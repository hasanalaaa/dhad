import * as Y from "yjs";

const FRAME_UPDATE = 1;
const FRAME_SNAPSHOT = 2;
const FRAME_KEY_ANNOUNCEMENT = 3;
const CLIENT_MAGIC = new Uint8Array([0x44, 0x48, 0x43, 0x34]); // DHC4
const SERVER_MAGIC = new Uint8Array([0x44, 0x48, 0x53, 0x34]); // DHS4
const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder("utf-8", { fatal: true });

function bytes(value) {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  throw new TypeError("Expected binary collaboration data");
}

function base64urlEncode(value) {
  let binary = "";
  for (const byte of bytes(value)) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

function base64urlDecode(value, maxBytes) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/u.test(value)) {
    throw new Error("Invalid base64url key package");
  }
  if (Math.ceil((value.length * 3) / 4) > maxBytes) {
    throw new Error("Key package exceeds the collaboration byte budget");
  }
  const padded = value.replaceAll("-", "+").replaceAll("_", "/").padEnd(
    Math.ceil(value.length / 4) * 4,
    "=",
  );
  return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
}

function packClientFrame(kind, payload) {
  if (![FRAME_UPDATE, FRAME_SNAPSHOT, FRAME_KEY_ANNOUNCEMENT].includes(kind)) {
    throw new Error("Unsupported collaboration frame kind");
  }
  const opaque = bytes(payload);
  const frame = new Uint8Array(5 + opaque.length);
  frame.set(CLIENT_MAGIC, 0);
  frame[4] = kind;
  frame.set(opaque, 5);
  return frame;
}

function unpackServerFrame(value) {
  const frame = bytes(value);
  if (frame.length < 9) throw new Error("Invalid Dhad server frame");
  for (let index = 0; index < SERVER_MAGIC.length; index += 1) {
    if (frame[index] !== SERVER_MAGIC[index]) throw new Error("Invalid Dhad server frame");
  }
  const view = new DataView(frame.buffer, frame.byteOffset, frame.byteLength);
  const cursorLength = view.getUint16(5, false);
  const senderLength = view.getUint16(7, false);
  const payloadStart = 9 + cursorLength + senderLength;
  if (payloadStart > frame.length) throw new Error("Invalid Dhad server frame metadata");
  return { kind: frame[4], payload: frame.subarray(payloadStart) };
}

export class SecureYjsProvider {
  constructor({
    doc,
    session,
    transport,
    leaderId,
    trustedFingerprints,
    maxPendingBytes = 4 * 1024 * 1024,
    maxPendingKeyPackages = 64,
    snapshotEveryUpdates = 500,
  }) {
    if (!(doc instanceof Y.Doc)) throw new TypeError("SecureYjsProvider requires a Y.Doc");
    if (!session || !transport) throw new TypeError("An E2EE session and transport are required");
    if (typeof leaderId !== "string" || !leaderId) throw new TypeError("leaderId is required");
    if (!(maxPendingBytes > 0)) throw new TypeError("maxPendingBytes must be positive");
    if (!Number.isInteger(maxPendingKeyPackages) || maxPendingKeyPackages < 1) {
      throw new TypeError("maxPendingKeyPackages must be a positive integer");
    }
    if (!Number.isInteger(snapshotEveryUpdates) || snapshotEveryUpdates < 1) {
      throw new TypeError("snapshotEveryUpdates must be a positive integer");
    }
    this.doc = doc;
    this.session = session;
    this.transport = transport;
    this.leaderId = leaderId;
    this.trustedFingerprints = trustedFingerprints;
    this.maxPendingBytes = maxPendingBytes;
    this.maxPendingKeyPackages = maxPendingKeyPackages;
    this.snapshotEveryUpdates = snapshotEveryUpdates;
    this.updatesSinceSnapshot = 0;
    this.pendingUpdates = [];
    this.pendingBytes = 0;
    this.pendingGroupPackages = [];
    this.pendingGroupPackageBytes = 0;
    this.pendingInbound = [];
    this.pendingInboundBytes = 0;
    this.origin = Object.freeze({ provider: this });
    this.started = false;
    this.outbound = Promise.resolve();
    this.outboundError = null;
    this.localUpdate = (update, origin) => {
      if (origin === this.origin) return;
      const copy = new Uint8Array(update);
      this.#enqueueOutbound(() => this.#queueOrSend(copy));
    };
  }

  #reportError(error) {
    this.outboundError ??= error;
    try {
      this.transport.onError?.(error);
    } catch {
      // Reporting must never poison the collaboration queue.
    }
  }

  #enqueueOutbound(operation) {
    this.outbound = this.outbound
      .then(operation, operation)
      .catch((error) => this.#reportError(error));
  }

  #fingerprint(member) {
    const value =
      typeof this.trustedFingerprints === "function"
        ? this.trustedFingerprints(member)
        : this.trustedFingerprints?.get(member);
    if (typeof value !== "string" || !value) {
      throw new Error(`No pinned identity fingerprint for member ${member}`);
    }
    return value;
  }

  start() {
    if (this.started) return;
    this.started = true;
    this.doc.on("update", this.localUpdate);
    this.transport.onOpen = () => {
      this.announce().catch((error) => this.#reportError(error));
    };
    this.transport.onFrame = (frame) => {
      this.receiveServerFrame(frame).catch((error) => this.#reportError(error));
    };
  }

  connect() {
    this.start();
    return this.transport.connect();
  }

  stop() {
    if (!this.started) return;
    this.started = false;
    this.doc.off("update", this.localUpdate);
  }

  close() {
    this.stop();
    this.transport.close();
  }

  async announce() {
    const payload = textEncoder.encode(
      JSON.stringify({ type: "epoch-key", announcement: await this.session.announcement() }),
    );
    this.transport.send(packClientFrame(FRAME_KEY_ANNOUNCEMENT, payload));
  }

  async #sendGroupPackage(recipient) {
    const envelope = await this.session.createGroupKeyPackage(recipient);
    const payload = textEncoder.encode(
      JSON.stringify({
        type: "group-key",
        leader: this.session.memberId,
        recipient,
        envelope: base64urlEncode(envelope),
      }),
    );
    this.transport.send(packClientFrame(FRAME_KEY_ANNOUNCEMENT, payload));
  }

  async #handleKeyMessage(payload) {
    let message;
    try {
      message = JSON.parse(textDecoder.decode(payload));
    } catch (error) {
      throw new Error("Invalid signed key-announcement frame", { cause: error });
    }
    if (message?.type === "epoch-key") {
      const member = message.announcement?.member;
      if (member === this.session.memberId) return;
      if (message.announcement?.epoch > this.session.epoch) {
        if (member !== this.leaderId) {
          throw new Error("Only the pinned leader may advance the room epoch");
        }
        const expectedFingerprint = this.#fingerprint(member);
        await this.session.verifyPeerAnnouncement(message.announcement, {
          expectedFingerprint,
          expectedEpoch: message.announcement.epoch,
        });
        await this.session.rotateEpoch(message.announcement.epoch);
        await this.session.acceptPeer(message.announcement, { expectedFingerprint });
        await this.announce();
        return;
      }
      if (message.announcement?.epoch < this.session.epoch) return;
      await this.session.acceptPeer(message.announcement, {
        expectedFingerprint: this.#fingerprint(member),
      });
      if (this.session.isLeader) {
        // A reconnecting member may have resumed from a snapshot newer than
        // the leader's earlier public announcement. Re-announce before the
        // pairwise group-key package so it can always derive the X25519 KEK.
        await this.announce();
        await this.#sendGroupPackage(member);
      }
      const waiting = this.pendingGroupPackages;
      this.pendingGroupPackages = [];
      this.pendingGroupPackageBytes = 0;
      for (const pending of waiting) await this.#handleKeyMessage(pending);
      return;
    }
    if (message?.type === "group-key") {
      if (message.recipient !== this.session.memberId) return;
      if (message.leader !== this.leaderId) {
        throw new Error("Group-key package leader does not match the pinned leader");
      }
      try {
        await this.session.acceptGroupKeyPackage(
          base64urlDecode(message.envelope, this.maxPendingBytes),
          {
            expectedLeader: this.leaderId,
          },
        );
      } catch (error) {
        if (error?.code === "missing_peer_key") {
          if (
            this.pendingGroupPackages.length >= this.maxPendingKeyPackages ||
            this.pendingGroupPackageBytes + payload.length > this.maxPendingBytes
          ) {
            throw new Error("Pending group-key package budget exceeded", { cause: error });
          }
          this.pendingGroupPackages.push(payload.slice());
          this.pendingGroupPackageBytes += payload.length;
          return;
        }
        throw error;
      }
      await this.#flushPending();
      await this.#flushPendingInbound();
      return;
    }
    throw new Error("Unsupported key-announcement message");
  }

  async #queueOrSend(update) {
    if (!this.session.hasGroupKey) {
      if (this.pendingBytes + update.length > this.maxPendingBytes) {
        throw new Error("Pending encrypted collaboration update budget exceeded");
      }
      this.pendingUpdates.push(update);
      this.pendingBytes += update.length;
      return;
    }
    const encrypted = await this.session.encryptBroadcast(update);
    this.transport.send(packClientFrame(FRAME_UPDATE, encrypted));
    await this.#maybePublishSnapshot();
  }

  async #flushPending() {
    if (!this.session.hasGroupKey || this.pendingUpdates.length === 0) return;
    const merged = Y.mergeUpdates(this.pendingUpdates);
    this.pendingUpdates = [];
    this.pendingBytes = 0;
    await this.#queueOrSend(merged);
  }

  async #flushPendingInbound() {
    if (!this.session.hasGroupKey || this.pendingInbound.length === 0) return;
    const waiting = this.pendingInbound;
    this.pendingInbound = [];
    this.pendingInboundBytes = 0;
    for (const { kind, payload } of waiting) await this.receiveOpaqueFrame(kind, payload);
  }

  async rotateEpoch(nextEpoch) {
    if (!this.session.isLeader) throw new Error("Only the pinned leader may rotate the epoch");
    await this.session.rotateEpoch(nextEpoch);
    await this.announce();
  }

  async publishSnapshot() {
    if (!this.session.hasGroupKey) throw new Error("Cannot publish a snapshot before epoch setup");
    const encrypted = await this.session.encryptBroadcast(Y.encodeStateAsUpdate(this.doc));
    this.transport.send(packClientFrame(FRAME_SNAPSHOT, encrypted));
    this.updatesSinceSnapshot = 0;
  }

  async #maybePublishSnapshot() {
    this.updatesSinceSnapshot += 1;
    if (
      this.session.isLeader &&
      this.updatesSinceSnapshot >= this.snapshotEveryUpdates
    ) {
      await this.publishSnapshot();
    }
  }

  async receiveOpaqueFrame(kind, payload) {
    if (kind === FRAME_KEY_ANNOUNCEMENT) {
      await this.#handleKeyMessage(bytes(payload));
      return;
    }
    if (kind !== FRAME_UPDATE && kind !== FRAME_SNAPSHOT) {
      throw new Error("Unsupported collaboration frame kind");
    }
    const opaque = bytes(payload);
    let update;
    try {
      update = await this.session.decryptBroadcast(opaque);
    } catch (error) {
      if (error?.code === "replay") {
        // Redis Streams/PubSub intentionally provide at-least-once delivery.
        // Authenticated duplicates are discarded before reaching Yjs.
        return;
      }
      if (error?.code === "epoch_mismatch" || error?.code === "missing_group_key") {
        if (this.pendingInboundBytes + opaque.length > this.maxPendingBytes) {
          throw new Error("Pending inbound collaboration budget exceeded", { cause: error });
        }
        this.pendingInbound.push({ kind, payload: opaque.slice() });
        this.pendingInboundBytes += opaque.length;
        return;
      }
      throw error;
    }
    Y.applyUpdate(this.doc, update, this.origin);
    if (kind === FRAME_UPDATE) await this.#maybePublishSnapshot();
  }

  async receiveServerFrame(frame) {
    const { kind, payload } = unpackServerFrame(frame);
    await this.receiveOpaqueFrame(kind, payload);
  }

  async flush() {
    await this.outbound;
    await Promise.resolve();
    await this.outbound;
    if (this.outboundError !== null) {
      const error = this.outboundError;
      this.outboundError = null;
      throw error;
    }
  }
}
