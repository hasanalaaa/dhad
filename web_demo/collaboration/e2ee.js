const ENVELOPE_MAGIC = new Uint8Array([0x44, 0x48, 0x45, 0x34]); // DHE4
const ENVELOPE_HEADER_BYTES = 20;
const GROUP_MAGIC = new Uint8Array([0x44, 0x48, 0x47, 0x34]); // DHG4
const GROUP_HEADER_BYTES = 18;
const ED25519_SIGNATURE_BYTES = 64;
const PROTOCOL_VERSION = 1;
const MAX_U64 = (1n << 64n) - 1n;
const REPLAY_WINDOW = 256n;
const textEncoder = new TextEncoder();

function cryptoProvider() {
  if (!globalThis.crypto?.subtle) throw new Error("WebCrypto SubtleCrypto is required");
  return globalThis.crypto;
}

function bytes(value) {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  throw new TypeError("Expected binary data");
}

function base64urlEncode(value) {
  const data = bytes(value);
  let binary = "";
  for (const byte of data) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

function base64urlDecode(value, { maxBytes = 1024 * 1024, expectedBytes = null } = {}) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/u.test(value)) {
    throw new ValueError("Invalid base64url value");
  }
  const upperBound = Math.ceil((value.length * 3) / 4);
  if (upperBound > maxBytes) throw new ValueError("base64url value exceeds the byte budget");
  const padded = value.replaceAll("-", "+").replaceAll("_", "/").padEnd(
    Math.ceil(value.length / 4) * 4,
    "=",
  );
  const decoded = Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
  if (expectedBytes !== null && decoded.byteLength !== expectedBytes) {
    throw new ValueError("base64url value has an invalid length");
  }
  return decoded;
}

class ValueError extends Error {
  constructor(message) {
    super(message);
    this.name = "ValueError";
  }
}

export class DhadCryptoError extends Error {
  constructor(code, message, options) {
    super(message, options);
    this.name = "DhadCryptoError";
    this.code = code;
  }
}

function validateIdentifier(value, name) {
  if (typeof value !== "string" || value.length < 1 || value.length > 128) {
    throw new ValueError(`${name} must contain 1-128 characters`);
  }
  return value;
}

function validateEpoch(value) {
  if (!Number.isSafeInteger(value) || value < 1 || value > 0xffff_ffff) {
    throw new ValueError("epoch must be an unsigned 32-bit positive integer");
  }
  return value;
}

async function fingerprint(rawPublicKey, crypto = cryptoProvider()) {
  return base64urlEncode(await crypto.subtle.digest("SHA-256", bytes(rawPublicKey)));
}

function announcementBytes(announcement) {
  return textEncoder.encode(
    JSON.stringify([
      announcement.v,
      announcement.room,
      announcement.member,
      announcement.epoch,
      announcement.key,
      announcement.identity,
    ]),
  );
}

function additionalData(roomId, epoch, sender, recipient, sequence) {
  return textEncoder.encode(
    JSON.stringify([
      "dhad-e2ee-v1",
      roomId,
      epoch,
      sender,
      recipient,
      sequence.toString(),
    ]),
  );
}

function nonce(epoch, sequence) {
  const value = new Uint8Array(12);
  const view = new DataView(value.buffer);
  view.setUint32(0, epoch, false);
  view.setBigUint64(4, sequence, false);
  return value;
}

function packEnvelope(epoch, sequence, sender, recipient, ciphertext) {
  const senderBytes = textEncoder.encode(sender);
  const recipientBytes = textEncoder.encode(recipient);
  if (senderBytes.length > 0xffff || recipientBytes.length > 0xffff) {
    throw new ValueError("Envelope identity is too long");
  }
  const encrypted = bytes(ciphertext);
  const result = new Uint8Array(
    ENVELOPE_HEADER_BYTES + senderBytes.length + recipientBytes.length + encrypted.length,
  );
  result.set(ENVELOPE_MAGIC, 0);
  const view = new DataView(result.buffer);
  view.setUint32(4, epoch, false);
  view.setBigUint64(8, sequence, false);
  view.setUint16(16, senderBytes.length, false);
  view.setUint16(18, recipientBytes.length, false);
  result.set(senderBytes, ENVELOPE_HEADER_BYTES);
  result.set(recipientBytes, ENVELOPE_HEADER_BYTES + senderBytes.length);
  result.set(encrypted, ENVELOPE_HEADER_BYTES + senderBytes.length + recipientBytes.length);
  return result;
}

function unpackEnvelope(value) {
  const data = bytes(value);
  if (data.length < ENVELOPE_HEADER_BYTES) throw new ValueError("Invalid E2EE envelope");
  for (let index = 0; index < ENVELOPE_MAGIC.length; index += 1) {
    if (data[index] !== ENVELOPE_MAGIC[index]) throw new ValueError("Invalid E2EE envelope");
  }
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const epoch = view.getUint32(4, false);
  const sequence = view.getBigUint64(8, false);
  if (epoch === 0 || sequence === 0n) throw new ValueError("Invalid E2EE envelope sequence");
  const senderLength = view.getUint16(16, false);
  const recipientLength = view.getUint16(18, false);
  const metadataEnd = ENVELOPE_HEADER_BYTES + senderLength + recipientLength;
  if (metadataEnd >= data.length) throw new ValueError("Invalid E2EE envelope");
  const decoder = new TextDecoder("utf-8", { fatal: true });
  try {
    return {
      epoch,
      sequence,
      sender: decoder.decode(data.subarray(ENVELOPE_HEADER_BYTES, ENVELOPE_HEADER_BYTES + senderLength)),
      recipient: decoder.decode(data.subarray(ENVELOPE_HEADER_BYTES + senderLength, metadataEnd)),
      ciphertext: data.subarray(metadataEnd),
    };
  } catch (error) {
    throw new ValueError("Invalid E2EE envelope identity encoding", { cause: error });
  }
}

function packGroupEnvelope(epoch, sequence, sender, ciphertext, signature) {
  const senderBytes = textEncoder.encode(sender);
  const encrypted = bytes(ciphertext);
  const signed = bytes(signature);
  if (senderBytes.length > 0xffff || signed.length !== ED25519_SIGNATURE_BYTES) {
    throw new ValueError("Invalid signed group envelope metadata");
  }
  const result = new Uint8Array(
    GROUP_HEADER_BYTES + senderBytes.length + encrypted.length + signed.length,
  );
  result.set(GROUP_MAGIC, 0);
  const view = new DataView(result.buffer);
  view.setUint32(4, epoch, false);
  view.setBigUint64(8, sequence, false);
  view.setUint16(16, senderBytes.length, false);
  result.set(senderBytes, GROUP_HEADER_BYTES);
  result.set(encrypted, GROUP_HEADER_BYTES + senderBytes.length);
  result.set(signed, result.length - signed.length);
  return result;
}

function unsignedGroupEnvelope(epoch, sequence, sender, ciphertext) {
  const placeholder = new Uint8Array(ED25519_SIGNATURE_BYTES);
  const packed = packGroupEnvelope(epoch, sequence, sender, ciphertext, placeholder);
  return packed.subarray(0, packed.length - ED25519_SIGNATURE_BYTES);
}

function unpackGroupEnvelope(value) {
  const data = bytes(value);
  if (data.length < GROUP_HEADER_BYTES + ED25519_SIGNATURE_BYTES + 16) {
    throw new ValueError("Invalid signed group envelope");
  }
  for (let index = 0; index < GROUP_MAGIC.length; index += 1) {
    if (data[index] !== GROUP_MAGIC[index]) throw new ValueError("Invalid signed group envelope");
  }
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const epoch = view.getUint32(4, false);
  const sequence = view.getBigUint64(8, false);
  if (epoch === 0 || sequence === 0n) throw new ValueError("Invalid group envelope sequence");
  const senderLength = view.getUint16(16, false);
  const ciphertextStart = GROUP_HEADER_BYTES + senderLength;
  const signatureStart = data.length - ED25519_SIGNATURE_BYTES;
  if (ciphertextStart >= signatureStart) throw new ValueError("Invalid signed group envelope");
  try {
    const sender = new TextDecoder("utf-8", { fatal: true }).decode(
      data.subarray(GROUP_HEADER_BYTES, ciphertextStart),
    );
    return {
      epoch,
      sequence,
      sender,
      ciphertext: data.subarray(ciphertextStart, signatureStart),
      signature: data.subarray(signatureStart),
      signedBytes: data.subarray(0, signatureStart),
    };
  } catch (error) {
    throw new ValueError("Invalid group sender identity", { cause: error });
  }
}

class ReplayWindow {
  constructor() {
    this.maximum = 0n;
    this.seen = new Set();
  }

  assertFresh(sequence) {
    const marker = sequence.toString();
    if (this.seen.has(marker) || (this.maximum >= REPLAY_WINDOW && sequence <= this.maximum - REPLAY_WINDOW)) {
      throw new DhadCryptoError("replay", "Replay attack rejected");
    }
  }

  commit(sequence) {
    this.seen.add(sequence.toString());
    if (sequence > this.maximum) this.maximum = sequence;
    const minimum = this.maximum > REPLAY_WINDOW ? this.maximum - REPLAY_WINDOW : 0n;
    for (const marker of this.seen) {
      if (BigInt(marker) < minimum) this.seen.delete(marker);
    }
  }
}

async function deriveDirectionalKey(sharedSecret, salt, sender, recipient, usage, crypto) {
  const material = await crypto.subtle.importKey("raw", sharedSecret, "HKDF", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    {
      name: "HKDF",
      hash: "SHA-256",
      salt,
      info: textEncoder.encode(`dhad-e2ee-v1\u0000${sender}\u0000${recipient}`),
    },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    [usage],
  );
}

export async function createIdentity({ crypto = cryptoProvider() } = {}) {
  const keyPair = await crypto.subtle.generateKey({ name: "Ed25519" }, false, ["sign", "verify"]);
  const publicKeyRaw = new Uint8Array(await crypto.subtle.exportKey("raw", keyPair.publicKey));
  return Object.freeze({
    privateKey: keyPair.privateKey,
    publicKey: keyPair.publicKey,
    publicKeyRaw,
    fingerprint: await fingerprint(publicKeyRaw, crypto),
  });
}

export class EncryptedSession {
  static async create({
    roomId,
    memberId,
    identity,
    epoch = 1,
    isLeader = false,
    crypto = cryptoProvider(),
  }) {
    const session = new EncryptedSession({ roomId, memberId, identity, epoch, isLeader, crypto });
    await session.#generateEpochKey();
    if (isLeader) await session.enableGroupLeader();
    return session;
  }

  constructor({ roomId, memberId, identity, epoch, isLeader, crypto }) {
    this.roomId = validateIdentifier(roomId, "roomId");
    this.memberId = validateIdentifier(memberId, "memberId");
    this.identity = identity;
    if (!identity?.privateKey || !identity?.publicKeyRaw || !identity?.fingerprint) {
      throw new TypeError("A persistent Ed25519 identity is required");
    }
    this.epoch = validateEpoch(epoch);
    this.crypto = crypto;
    this.peers = new Map();
    this.epochKeyPair = null;
    this.epochPublicKeyRaw = null;
    this.isLeader = Boolean(isLeader);
    this.groupKeyRaw = null;
    this.groupKeyCache = new Map();
    this.groupSendSequence = 0n;
  }

  async #generateEpochKey() {
    this.epochKeyPair = await this.crypto.subtle.generateKey(
      { name: "X25519" },
      false,
      ["deriveBits"],
    );
    this.epochPublicKeyRaw = new Uint8Array(
      await this.crypto.subtle.exportKey("raw", this.epochKeyPair.publicKey),
    );
  }

  async announcement() {
    const unsigned = {
      v: PROTOCOL_VERSION,
      room: this.roomId,
      member: this.memberId,
      epoch: this.epoch,
      key: base64urlEncode(this.epochPublicKeyRaw),
      identity: base64urlEncode(this.identity.publicKeyRaw),
    };
    const signature = await this.crypto.subtle.sign(
      { name: "Ed25519" },
      this.identity.privateKey,
      announcementBytes(unsigned),
    );
    return Object.freeze({ ...unsigned, signature: base64urlEncode(signature) });
  }

  async verifyPeerAnnouncement(
    announcement,
    { expectedFingerprint, expectedEpoch = this.epoch } = {},
  ) {
    if (announcement?.v !== PROTOCOL_VERSION || announcement.room !== this.roomId) {
      throw new ValueError("Peer announcement protocol or room mismatch");
    }
    validateIdentifier(announcement.member, "peer member");
    if (announcement.member === this.memberId) throw new ValueError("Cannot accept our own peer key");
    if (announcement.epoch !== expectedEpoch) throw new Error("Peer epoch does not match expected epoch");
    if (typeof expectedFingerprint !== "string" || !expectedFingerprint) {
      throw new Error("A pinned peer identity fingerprint is required");
    }
    const identityRaw = base64urlDecode(announcement.identity, { expectedBytes: 32 });
    const actualFingerprint = await fingerprint(identityRaw, this.crypto);
    if (actualFingerprint !== expectedFingerprint) {
      throw new Error("Peer identity fingerprint mismatch");
    }
    const identityKey = await this.crypto.subtle.importKey(
      "raw",
      identityRaw,
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    const valid = await this.crypto.subtle.verify(
      { name: "Ed25519" },
      identityKey,
      base64urlDecode(announcement.signature, { expectedBytes: ED25519_SIGNATURE_BYTES }),
      announcementBytes(announcement),
    );
    if (!valid) throw new Error("Peer epoch-key signature verification failed");
    return { actualFingerprint, identityKey };
  }

  async acceptPeer(announcement, { expectedFingerprint } = {}) {
    const { actualFingerprint, identityKey } = await this.verifyPeerAnnouncement(announcement, {
      expectedFingerprint,
      expectedEpoch: this.epoch,
    });
    const existing = this.peers.get(announcement.member);
    if (existing) {
      if (
        existing.fingerprint === actualFingerprint &&
        existing.epochKey === announcement.key
      ) {
        return;
      }
      throw new Error("Peer changed its X25519 key without rotating the epoch");
    }

    const peerPublicKey = await this.crypto.subtle.importKey(
      "raw",
      base64urlDecode(announcement.key, { expectedBytes: 32 }),
      { name: "X25519" },
      false,
      [],
    );
    const sharedSecret = await this.crypto.subtle.deriveBits(
      { name: "X25519", public: peerPublicKey },
      this.epochKeyPair.privateKey,
      256,
    );
    const salt = await this.crypto.subtle.digest(
      "SHA-256",
      textEncoder.encode(JSON.stringify(["dhad-e2ee-v1", this.roomId, this.epoch])),
    );
    const sendKey = await deriveDirectionalKey(
      sharedSecret,
      salt,
      this.memberId,
      announcement.member,
      "encrypt",
      this.crypto,
    );
    const receiveKey = await deriveDirectionalKey(
      sharedSecret,
      salt,
      announcement.member,
      this.memberId,
      "decrypt",
      this.crypto,
    );
    this.peers.set(announcement.member, {
      sendKey,
      receiveKey,
      sendSequence: 0n,
      replay: new ReplayWindow(),
      decryptChain: Promise.resolve(),
      fingerprint: actualFingerprint,
      epochKey: announcement.key,
      identityKey,
      groupReplay: new ReplayWindow(),
      groupDecryptChain: Promise.resolve(),
    });
  }

  get hasGroupKey() {
    return this.groupKeyRaw !== null;
  }

  async enableGroupLeader() {
    this.groupKeyRaw?.fill(0);
    const key = new Uint8Array(32);
    this.crypto.getRandomValues(key);
    this.groupKeyRaw = key;
    this.groupKeyCache.clear();
    this.groupSendSequence = 0n;
    this.isLeader = true;
  }

  async createGroupKeyPackage(recipient) {
    if (!this.isLeader || this.groupKeyRaw === null) {
      throw new Error("Only the active group leader can distribute an epoch key");
    }
    return this.encrypt(recipient, this.groupKeyRaw);
  }

  async acceptGroupKeyPackage(envelope, { expectedLeader } = {}) {
    const metadata = unpackEnvelope(envelope);
    if (typeof expectedLeader !== "string" || metadata.sender !== expectedLeader) {
      throw new Error("Group key package did not come from the pinned epoch leader");
    }
    const key = await this.decrypt(envelope);
    if (key.length !== 32) throw new Error("Invalid AES-256 group epoch key");
    this.groupKeyRaw?.fill(0);
    this.groupKeyRaw = key.slice();
    this.groupKeyCache.clear();
    this.groupSendSequence = 0n;
    this.isLeader = false;
  }

  async #groupKey(sender, usage) {
    if (this.groupKeyRaw === null) {
      throw new DhadCryptoError(
        "missing_group_key",
        "No authenticated group epoch key installed",
      );
    }
    const cacheKey = `${sender}:${usage}`;
    let key = this.groupKeyCache.get(cacheKey);
    if (key) return key;
    const salt = await this.crypto.subtle.digest(
      "SHA-256",
      textEncoder.encode(JSON.stringify(["dhad-group-v1", this.roomId, this.epoch])),
    );
    key = await deriveDirectionalKey(
      this.groupKeyRaw,
      salt,
      sender,
      "broadcast",
      usage,
      this.crypto,
    );
    this.groupKeyCache.set(cacheKey, key);
    return key;
  }

  async encryptBroadcast(plaintext) {
    if (this.groupSendSequence >= MAX_U64) {
      throw new Error("Group sequence space exhausted; rotate epoch");
    }
    this.groupSendSequence += 1n;
    const key = await this.#groupKey(this.memberId, "encrypt");
    const ciphertext = await this.crypto.subtle.encrypt(
      {
        name: "AES-GCM",
        iv: nonce(this.epoch, this.groupSendSequence),
        additionalData: additionalData(
          this.roomId,
          this.epoch,
          this.memberId,
          "broadcast",
          this.groupSendSequence,
        ),
        tagLength: 128,
      },
      key,
      bytes(plaintext),
    );
    const unsigned = unsignedGroupEnvelope(
      this.epoch,
      this.groupSendSequence,
      this.memberId,
      ciphertext,
    );
    const signature = await this.crypto.subtle.sign(
      { name: "Ed25519" },
      this.identity.privateKey,
      unsigned,
    );
    return packGroupEnvelope(
      this.epoch,
      this.groupSendSequence,
      this.memberId,
      ciphertext,
      signature,
    );
  }

  async decryptBroadcast(envelope) {
    const parsed = unpackGroupEnvelope(envelope);
    if (parsed.epoch !== this.epoch) {
      throw new DhadCryptoError("epoch_mismatch", "Group ciphertext epoch is stale or unknown");
    }
    const peer = this.peers.get(parsed.sender);
    if (!peer) {
      throw new DhadCryptoError(
        "missing_peer_key",
        `No pinned identity for group sender ${parsed.sender}`,
      );
    }
    const operation = peer.groupDecryptChain.then(async () => {
      peer.groupReplay.assertFresh(parsed.sequence);
      const signatureValid = await this.crypto.subtle.verify(
        { name: "Ed25519" },
        peer.identityKey,
        parsed.signature,
        parsed.signedBytes,
      );
      if (!signatureValid) throw new Error("Group sender signature verification failed");
      const key = await this.#groupKey(parsed.sender, "decrypt");
      let plaintext;
      try {
        plaintext = await this.crypto.subtle.decrypt(
          {
            name: "AES-GCM",
            iv: nonce(parsed.epoch, parsed.sequence),
            additionalData: additionalData(
              this.roomId,
              parsed.epoch,
              parsed.sender,
              "broadcast",
              parsed.sequence,
            ),
            tagLength: 128,
          },
          key,
          parsed.ciphertext,
        );
      } catch (error) {
        throw new Error("Group ciphertext authentication failed", { cause: error });
      }
      peer.groupReplay.commit(parsed.sequence);
      return new Uint8Array(plaintext);
    });
    peer.groupDecryptChain = operation.catch(() => {});
    return operation;
  }

  async encrypt(recipient, plaintext) {
    const peer = this.peers.get(recipient);
    if (!peer) {
      throw new DhadCryptoError(
        "missing_peer_key",
        `No authenticated epoch key for peer ${recipient}`,
      );
    }
    if (peer.sendSequence >= MAX_U64) throw new Error("E2EE sequence space exhausted; rotate epoch");
    peer.sendSequence += 1n;
    const iv = nonce(this.epoch, peer.sendSequence);
    const ciphertext = await this.crypto.subtle.encrypt(
      {
        name: "AES-GCM",
        iv,
        additionalData: additionalData(
          this.roomId,
          this.epoch,
          this.memberId,
          recipient,
          peer.sendSequence,
        ),
        tagLength: 128,
      },
      peer.sendKey,
      bytes(plaintext),
    );
    return packEnvelope(this.epoch, peer.sendSequence, this.memberId, recipient, ciphertext);
  }

  async decrypt(envelope) {
    const parsed = unpackEnvelope(envelope);
    if (parsed.epoch !== this.epoch) {
      throw new DhadCryptoError("epoch_mismatch", "Ciphertext epoch is stale or unknown");
    }
    if (parsed.recipient !== this.memberId) throw new Error("Ciphertext recipient mismatch");
    const peer = this.peers.get(parsed.sender);
    if (!peer) {
      throw new DhadCryptoError(
        "missing_peer_key",
        `No authenticated epoch key for peer ${parsed.sender}`,
      );
    }

    const operation = peer.decryptChain.then(async () => {
      peer.replay.assertFresh(parsed.sequence);
      let plaintext;
      try {
        plaintext = await this.crypto.subtle.decrypt(
          {
            name: "AES-GCM",
            iv: nonce(parsed.epoch, parsed.sequence),
            additionalData: additionalData(
              this.roomId,
              parsed.epoch,
              parsed.sender,
              parsed.recipient,
              parsed.sequence,
            ),
            tagLength: 128,
          },
          peer.receiveKey,
          parsed.ciphertext,
        );
      } catch (error) {
        throw new Error("Ciphertext authentication failed", { cause: error });
      }
      peer.replay.commit(parsed.sequence);
      return new Uint8Array(plaintext);
    });
    peer.decryptChain = operation.catch(() => {});
    return operation;
  }

  async rotateEpoch(nextEpoch) {
    validateEpoch(nextEpoch);
    if (nextEpoch <= this.epoch) throw new ValueError("Epochs must increase monotonically");
    this.epoch = nextEpoch;
    this.peers.clear();
    this.groupKeyRaw?.fill(0);
    this.groupKeyRaw = null;
    this.groupKeyCache.clear();
    this.groupSendSequence = 0n;
    await this.#generateEpochKey();
    if (this.isLeader) await this.enableGroupLeader();
  }
}
