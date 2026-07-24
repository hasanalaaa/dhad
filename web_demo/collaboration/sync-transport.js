const CURSOR_RE = /^\d+-\d+$/u;
const SERVER_MAGIC = [0x44, 0x48, 0x53, 0x34]; // DHS4
const SERVER_HEADER_BYTES = 9;
const NON_RETRIABLE_CLOSE_CODES = new Set([1000, 4000, 4002, 4003, 4004, 4006, 4007, 4008]);

export function shouldReconnect(code) {
  return !NON_RETRIABLE_CLOSE_CODES.has(code);
}

export function reconnectDelay(
  attempt,
  { baseMs = 250, capMs = 30_000, random = Math.random } = {},
) {
  if (!Number.isInteger(attempt) || attempt < 0) throw new TypeError("attempt must be non-negative");
  if (!(baseMs > 0) || !(capMs >= baseMs)) throw new TypeError("Invalid reconnect bounds");
  const ceiling = Math.min(capMs, baseMs * 2 ** Math.min(attempt, 30));
  return Math.floor(random() * ceiling);
}

function cursorFromServerFrame(value) {
  const data = value instanceof Uint8Array ? value : new Uint8Array(value);
  if (data.length < SERVER_HEADER_BYTES) throw new Error("Invalid Dhad server frame");
  for (let index = 0; index < SERVER_MAGIC.length; index += 1) {
    if (data[index] !== SERVER_MAGIC[index]) throw new Error("Invalid Dhad server frame");
  }
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const cursorLength = view.getUint16(5, false);
  const senderLength = view.getUint16(7, false);
  if (SERVER_HEADER_BYTES + cursorLength + senderLength > data.length) {
    throw new Error("Invalid Dhad server frame");
  }
  return new TextDecoder("ascii", { fatal: true }).decode(
    data.subarray(SERVER_HEADER_BYTES, SERVER_HEADER_BYTES + cursorLength),
  );
}

export class EncryptedSyncTransport {
  constructor({
    url,
    webSocketFactory = (target) => new WebSocket(target),
    schedule = setTimeout,
    cancelSchedule = clearTimeout,
    random = Math.random,
    onFrame = () => {},
    onControl = () => {},
    onOpen = () => {},
    onError = () => {},
    maxInboundBytes = 512 * 1024,
    maxOutboundBytes = 512 * 1024,
    maxBufferedBytes = 4 * 1024 * 1024,
    maxQueuedInboundBytes = 4 * 1024 * 1024,
  }) {
    const parsed = new URL(url);
    if (!new Set(["ws:", "wss:"]).has(parsed.protocol)) {
      throw new TypeError("Sync transport requires a ws:// or wss:// URL");
    }
    this.url = parsed;
    this.webSocketFactory = webSocketFactory;
    this.schedule = schedule;
    this.cancelSchedule = cancelSchedule;
    this.random = random;
    this.onFrame = onFrame;
    this.onControl = onControl;
    for (const [name, callback] of Object.entries({ onFrame, onControl, onOpen, onError })) {
      if (typeof callback !== "function") throw new TypeError(`${name} must be a function`);
    }
    if (!Number.isSafeInteger(maxInboundBytes) || maxInboundBytes < SERVER_HEADER_BYTES) {
      throw new RangeError("maxInboundBytes is invalid");
    }
    if (!Number.isSafeInteger(maxOutboundBytes) || maxOutboundBytes < 1) {
      throw new RangeError("maxOutboundBytes is invalid");
    }
    if (!Number.isSafeInteger(maxBufferedBytes) || maxBufferedBytes < maxOutboundBytes) {
      throw new RangeError("maxBufferedBytes must be at least maxOutboundBytes");
    }
    if (!Number.isSafeInteger(maxQueuedInboundBytes) || maxQueuedInboundBytes < maxInboundBytes) {
      throw new RangeError("maxQueuedInboundBytes must be at least maxInboundBytes");
    }
    this.onOpen = onOpen;
    this.onError = onError;
    this.maxInboundBytes = maxInboundBytes;
    this.maxOutboundBytes = maxOutboundBytes;
    this.maxBufferedBytes = maxBufferedBytes;
    this.maxQueuedInboundBytes = maxQueuedInboundBytes;
    this.queuedInboundBytes = 0;
    this.inbound = Promise.resolve();
    this.socket = null;
    this.cursor = null;
    this.attempt = 0;
    this.timer = null;
    this.explicitlyClosed = false;
  }

  #reportError(error) {
    try {
      this.onError(error);
    } catch {
      // Error reporters must never destabilize the transport state machine.
    }
  }

  #eventByteLength(data) {
    if (typeof data === "string") return new TextEncoder().encode(data).byteLength;
    if (data instanceof Blob) return data.size;
    if (data instanceof ArrayBuffer) return data.byteLength;
    if (ArrayBuffer.isView(data)) return data.byteLength;
    throw new TypeError("Unsupported WebSocket frame type");
  }

  async #processInbound(socket, event) {
    if (socket !== this.socket) return;
    if (typeof event.data === "string") {
      await this.onControl(JSON.parse(event.data));
      return;
    }
    const data = event.data instanceof Blob ? await event.data.arrayBuffer() : event.data;
    const frame = data instanceof Uint8Array
      ? data
      : new Uint8Array(data.buffer ?? data, data.byteOffset ?? 0, data.byteLength);
    const cursor = cursorFromServerFrame(frame);
    await this.onFrame(frame);
    this.noteCursor(cursor);
  }

  #enqueueInbound(socket, event) {
    let size;
    try {
      size = this.#eventByteLength(event.data);
    } catch (error) {
      this.#reportError(error);
      return Promise.resolve();
    }
    if (size > this.maxInboundBytes) {
      const error = new Error("Sync frame exceeds the inbound byte budget");
      this.#reportError(error);
      if (socket === this.socket) socket.close(1009, "inbound frame too large");
      return Promise.resolve();
    }
    if (this.queuedInboundBytes + size > this.maxQueuedInboundBytes) {
      const error = new Error("Sync inbound queue backpressure budget exceeded");
      this.#reportError(error);
      if (socket === this.socket) socket.close(1009, "inbound queue overflow");
      return Promise.resolve();
    }

    this.queuedInboundBytes += size;
    const operation = () => this.#processInbound(socket, event);
    const pending = this.inbound.then(operation, operation);
    this.inbound = pending
      .catch((error) => this.#reportError(error))
      .finally(() => {
        this.queuedInboundBytes = Math.max(0, this.queuedInboundBytes - size);
      });
    return this.inbound;
  }

  #scheduleReconnect() {
    if (this.explicitlyClosed || this.timer !== null) return;
    const delay = reconnectDelay(this.attempt, { random: this.random });
    this.attempt += 1;
    this.timer = this.schedule(() => {
      this.timer = null;
      try {
        this.connect();
      } catch (error) {
        this.#reportError(error);
        this.#scheduleReconnect();
      }
    }, delay);
  }

  noteCursor(cursor) {
    if (typeof cursor !== "string" || !CURSOR_RE.test(cursor)) {
      throw new TypeError("Invalid Redis stream cursor");
    }
    this.cursor = cursor;
  }

  #connectionUrl() {
    const target = new URL(this.url);
    if (this.cursor) target.searchParams.set("cursor", this.cursor);
    return target.toString();
  }

  connect() {
    this.explicitlyClosed = false;
    if (this.timer !== null) {
      this.cancelSchedule(this.timer);
      this.timer = null;
    }
    if (this.socket) {
      const previous = this.socket;
      this.socket = null;
      previous.onopen = null;
      previous.onmessage = null;
      previous.onerror = null;
      previous.onclose = null;
      previous.close();
    }
    let socket;
    try {
      socket = this.webSocketFactory(this.#connectionUrl());
    } catch (error) {
      this.#scheduleReconnect();
      throw error;
    }
    this.socket = socket;
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      if (socket !== this.socket) return;
      this.attempt = 0;
      Promise.resolve(this.onOpen()).catch((error) => this.#reportError(error));
    };
    socket.onmessage = (event) => this.#enqueueInbound(socket, event);
    socket.onclose = (event) => {
      if (socket !== this.socket) return;
      this.socket = null;
      if (shouldReconnect(event?.code)) this.#scheduleReconnect();
    };
    socket.onerror = (event) => {
      if (socket === this.socket) this.#reportError(event);
    };
    return socket;
  }

  send(frame) {
    if (!this.socket || this.socket.readyState !== 1) throw new Error("Sync socket is not open");
    const data = frame instanceof Uint8Array ? frame : new Uint8Array(frame);
    if (data.byteLength > this.maxOutboundBytes) {
      throw new Error("Sync frame exceeds the outbound byte budget");
    }
    const projectedBufferedBytes = (this.socket.bufferedAmount ?? 0) + data.byteLength;
    if (projectedBufferedBytes > this.maxBufferedBytes) {
      throw new Error("Sync socket backpressure budget exceeded");
    }
    this.socket.send(data);
  }

  close(code = 1000, reason = "client shutdown") {
    this.explicitlyClosed = true;
    if (this.timer !== null) {
      this.cancelSchedule(this.timer);
      this.timer = null;
    }
    const socket = this.socket;
    this.socket = null;
    socket?.close(code, reason);
  }
}
