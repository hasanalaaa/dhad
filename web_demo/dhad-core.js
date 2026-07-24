/**
 * Hand-rolled dhad-core WASM bridge (zero dependencies, no wasm-bindgen).
 *
 * The diagnostic hot path uses persistent generation-safe document handles.
 * Input is encoded directly into a reusable WASM allocation with encodeInto;
 * output is a versioned binary table viewed in-place through TypedArrays.
 * Legacy structured APIs remain available for morphology/tokenization/parsing.
 */

const MODES = { strict: 0, lookup: 1, search: 2, aggressive: 3 };
const PACKED_MAGIC = 0x44414844;
const PACKED_VERSION = 1;
const PACKED_HEADER_SIZE = 56;
const PACKED_RECORD_SIZE = 80;
const PACKED_LIST_ENTRY_SIZE = 8;
const SEVERITIES = ["hint", "warning", "error"];

/** Convert a Python/Rust Unicode-scalar offset to a JavaScript UTF-16 offset. */
export function scalarToUtf16(text, scalarOffset) {
  if (!Number.isInteger(scalarOffset) || scalarOffset < 0) {
    throw new RangeError("scalarOffset must be a non-negative integer");
  }
  let scalars = 0;
  let units = 0;
  for (const value of text) {
    if (scalars === scalarOffset) return units;
    scalars += 1;
    units += value.length;
  }
  if (scalars === scalarOffset) return units;
  throw new RangeError("scalarOffset is outside the string");
}

/** Convert a JavaScript UTF-16 offset to the engine's Unicode-scalar offset. */
export function utf16ToScalar(text, utf16Offset) {
  if (!Number.isInteger(utf16Offset) || utf16Offset < 0 || utf16Offset > text.length) {
    throw new RangeError("utf16Offset is outside the string");
  }
  let scalars = 0;
  let units = 0;
  for (const value of text) {
    if (units === utf16Offset) return scalars;
    units += value.length;
    scalars += 1;
    if (units > utf16Offset) throw new RangeError("utf16Offset splits a surrogate pair");
  }
  return scalars;
}

class PackedDiagnosticsView {
  constructor(document, exports, decoder, ptr, length, viewGeneration, revision) {
    this._document = document;
    this._exports = exports;
    this._decoder = decoder;
    this._ptr = ptr >>> 0;
    this._length = length >>> 0;
    this._viewGeneration = viewGeneration;
    this.revision = revision;
    this._buffer = null;
    this._data = null;
    this._strings = new Map();
    this._refresh();
    this._validate();
    if (this._data.getUint32(52, true) !== this.revision) {
      throw new Error("packed diagnostics revision mismatch");
    }
  }

  _assertCurrent() {
    this._document._assertView(this._viewGeneration, this.revision);
  }

  _refresh() {
    this._assertCurrent();
    const buffer = this._exports.memory.buffer;
    if (buffer !== this._buffer) {
      if (this._ptr + this._length > buffer.byteLength) {
        throw new RangeError("packed diagnostics exceed WASM memory");
      }
      this._buffer = buffer;
      this._data = new DataView(buffer, this._ptr, this._length);
    }
  }

  _validate() {
    if (this._length < PACKED_HEADER_SIZE) {
      throw new RangeError("truncated packed diagnostics header");
    }
    const data = this._data;
    if (data.getUint32(0, true) !== PACKED_MAGIC) {
      throw new Error("invalid packed diagnostics magic");
    }
    if (data.getUint16(4, true) !== PACKED_VERSION) {
      throw new Error(`unsupported packed diagnostics version: ${data.getUint16(4, true)}`);
    }
    const headerSize = data.getUint16(6, true);
    const recordSize = data.getUint16(8, true);
    const listEntrySize = data.getUint16(10, true);
    const recordCount = data.getUint32(24, true);
    const listCount = data.getUint32(28, true);
    const recordsOffset = data.getUint32(32, true);
    const listsOffset = data.getUint32(36, true);
    const stringsOffset = data.getUint32(40, true);
    const stringsLength = data.getUint32(44, true);
    const totalLength = data.getUint32(48, true);
    if (
      headerSize !== PACKED_HEADER_SIZE ||
      recordSize !== PACKED_RECORD_SIZE ||
      listEntrySize !== PACKED_LIST_ENTRY_SIZE ||
      recordsOffset !== headerSize ||
      recordsOffset + recordCount * recordSize !== listsOffset ||
      listsOffset + listCount * listEntrySize !== stringsOffset ||
      stringsOffset + stringsLength !== totalLength ||
      totalLength !== this._length
    ) {
      throw new RangeError("invalid packed diagnostics layout");
    }
  }

  get rawCount() {
    this._refresh();
    return this._data.getUint32(16, true);
  }

  get resolvedCount() {
    this._refresh();
    return this._data.getUint32(20, true);
  }

  /** Direct, non-owning view of all fixed-width records in WASM memory. */
  get recordsBytes() {
    this._refresh();
    const offset = this._data.getUint32(32, true);
    const length = this._data.getUint32(24, true) * PACKED_RECORD_SIZE;
    return new Uint8Array(this._buffer, this._ptr + offset, length);
  }

  /** Direct, non-owning view of the interned UTF-8 string table. */
  get stringsBytes() {
    this._refresh();
    const offset = this._data.getUint32(40, true);
    const length = this._data.getUint32(44, true);
    return new Uint8Array(this._buffer, this._ptr + offset, length);
  }

  _string(offset, length) {
    const key = `${offset}:${length}`;
    let value = this._strings.get(key);
    if (value !== undefined) return value;
    const stringsOffset = this._data.getUint32(40, true);
    const stringsLength = this._data.getUint32(44, true);
    if (offset + length > stringsLength) {
      throw new RangeError("packed string reference is out of bounds");
    }
    const bytes = new Uint8Array(this._buffer, this._ptr + stringsOffset + offset, length);
    value = this._decoder.decode(bytes);
    this._strings.set(key, value);
    return value;
  }

  _recordString(base, field) {
    return this._string(
      this._data.getUint32(base + field, true),
      this._data.getUint32(base + field + 4, true),
    );
  }

  _list(base, startField, countField) {
    const start = this._data.getUint32(base + startField, true);
    const count = this._data.getUint16(base + countField, true);
    const listCount = this._data.getUint32(28, true);
    const listsOffset = this._data.getUint32(36, true);
    if (start + count > listCount) {
      throw new RangeError("packed string-list reference is out of bounds");
    }
    const values = new Array(count);
    for (let index = 0; index < count; index += 1) {
      const entry = listsOffset + (start + index) * PACKED_LIST_ENTRY_SIZE;
      values[index] = this._string(
        this._data.getUint32(entry, true),
        this._data.getUint32(entry + 4, true),
      );
    }
    return values;
  }

  _record(index) {
    const recordCount = this._data.getUint32(24, true);
    if (!Number.isInteger(index) || index < 0 || index >= recordCount) {
      throw new RangeError("packed record index is out of bounds");
    }
    const base = this._data.getUint32(32, true) + index * PACKED_RECORD_SIZE;
    const severity = SEVERITIES[this._data.getUint8(base + 76)];
    if (severity === undefined) throw new Error("invalid packed severity");
    return {
      rule_id: this._recordString(base, 0),
      category: this._recordString(base, 8),
      message: this._recordString(base, 16),
      offset: this._data.getUint32(base + 32, true),
      length: this._data.getUint32(base + 36, true),
      replacements: this._list(base, 52, 68),
      severity,
      explanation: this._recordString(base, 24),
      autofix: this._data.getUint8(base + 77) !== 0,
      confidence: this._data.getFloat64(base + 40, true),
      priority: this._data.getInt32(base + 48, true),
      tags: this._list(base, 56, 70),
      references: this._list(base, 60, 72),
      profiles: this._list(base, 64, 74),
    };
  }

  toObject() {
    this._refresh();
    const rawCount = this._data.getUint32(16, true);
    const resolvedCount = this._data.getUint32(20, true);
    const matches = new Array(rawCount);
    const resolved = new Array(resolvedCount);
    for (let index = 0; index < rawCount; index += 1) matches[index] = this._record(index);
    for (let index = 0; index < resolvedCount; index += 1) {
      resolved[index] = this._record(rawCount + index);
    }
    return { matches, resolved };
  }
}

export async function loadEngine(wasmSource, rulesJson) {
  const { instance } =
    wasmSource instanceof WebAssembly.Module
      ? { instance: await WebAssembly.instantiate(wasmSource, {}) }
      : await WebAssembly.instantiate(wasmSource, {});
  const exports = instance.exports;
  const encoder = new TextEncoder();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let inputPtr = 0;
  let inputCapacity = 0;
  let disposed = false;
  let scratchDocument = null;
  const documents = new Map();

  function assertLiveEngine() {
    if (disposed) throw new Error("disposed engine");
  }

  function growInput(required) {
    if (required <= inputCapacity) return;
    let capacity = Math.max(64, inputCapacity || 64);
    while (capacity < required) capacity *= 2;
    const next = Number(exports.dc_alloc(capacity)) >>> 0;
    if (next === 0) throw new Error("WASM input allocation failed");
    if (inputPtr !== 0) exports.dc_free(inputPtr, inputCapacity);
    inputPtr = next;
    inputCapacity = capacity;
  }

  function withInput(text, call) {
    assertLiveEngine();
    if (typeof text !== "string") throw new TypeError("WASM input must be a string");
    growInput(Math.max(1, text.length * 3));
    const destination = new Uint8Array(exports.memory.buffer, inputPtr, inputCapacity);
    const { read, written } = encoder.encodeInto(text, destination);
    if (read !== text.length) throw new Error("WASM UTF-8 input arena was undersized");
    return call(inputPtr, written);
  }

  // Compatibility decoder for the non-diagnostic APIs. The check path never
  // invokes this function and never allocates/copies a JSON response.
  function unpackLegacy(packed) {
    const ptr = Number(packed >> 32n) >>> 0;
    const len = Number(packed & 0xffffffffn);
    const bytes = new Uint8Array(exports.memory.buffer, ptr, len).slice();
    exports.dc_free(ptr, len || 1);
    return JSON.parse(decoder.decode(bytes));
  }

  class DhadDocument {
    constructor(text) {
      this._handle = withInput(text, (ptr, len) => Number(exports.dc_doc_create(ptr, len)) >>> 0);
      if (this._handle === 0) throw new Error("WASM document creation failed");
      this._disposed = false;
      this._viewGeneration = 0;
      documents.set(this._handle, new WeakRef(this));
      finalizer.register(this, this._handle, this);
    }

    _assertLive() {
      assertLiveEngine();
      if (this._disposed) throw new Error("disposed document");
    }

    _assertView(generation, revision) {
      this._assertLive();
      if (
        generation !== this._viewGeneration ||
        Number(exports.dc_doc_revision(this._handle)) !== revision
      ) {
        throw new Error("stale packed diagnostics view");
      }
    }

    update(text) {
      this._assertLive();
      const status = withInput(text, (ptr, len) =>
        Number(exports.dc_doc_update(this._handle, ptr, len)),
      );
      if (status !== 0) throw new Error(`WASM document update failed (${status})`);
      this._viewGeneration += 1;
      return this;
    }

    analyzeView() {
      this._assertLive();
      const status = Number(exports.dc_doc_analyze(this._handle));
      if (status !== 0) throw new Error(`WASM document analysis failed (${status})`);
      this._viewGeneration += 1;
      const ptr = Number(exports.dc_doc_result_ptr(this._handle)) >>> 0;
      const length = Number(exports.dc_doc_result_len(this._handle));
      if (ptr === 0 || length === 0) throw new Error("WASM returned an empty diagnostics view");
      return new PackedDiagnosticsView(
        this,
        exports,
        decoder,
        ptr,
        length,
        this._viewGeneration,
        Number(exports.dc_doc_revision(this._handle)),
      );
    }

    check() {
      return this.analyzeView().toObject();
    }

    dispose() {
      if (this._disposed) return;
      this._viewGeneration += 1;
      exports.dc_doc_destroy(this._handle);
      finalizer.unregister(this);
      documents.delete(this._handle);
      this._disposed = true;
      this._handle = 0;
    }
  }

  const finalizer = new FinalizationRegistry((handle) => {
    documents.delete(handle);
    if (!disposed) exports.dc_doc_destroy(handle);
  });

  const loaded = withInput(rulesJson, (ptr, len) => exports.dc_load_rules(ptr, len));
  if (loaded < 0n) throw new Error("dhad-core rejected the rule pack");
  const lexemeCount = typeof exports.dc_warmup === "function" ? Number(exports.dc_warmup()) : 0;

  const engine = {
    ruleCount: Number(loaded),
    lexemeCount,
    createDocument(text) {
      assertLiveEngine();
      return new DhadDocument(text);
    },
    liveDocumentCount() {
      return Number(exports.dc_live_documents());
    },
    /** Full deterministic check with the original {matches, resolved} shape. */
    check(text) {
      assertLiveEngine();
      if (scratchDocument === null) scratchDocument = new DhadDocument(text);
      else scratchDocument.update(text);
      return scratchDocument.check();
    },
    tokenize(text) {
      return withInput(text, (ptr, len) => unpackLegacy(exports.dc_tokenize(ptr, len))).tokens;
    },
    sentences(text) {
      return withInput(text, (ptr, len) => unpackLegacy(exports.dc_sentences(ptr, len))).sentences;
    },
    normalize(text, mode = "lookup") {
      const code = MODES[mode];
      if (code === undefined) throw new Error(`unknown mode: ${mode}`);
      return withInput(text, (ptr, len) => unpackLegacy(exports.dc_normalize(code, ptr, len)))
        .normalized;
    },
    analyze(token, minConfidence = 0) {
      if (!Number.isFinite(minConfidence) || minConfidence < 0 || minConfidence > 1) {
        throw new RangeError("minConfidence must be between 0 and 1");
      }
      const result = withInput(token, (ptr, len) =>
        unpackLegacy(exports.dc_analyze(ptr, len, minConfidence)),
      );
      if (result.error) throw new Error(result.error);
      return result.analyses;
    },
    parse(text) {
      return withInput(text, (ptr, len) => unpackLegacy(exports.dc_parse(ptr, len)));
    },
    syntaxCheck(text) {
      return withInput(text, (ptr, len) => unpackLegacy(exports.dc_syntax_check(ptr, len))).matches;
    },
    dispose() {
      if (disposed) return;
      for (const [handle, reference] of [...documents]) {
        const document = reference.deref();
        if (document === undefined) {
          exports.dc_doc_destroy(handle);
          documents.delete(handle);
        } else {
          document.dispose();
        }
      }
      scratchDocument = null;
      if (inputPtr !== 0) exports.dc_free(inputPtr, inputCapacity);
      inputPtr = 0;
      inputCapacity = 0;
      disposed = true;
    },
  };
  return engine;
}
