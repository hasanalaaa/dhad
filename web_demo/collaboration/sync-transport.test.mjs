import assert from "node:assert/strict";
import test from "node:test";

test("full-jitter exponential backoff is bounded and capped", async () => {
  const { reconnectDelay } = await import("./sync-transport.js");
  assert.equal(reconnectDelay(0, { baseMs: 250, capMs: 30_000, random: () => 0.5 }), 125);
  assert.equal(reconnectDelay(8, { baseMs: 250, capMs: 30_000, random: () => 0.5 }), 15_000);
  assert.equal(reconnectDelay(80, { baseMs: 250, capMs: 30_000, random: () => 0.999 }), 29_970);
});

test("reconnect URLs carry the last durable Redis stream cursor", async () => {
  const { EncryptedSyncTransport } = await import("./sync-transport.js");
  const opened = [];
  class FakeSocket {
    static OPEN = 1;
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      opened.push(this);
    }
    close() {}
  }
  const transport = new EncryptedSyncTransport({
    url: "wss://example.test/ws/sync/doc",
    webSocketFactory: (url) => new FakeSocket(url),
    schedule: () => 1,
    cancelSchedule: () => {},
  });

  transport.connect();
  assert.equal(opened[0].url, "wss://example.test/ws/sync/doc");
  transport.noteCursor("1712345678901-7");
  transport.connect();
  assert.equal(opened[1].url, "wss://example.test/ws/sync/doc?cursor=1712345678901-7");
  transport.close();
});

test("unexpected disconnect schedules a reconnect, explicit close does not", async () => {
  const { EncryptedSyncTransport } = await import("./sync-transport.js");
  const scheduled = [];
  const sockets = [];
  class FakeSocket {
    static OPEN = 1;
    constructor() {
      this.readyState = 0;
      sockets.push(this);
    }
    close() {}
  }
  const transport = new EncryptedSyncTransport({
    url: "wss://example.test/ws/sync/doc",
    webSocketFactory: () => new FakeSocket(),
    schedule: (callback, delay) => {
      scheduled.push({ callback, delay });
      return scheduled.length;
    },
    cancelSchedule: () => {},
    random: () => 0.5,
  });
  transport.connect();
  sockets[0].onclose({ code: 1006 });
  assert.equal(scheduled.length, 1);
  assert.equal(scheduled[0].delay, 125);
  transport.close();
  sockets[0].onclose({ code: 1006 });
  assert.equal(scheduled.length, 1);
});

test("open callback lets the secure provider announce every reconnect epoch", async () => {
  const { EncryptedSyncTransport } = await import("./sync-transport.js");
  let opened = 0;
  class FakeSocket {
    constructor() {
      this.readyState = 0;
    }
    close() {}
  }
  const transport = new EncryptedSyncTransport({
    url: "wss://example.test/ws/sync/doc",
    webSocketFactory: () => new FakeSocket(),
    onOpen: () => {
      opened += 1;
    },
  });
  const socket = transport.connect();
  socket.onopen();
  assert.equal(opened, 1);
  transport.close();
});

test("async frame failures are reported without becoming unhandled rejections", async () => {
  const { EncryptedSyncTransport } = await import("./sync-transport.js");
  const errors = [];
  class FakeSocket {
    static OPEN = 1;
    constructor() {
      this.readyState = 1;
      this.bufferedAmount = 0;
    }
    close() {}
    send() {}
  }
  const transport = new EncryptedSyncTransport({
    url: "wss://example.test/ws/sync/doc",
    webSocketFactory: () => new FakeSocket(),
    onFrame: async () => { throw new Error("consumer failed"); },
    onError: (error) => errors.push(error),
  });
  const socket = transport.connect();
  const cursor = new TextEncoder().encode("1-0");
  const sender = new TextEncoder().encode("peer");
  const frame = new Uint8Array(9 + cursor.length + sender.length + 1);
  frame.set([0x44, 0x48, 0x53, 0x34, 1, 0, cursor.length, 0, sender.length]);
  frame.set(cursor, 9);
  frame.set(sender, 9 + cursor.length);
  frame.at(-1);
  await socket.onmessage({ data: frame.buffer });
  assert.equal(errors.length, 1);
  assert.match(String(errors[0]), /consumer failed/);
  transport.close();
});

test("inbound and outbound byte budgets enforce memory backpressure", async () => {
  const { EncryptedSyncTransport } = await import("./sync-transport.js");
  const errors = [];
  class FakeSocket {
    static OPEN = 1;
    constructor() {
      this.readyState = 1;
      this.bufferedAmount = 11;
    }
    close() {}
    send() { throw new Error("must not send"); }
  }
  const transport = new EncryptedSyncTransport({
    url: "wss://example.test/ws/sync/doc",
    webSocketFactory: () => new FakeSocket(),
    maxInboundBytes: 9,
    maxOutboundBytes: 4,
    maxBufferedBytes: 10,
    onError: (error) => errors.push(error),
  });
  const socket = transport.connect();
  await socket.onmessage({ data: new Uint8Array(10).buffer });
  assert.match(String(errors[0]), /inbound byte budget/);
  assert.throws(() => transport.send(new Uint8Array(5)), /outbound byte budget/);
  assert.throws(() => transport.send(new Uint8Array([1])), /backpressure budget/);
  transport.close();
  assert.throws(() => transport.send(new Uint8Array([1])), /not open/);
});

test("durable cursor advances only after the consumer commits a frame", async () => {
  const { EncryptedSyncTransport } = await import("./sync-transport.js");
  const errors = [];
  class FakeSocket { close() {} }
  const transport = new EncryptedSyncTransport({
    url: "wss://example.test/ws/sync/doc",
    webSocketFactory: () => new FakeSocket(),
    onFrame: async () => { throw new Error("storage commit failed"); },
    onError: (error) => errors.push(error),
  });
  const socket = transport.connect();
  const cursor = new TextEncoder().encode("8-0");
  const sender = new TextEncoder().encode("peer");
  const frame = new Uint8Array(9 + cursor.length + sender.length);
  frame.set([0x44, 0x48, 0x53, 0x34, 1, 0, cursor.length, 0, sender.length]);
  frame.set(cursor, 9);
  frame.set(sender, 9 + cursor.length);
  await socket.onmessage({ data: frame.buffer });
  assert.equal(transport.cursor, null);
  assert.match(String(errors[0]), /storage commit failed/);
  transport.close();
});

test("inbound frames are consumed strictly in wire order", async () => {
  const { EncryptedSyncTransport } = await import("./sync-transport.js");
  const observed = [];
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  class FakeSocket { close() {} }
  const makeFrame = (cursorText) => {
    const cursor = new TextEncoder().encode(cursorText);
    const sender = new TextEncoder().encode("peer");
    const frame = new Uint8Array(9 + cursor.length + sender.length);
    frame.set([0x44, 0x48, 0x53, 0x34, 1, 0, cursor.length, 0, sender.length]);
    frame.set(cursor, 9);
    frame.set(sender, 9 + cursor.length);
    return frame.buffer;
  };
  const transport = new EncryptedSyncTransport({
    url: "wss://example.test/ws/sync/doc",
    webSocketFactory: () => new FakeSocket(),
    onFrame: async () => {
      observed.push(observed.length + 1);
      if (observed.length === 1) await gate;
    },
  });
  const socket = transport.connect();
  const first = socket.onmessage({ data: makeFrame("1-0") });
  const second = socket.onmessage({ data: makeFrame("2-0") });
  await Promise.resolve();
  assert.deepEqual(observed, [1]);
  release();
  await Promise.all([first, second]);
  assert.deepEqual(observed, [1, 2]);
  assert.equal(transport.cursor, "2-0");
  transport.close();
});

test("authentication and protocol close codes do not reconnect forever", async () => {
  const { EncryptedSyncTransport, shouldReconnect } = await import("./sync-transport.js");
  const scheduled = [];
  class FakeSocket { close() {} }
  const transport = new EncryptedSyncTransport({
    url: "wss://example.test/ws/sync/doc",
    webSocketFactory: () => new FakeSocket(),
    schedule: (callback) => { scheduled.push(callback); return scheduled.length; },
  });
  const socket = transport.connect();
  socket.onclose({ code: 4006 });
  assert.equal(scheduled.length, 0);
  assert.equal(shouldReconnect(4006), false);
  assert.equal(shouldReconnect(1006), true);
});
