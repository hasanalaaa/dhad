import assert from "node:assert/strict";
import test from "node:test";

const encoder = new TextEncoder();
const decoder = new TextDecoder();

async function pairedSessions() {
  const { createIdentity, EncryptedSession } = await import("./e2ee.js");
  const aliceIdentity = await createIdentity();
  const bobIdentity = await createIdentity();
  const alice = await EncryptedSession.create({
    roomId: "arabic-doc",
    memberId: "alice",
    identity: aliceIdentity,
  });
  const bob = await EncryptedSession.create({
    roomId: "arabic-doc",
    memberId: "bob",
    identity: bobIdentity,
  });
  await alice.acceptPeer(await bob.announcement(), {
    expectedFingerprint: bobIdentity.fingerprint,
  });
  await bob.acceptPeer(await alice.announcement(), {
    expectedFingerprint: aliceIdentity.fingerprint,
  });
  return { alice, bob, aliceIdentity, bobIdentity };
}

test("X25519 peers derive directional AES-256-GCM keys and decrypt Arabic", async () => {
  const { alice, bob } = await pairedSessions();
  const plaintext = encoder.encode("تحديث Yjs سري");

  const envelope = await alice.encrypt("bob", plaintext);
  assert.equal(Buffer.from(envelope).includes(Buffer.from(plaintext)), false);
  assert.equal(decoder.decode(await bob.decrypt(envelope)), "تحديث Yjs سري");
});

test("identity pinning rejects a server-substituted key announcement", async () => {
  const { createIdentity, EncryptedSession } = await import("./e2ee.js");
  const aliceIdentity = await createIdentity();
  const malloryIdentity = await createIdentity();
  const alice = await EncryptedSession.create({
    roomId: "room",
    memberId: "alice",
    identity: aliceIdentity,
  });
  const mallory = await EncryptedSession.create({
    roomId: "room",
    memberId: "bob",
    identity: malloryIdentity,
  });

  await assert.rejects(
    alice.acceptPeer(await mallory.announcement(), {
      expectedFingerprint: aliceIdentity.fingerprint,
    }),
    /identity fingerprint/i,
  );
});

test("authenticated ciphertext tampering and replay are both rejected", async () => {
  const { alice, bob } = await pairedSessions();
  const envelope = await alice.encrypt("bob", encoder.encode("سري"));
  const tampered = envelope.slice();
  tampered[tampered.length - 1] ^= 1;

  await assert.rejects(bob.decrypt(tampered), /authentication/i);
  assert.equal(decoder.decode(await bob.decrypt(envelope)), "سري");
  await assert.rejects(bob.decrypt(envelope), /replay/i);
});

test("bounded replay window accepts out-of-order unique messages", async () => {
  const { alice, bob } = await pairedSessions();
  const first = await alice.encrypt("bob", encoder.encode("1"));
  const second = await alice.encrypt("bob", encoder.encode("2"));

  assert.equal(decoder.decode(await bob.decrypt(second)), "2");
  assert.equal(decoder.decode(await bob.decrypt(first)), "1");
});

test("epoch rotation invalidates old ciphertext and requires fresh peer keys", async () => {
  const { alice, bob, aliceIdentity, bobIdentity } = await pairedSessions();
  const old = await alice.encrypt("bob", encoder.encode("قديم"));
  await alice.rotateEpoch(2);
  await bob.rotateEpoch(2);

  await assert.rejects(bob.decrypt(old), /epoch/i);
  await alice.acceptPeer(await bob.announcement(), {
    expectedFingerprint: bobIdentity.fingerprint,
  });
  await bob.acceptPeer(await alice.announcement(), {
    expectedFingerprint: aliceIdentity.fingerprint,
  });
  const fresh = await alice.encrypt("bob", encoder.encode("جديد"));
  assert.equal(decoder.decode(await bob.decrypt(fresh)), "جديد");
});

test("leader distributes one room epoch key over pinned X25519 channels", async () => {
  const { createIdentity, EncryptedSession } = await import("./e2ee.js");
  const identities = {
    alice: await createIdentity(),
    bob: await createIdentity(),
    carol: await createIdentity(),
  };
  const alice = await EncryptedSession.create({
    roomId: "group",
    memberId: "alice",
    identity: identities.alice,
    isLeader: true,
  });
  const bob = await EncryptedSession.create({
    roomId: "group",
    memberId: "bob",
    identity: identities.bob,
  });
  const carol = await EncryptedSession.create({
    roomId: "group",
    memberId: "carol",
    identity: identities.carol,
  });

  for (const member of [bob, carol]) {
    await alice.acceptPeer(await member.announcement(), {
      expectedFingerprint: identities[member.memberId].fingerprint,
    });
    await member.acceptPeer(await alice.announcement(), {
      expectedFingerprint: identities.alice.fingerprint,
    });
    await member.acceptGroupKeyPackage(await alice.createGroupKeyPackage(member.memberId), {
      expectedLeader: "alice",
    });
  }

  const encryptedSnapshot = await alice.encryptBroadcast(encoder.encode("لقطة Yjs كاملة"));
  assert.equal(decoder.decode(await bob.decryptBroadcast(encryptedSnapshot)), "لقطة Yjs كاملة");
  assert.equal(decoder.decode(await carol.decryptBroadcast(encryptedSnapshot)), "لقطة Yjs كاملة");
  await assert.rejects(bob.decryptBroadcast(encryptedSnapshot), /replay/i);
});

test("group members cannot forge another member's signed broadcast", async () => {
  const { alice, bob } = await pairedSessions();
  await alice.enableGroupLeader();
  await bob.acceptGroupKeyPackage(await alice.createGroupKeyPackage("bob"), {
    expectedLeader: "alice",
  });
  const authentic = await alice.encryptBroadcast(encoder.encode("أصلي"));
  const forged = authentic.slice();
  const senderOffset = 18;
  forged[senderOffset] = "b".charCodeAt(0);
  await assert.rejects(bob.decryptBroadcast(forged), /signature|identity|authentication/i);
});

test("duplicate epoch announcements never reset replay state", async () => {
  const { alice, bob, aliceIdentity } = await pairedSessions();
  const encrypted = await alice.encrypt("bob", encoder.encode("مرة واحدة"));
  await bob.decrypt(encrypted);

  await bob.acceptPeer(await alice.announcement(), {
    expectedFingerprint: aliceIdentity.fingerprint,
  });

  await assert.rejects(bob.decrypt(encrypted), /replay/i);
});

test("zero sequence envelopes are rejected before any cryptographic work", async () => {
  const { alice, bob } = await pairedSessions();
  const envelope = await alice.encrypt("bob", encoder.encode("payload"));
  envelope.fill(0, 8, 16);
  await assert.rejects(bob.decrypt(envelope), /invalid.*sequence/i);
});

test("replacing a group epoch key zeroizes the previous raw key material", async () => {
  const { alice, bob } = await pairedSessions();
  await alice.enableGroupLeader();
  await bob.acceptGroupKeyPackage(await alice.createGroupKeyPackage("bob"), {
    expectedLeader: "alice",
  });
  const previous = bob.groupKeyRaw;
  assert.equal(previous.some((value) => value !== 0), true);
  await alice.enableGroupLeader();
  await bob.acceptGroupKeyPackage(await alice.createGroupKeyPackage("bob"), {
    expectedLeader: "alice",
  });
  assert.equal(previous.every((value) => value === 0), true);
});
