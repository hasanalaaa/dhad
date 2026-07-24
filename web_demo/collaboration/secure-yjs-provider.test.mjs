import assert from "node:assert/strict";
import test from "node:test";

// Node 26 exposes an experimental localStorage getter that warns when Yjs
// feature-detects it. Browsers provide the real API; tests deliberately run
// without persistence.
Object.defineProperty(globalThis, "localStorage", {
  value: undefined,
  configurable: true,
});
const Y = await import("yjs");

class FakeTransport {
  constructor() {
    this.sent = [];
    this.onFrame = () => {};
  }
  connect() {}
  send(frame) {
    this.sent.push(new Uint8Array(frame));
  }
  close() {}
}

function unpackClientFrame(frame) {
  assert.equal(new TextDecoder().decode(frame.subarray(0, 4)), "DHC4");
  return { kind: frame[4], payload: frame.subarray(5) };
}

async function deliverAll(source, target) {
  while (source.sent.length) {
    const { kind, payload } = unpackClientFrame(source.sent.shift());
    await target.receiveOpaqueFrame(kind, payload);
  }
}

test("Yjs updates converge only after authenticated group-key establishment", async () => {
  const { createIdentity, EncryptedSession } = await import("./e2ee.js");
  const { SecureYjsProvider } = await import("./secure-yjs-provider.js");
  const aliceIdentity = await createIdentity();
  const bobIdentity = await createIdentity();
  const aliceSession = await EncryptedSession.create({
    roomId: "doc",
    memberId: "alice",
    identity: aliceIdentity,
    isLeader: true,
  });
  const bobSession = await EncryptedSession.create({
    roomId: "doc",
    memberId: "bob",
    identity: bobIdentity,
  });
  const aliceTransport = new FakeTransport();
  const bobTransport = new FakeTransport();
  const aliceDoc = new Y.Doc();
  const bobDoc = new Y.Doc();
  const alice = new SecureYjsProvider({
    doc: aliceDoc,
    session: aliceSession,
    transport: aliceTransport,
    leaderId: "alice",
    trustedFingerprints: new Map([["bob", bobIdentity.fingerprint]]),
  });
  const bob = new SecureYjsProvider({
    doc: bobDoc,
    session: bobSession,
    transport: bobTransport,
    leaderId: "alice",
    trustedFingerprints: new Map([["alice", aliceIdentity.fingerprint]]),
  });
  alice.start();
  bob.start();

  await alice.announce();
  await deliverAll(aliceTransport, bob);
  await bob.announce();
  await deliverAll(bobTransport, alice);
  await deliverAll(aliceTransport, bob);
  assert.equal(bobSession.hasGroupKey, true);

  aliceDoc.getText("text").insert(0, "نص تعاوني مشفر");
  await alice.flush();
  assert.equal(aliceTransport.sent.length, 1);
  assert.equal(Buffer.from(aliceTransport.sent[0]).includes(Buffer.from("نص تعاوني مشفر")), false);
  await deliverAll(aliceTransport, bob);
  await bob.flush();

  assert.equal(bobDoc.getText("text").toString(), "نص تعاوني مشفر");
  assert.equal(bobTransport.sent.length, 0, "remote apply must not echo as a local update");

  await alice.rotateEpoch(2);
  await deliverAll(aliceTransport, bob);
  await deliverAll(bobTransport, alice);
  await deliverAll(aliceTransport, bob);
  assert.equal(aliceSession.epoch, 2);
  assert.equal(bobSession.epoch, 2);
  assert.equal(bobSession.hasGroupKey, true);

  aliceDoc.getText("text").insert(aliceDoc.getText("text").length, " بعد التدوير");
  await alice.flush();
  await deliverAll(aliceTransport, bob);
  assert.equal(bobDoc.getText("text").toString(), "نص تعاوني مشفر بعد التدوير");
  alice.stop();
  bob.stop();
});

test("encrypted full-state snapshot recovers a newly created Y.Doc", async () => {
  const { createIdentity, EncryptedSession } = await import("./e2ee.js");
  const { SecureYjsProvider } = await import("./secure-yjs-provider.js");
  const leaderIdentity = await createIdentity();
  const peerIdentity = await createIdentity();
  const leaderSession = await EncryptedSession.create({
    roomId: "snapshot",
    memberId: "leader",
    identity: leaderIdentity,
    isLeader: true,
  });
  const peerSession = await EncryptedSession.create({
    roomId: "snapshot",
    memberId: "peer",
    identity: peerIdentity,
  });
  await leaderSession.acceptPeer(await peerSession.announcement(), {
    expectedFingerprint: peerIdentity.fingerprint,
  });
  await peerSession.acceptPeer(await leaderSession.announcement(), {
    expectedFingerprint: leaderIdentity.fingerprint,
  });
  await peerSession.acceptGroupKeyPackage(await leaderSession.createGroupKeyPackage("peer"), {
    expectedLeader: "leader",
  });
  const source = new Y.Doc();
  source.getText("text").insert(0, "حالة كاملة");
  const target = new Y.Doc();
  const sourceTransport = new FakeTransport();
  const targetTransport = new FakeTransport();
  const sourceProvider = new SecureYjsProvider({
    doc: source,
    session: leaderSession,
    transport: sourceTransport,
    leaderId: "leader",
    trustedFingerprints: new Map([["peer", peerIdentity.fingerprint]]),
  });
  const targetProvider = new SecureYjsProvider({
    doc: target,
    session: peerSession,
    transport: targetTransport,
    leaderId: "leader",
    trustedFingerprints: new Map([["leader", leaderIdentity.fingerprint]]),
  });

  await sourceProvider.publishSnapshot();
  const snapshot = unpackClientFrame(sourceTransport.sent.shift());
  assert.equal(snapshot.kind, 2);
  await targetProvider.receiveOpaqueFrame(snapshot.kind, snapshot.payload);
  assert.equal(target.getText("text").toString(), "حالة كاملة");
});

test("room leader emits periodic encrypted checkpoints before journal trimming", async () => {
  const { SecureYjsProvider } = await import("./secure-yjs-provider.js");
  const doc = new Y.Doc();
  const transport = new FakeTransport();
  const session = {
    hasGroupKey: true,
    isLeader: true,
    memberId: "leader",
    async encryptBroadcast(value) {
      return new Uint8Array(value);
    },
  };
  const provider = new SecureYjsProvider({
    doc,
    session,
    transport,
    leaderId: "leader",
    trustedFingerprints: new Map(),
    snapshotEveryUpdates: 2,
  });
  provider.start();
  doc.getText("text").insert(0, "أ");
  doc.getText("text").insert(1, "ب");
  await provider.flush();

  assert.deepEqual(transport.sent.map((frame) => frame[4]), [1, 1, 2]);
  provider.stop();
});

test("a failed outbound send is reported without permanently poisoning later updates", async () => {
  const { SecureYjsProvider } = await import("./secure-yjs-provider.js");
  const doc = new Y.Doc();
  const errors = [];
  let attempts = 0;
  const transport = new FakeTransport();
  transport.onError = (error) => errors.push(error);
  transport.send = (frame) => {
    attempts += 1;
    if (attempts === 1) throw new Error("temporary transport failure");
    transport.sent.push(new Uint8Array(frame));
  };
  const session = {
    hasGroupKey: true,
    isLeader: false,
    memberId: "member",
    async encryptBroadcast(value) {
      return new Uint8Array(value);
    },
  };
  const provider = new SecureYjsProvider({
    doc,
    session,
    transport,
    leaderId: "leader",
    trustedFingerprints: new Map(),
  });
  provider.start();

  doc.getText("text").insert(0, "أ");
  await assert.rejects(provider.flush(), /temporary transport failure/u);
  assert.equal(errors.length, 1);

  doc.getText("text").insert(1, "ب");
  await provider.flush();
  assert.equal(transport.sent.length, 1);
  provider.stop();
});
