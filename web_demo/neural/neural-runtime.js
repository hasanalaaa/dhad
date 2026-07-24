import {
  WordPieceTokenizer,
  candidateDescription,
  meanPool,
  rankCandidateEmbeddings,
  validateRankRequest,
} from "./neural-core.js";

const SHA256_PATTERN = /^[a-f0-9]{64}$/u;
const CONTRACT = "dhad-context-embedding-ranker-v1";

function requireObject(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function requireName(value, name) {
  if (typeof value !== "string" || !/^[A-Za-z_][A-Za-z0-9_.-]*$/u.test(value)) {
    throw new TypeError(`${name} must be a valid tensor name`);
  }
  return value;
}

function requireSha256(value, name) {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value)) {
    throw new TypeError(`${name} must be a lowercase SHA-256 digest`);
  }
  return value;
}

function resolveAssetUrl(value, baseUrl, name) {
  if (typeof value !== "string" || value.length === 0) throw new TypeError(`${name} is required`);
  const url = new URL(value, baseUrl);
  if (!new Set(["http:", "https:"]).has(url.protocol)) {
    throw new TypeError(`${name} must use HTTP(S)`);
  }
  return url;
}

export function validateModelManifest(payload, baseUrl = new URL("http://localhost/")) {
  const source = requireObject(payload, "model manifest");
  if (source.format !== 1) throw new Error("unsupported model manifest format");
  if (source.contract !== CONTRACT) throw new Error(`unsupported model contract: ${source.contract}`);
  if (typeof source.id !== "string" || source.id.length === 0 || source.id.length > 128) {
    throw new TypeError("model manifest id is invalid");
  }
  const model = requireObject(source.model, "model");
  const quantization = String(model.quantization ?? "").toLowerCase();
  if (!new Set(["int8", "uint8"]).has(quantization)) {
    throw new Error("student model must use INT8 or UINT8 quantization");
  }
  const tokenizer = requireObject(source.tokenizer, "tokenizer");
  if (tokenizer.type !== "wordpiece") throw new Error("only wordpiece tokenizers are supported");
  const inputs = requireObject(source.inputs, "inputs");
  const output = requireObject(source.output, "output");
  const thresholds = requireObject(source.thresholds, "thresholds");
  const confidence = Number(thresholds.confidence);
  const margin = Number(thresholds.margin);
  const temperature = Number(thresholds.temperature);
  if (!Number.isFinite(confidence) || confidence < 0.999 || confidence > 1) {
    throw new RangeError("confidence threshold must be at least 0.999");
  }
  if (!Number.isFinite(margin) || margin < 0 || margin > 1) {
    throw new RangeError("margin threshold must be between 0 and 1");
  }
  if (!Number.isFinite(temperature) || temperature <= 0 || temperature > 10) {
    throw new RangeError("temperature must be positive and at most 10");
  }
  const maxLength = Number(source.maxLength);
  if (!Number.isInteger(maxLength) || maxLength < 16 || maxLength > 512) {
    throw new RangeError("maxLength must be between 16 and 512");
  }
  const expectedBytes = model.expectedBytes === undefined ? null : Number(model.expectedBytes);
  if (
    expectedBytes !== null &&
    (!Number.isSafeInteger(expectedBytes) || expectedBytes <= 0 || expectedBytes > 4_294_967_295)
  ) {
    throw new RangeError("model.expectedBytes must be a positive 32-bit byte count");
  }
  return Object.freeze({
    format: 1,
    id: source.id,
    contract: CONTRACT,
    model: Object.freeze({
      url: resolveAssetUrl(model.url, baseUrl, "model.url"),
      sha256: requireSha256(model.sha256, "model.sha256"),
      quantization,
      expectedBytes,
    }),
    tokenizer: Object.freeze({
      type: "wordpiece",
      url: resolveAssetUrl(tokenizer.url, baseUrl, "tokenizer.url"),
      sha256: requireSha256(tokenizer.sha256, "tokenizer.sha256"),
      lowercase: Boolean(tokenizer.lowercase),
    }),
    inputs: Object.freeze({
      inputIds: requireName(inputs.inputIds, "inputs.inputIds"),
      attentionMask: requireName(inputs.attentionMask, "inputs.attentionMask"),
      ...(inputs.tokenTypeIds === undefined
        ? {}
        : { tokenTypeIds: requireName(inputs.tokenTypeIds, "inputs.tokenTypeIds") }),
    }),
    output: Object.freeze({ name: requireName(output.name, "output.name") }),
    maxLength,
    thresholds: Object.freeze({ confidence, margin, temperature }),
  });
}

export async function createSessionWithFallback(
  ort,
  modelBytes,
  { webgpuAvailable = typeof navigator !== "undefined" && "gpu" in navigator } = {},
) {
  const common = {
    graphOptimizationLevel: "all",
    executionMode: "sequential",
    enableCpuMemArena: true,
    enableMemPattern: true,
    logSeverityLevel: 3,
  };
  let webgpuError = null;
  if (webgpuAvailable) {
    try {
      const session = await ort.InferenceSession.create(modelBytes, {
        ...common,
        executionProviders: ["webgpu", "wasm"],
        preferredOutputLocation: "cpu",
      });
      return Object.freeze({ session, provider: "webgpu-preferred", webgpuError: null });
    } catch (error) {
      webgpuError = error instanceof Error ? error.message : String(error);
    }
  }
  const session = await ort.InferenceSession.create(modelBytes, {
    ...common,
    executionProviders: ["wasm"],
  });
  return Object.freeze({ session, provider: "wasm-simd", webgpuError });
}

export function buildCandidateBatch(tokenizer, unsafeRequest) {
  const request = validateRankRequest(unsafeRequest);
  const encoded = [tokenizer.encodePair(request.sentence)];
  for (const candidate of request.candidates) {
    encoded.push(tokenizer.encodePair(request.sentence, candidateDescription(candidate)));
  }
  const rows = encoded.length;
  const sequenceLength = tokenizer.maxLength;
  const inputIds = new BigInt64Array(rows * sequenceLength);
  const attentionMask = new BigInt64Array(rows * sequenceLength);
  const tokenTypeIds = new BigInt64Array(rows * sequenceLength);
  for (let row = 0; row < rows; row += 1) {
    const offset = row * sequenceLength;
    for (let column = 0; column < sequenceLength; column += 1) {
      inputIds[offset + column] = BigInt(encoded[row].inputIds[column]);
      attentionMask[offset + column] = BigInt(encoded[row].attentionMask[column]);
      tokenTypeIds[offset + column] = BigInt(encoded[row].tokenTypeIds[column]);
    }
  }
  return Object.freeze({ rows, sequenceLength, inputIds, attentionMask, tokenTypeIds, request });
}

export function buildCandidateSuperBatch(tokenizer, unsafeRequests) {
  if (!Array.isArray(unsafeRequests) || unsafeRequests.length < 1 || unsafeRequests.length > 64) {
    throw new RangeError("rank batch must contain between 1 and 64 requests");
  }
  const requests = unsafeRequests.map((request) => validateRankRequest(request));
  if (new Set(requests.map((request) => request.requestId)).size !== requests.length) {
    throw new RangeError("rank batch contains duplicate request ids");
  }
  const sequenceLength = tokenizer.maxLength;
  const rows = requests.reduce((total, request) => total + request.candidates.length + 1, 0);
  const inputIds = new BigInt64Array(rows * sequenceLength);
  const attentionMask = new BigInt64Array(rows * sequenceLength);
  const tokenTypeIds = new BigInt64Array(rows * sequenceLength);
  const items = [];
  let row = 0;

  const writeRow = (encoded) => {
    const offset = row * sequenceLength;
    for (let column = 0; column < sequenceLength; column += 1) {
      inputIds[offset + column] = BigInt(encoded.inputIds[column]);
      attentionMask[offset + column] = BigInt(encoded.attentionMask[column]);
      tokenTypeIds[offset + column] = BigInt(encoded.tokenTypeIds[column]);
    }
    row += 1;
  };

  for (const request of requests) {
    const rowStart = row;
    writeRow(tokenizer.encodePair(request.sentence));
    for (const candidate of request.candidates) {
      writeRow(tokenizer.encodePair(request.sentence, candidateDescription(candidate)));
    }
    items.push(Object.freeze({ request, rowStart, rowEnd: row }));
  }
  return Object.freeze({
    rows,
    sequenceLength,
    inputIds,
    attentionMask,
    tokenTypeIds,
    items: Object.freeze(items),
  });
}

export function createFeeds(ort, batch, inputs) {
  const dimensions = [batch.rows, batch.sequenceLength];
  const feeds = {
    [inputs.inputIds]: new ort.Tensor("int64", batch.inputIds, dimensions),
    [inputs.attentionMask]: new ort.Tensor("int64", batch.attentionMask, dimensions),
  };
  if (inputs.tokenTypeIds) {
    feeds[inputs.tokenTypeIds] = new ort.Tensor("int64", batch.tokenTypeIds, dimensions);
  }
  return feeds;
}

export async function sha256Hex(bytes) {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

export async function fetchVerifiedAsset(
  url,
  expectedSha256,
  expectedBytes = null,
  { signal } = {},
) {
  requireSha256(expectedSha256, "expectedSha256");
  const response = await fetch(url, {
    credentials: "omit",
    mode: "cors",
    cache: "force-cache",
    signal,
  });
  if (!response.ok) throw new Error(`asset fetch failed (${response.status}): ${url}`);
  const limit = expectedBytes ?? 16 * 1024 * 1024;
  const declaredHeader = response.headers?.get?.("content-length");
  const declaredLength = declaredHeader == null ? null : Number(declaredHeader);
  if (
    declaredLength !== null &&
    (!Number.isSafeInteger(declaredLength) ||
      declaredLength < 0 ||
      declaredLength > limit ||
      (expectedBytes !== null && declaredLength !== expectedBytes))
  ) {
    throw new Error(`asset length mismatch for ${url}`);
  }

  let bytes;
  if (typeof response.body?.getReader === "function") {
    const reader = response.body.getReader();
    const allocated = expectedBytes === null ? null : new Uint8Array(expectedBytes);
    const chunks = allocated === null ? [] : null;
    let total = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = value instanceof Uint8Array ? value : new Uint8Array(value);
        if (total + chunk.byteLength > limit) {
          throw new Error(`asset exceeds byte limit for ${url}`);
        }
        if (allocated !== null) allocated.set(chunk, total);
        else chunks.push(chunk);
        total += chunk.byteLength;
      }
    } catch (error) {
      await reader.cancel?.(error).catch?.(() => undefined);
      throw error;
    } finally {
      reader.releaseLock?.();
    }
    if (expectedBytes !== null && total !== expectedBytes) {
      throw new Error(`asset length mismatch for ${url}`);
    }
    if (allocated !== null) {
      bytes = allocated;
    } else {
      bytes = new Uint8Array(total);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
    }
  } else {
    bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.length > limit) throw new Error(`asset exceeds byte limit for ${url}`);
  }
  if (expectedBytes !== null && bytes.length !== expectedBytes) {
    throw new Error(`asset length mismatch for ${url}`);
  }
  const actual = await sha256Hex(bytes);
  if (actual !== expectedSha256) throw new Error(`asset SHA-256 mismatch for ${url}`);
  return bytes;
}

async function tensorData(tensor) {
  if (typeof tensor.getData === "function") return tensor.getData();
  return tensor.data;
}

export class NeuralInferenceRuntime {
  constructor(ort) {
    if (!ort?.InferenceSession || typeof ort.InferenceSession.create !== "function") {
      throw new TypeError("A compatible ONNX Runtime Web instance is required");
    }
    this.ort = ort;
    this.manifest = null;
    this.tokenizer = null;
    this.session = null;
    this.provider = "uninitialized";
    this.webgpuError = null;
    this.initializing = null;
    this.initializationController = null;
    this.generation = 0;
  }

  async #initialize(manifestUrl, generation, signal) {
    const url = new URL(manifestUrl, globalThis.location?.href ?? "http://localhost/");
    const response = await fetch(url, {
      credentials: "omit",
      cache: "no-cache",
      signal,
    });
    if (!response.ok) throw new Error(`model manifest fetch failed (${response.status})`);
    const manifest = validateModelManifest(await response.json(), url);
    const [modelBytes, vocabBytes] = await Promise.all([
      fetchVerifiedAsset(
        manifest.model.url,
        manifest.model.sha256,
        manifest.model.expectedBytes,
        { signal },
      ),
      fetchVerifiedAsset(manifest.tokenizer.url, manifest.tokenizer.sha256, null, { signal }),
    ]);
    const tokenizer = WordPieceTokenizer.fromVocabText(
      new TextDecoder("utf-8", { fatal: true }).decode(vocabBytes),
      { maxLength: manifest.maxLength, lowercase: manifest.tokenizer.lowercase },
    );
    const created = await createSessionWithFallback(this.ort, modelBytes);
    const session = created.session;
    try {
      const requiredInputs = Object.values(manifest.inputs);
      const missing = requiredInputs.filter((name) => !session.inputNames.includes(name));
      if (missing.length > 0) {
        throw new Error(`student model is missing declared inputs: ${missing.join(", ")}`);
      }
      if (!session.outputNames.includes(manifest.output.name)) {
        throw new Error(`student model is missing output: ${manifest.output.name}`);
      }
      if (generation !== this.generation) {
        throw new Error("neural runtime initialization was superseded");
      }
      this.manifest = manifest;
      this.tokenizer = tokenizer;
      this.session = session;
      this.provider = created.provider;
      this.webgpuError = created.webgpuError;
      return this.status();
    } catch (error) {
      await session.release?.();
      throw error;
    }
  }

  async initialize(manifestUrl) {
    if (this.session !== null) return this.status();
    if (this.initializing !== null) return this.initializing;
    const generation = this.generation;
    const controller = new AbortController();
    this.initializationController = controller;
    const initializing = this.#initialize(manifestUrl, generation, controller.signal);
    this.initializing = initializing;
    try {
      return await initializing;
    } finally {
      if (this.initializing === initializing) this.initializing = null;
      if (this.initializationController === controller) this.initializationController = null;
    }
  }

  status() {
    return Object.freeze({
      ready: this.session !== null,
      modelId: this.manifest?.id ?? null,
      provider: this.provider,
      webgpuError: this.webgpuError,
      threshold: this.manifest?.thresholds.confidence ?? 0.999,
    });
  }

  async rank(unsafeRequest) {
    return (await this.rankMany([unsafeRequest]))[0];
  }

  async rankMany(unsafeRequests) {
    if (this.session === null || this.manifest === null || this.tokenizer === null) {
      throw new Error("neural runtime is not initialized");
    }
    const batch = buildCandidateSuperBatch(this.tokenizer, unsafeRequests);
    const feeds = createFeeds(this.ort, batch, this.manifest.inputs);
    const started = performance.now();
    let output = null;
    try {
      const outputs = await this.session.run(feeds, [this.manifest.output.name]);
      output = outputs[this.manifest.output.name];
      if (output === undefined) throw new Error("student model returned no declared output");
      const hidden = await tensorData(output);
      const embeddings = meanPool(hidden, output.dims, batch.attentionMask);
      const elapsedMs = performance.now() - started;
      return Object.freeze(
        batch.items.map((item) => {
          const itemEmbeddings = embeddings.slice(item.rowStart, item.rowEnd);
          const decision = rankCandidateEmbeddings(item.request.candidates, itemEmbeddings, {
            confidenceThreshold: this.manifest.thresholds.confidence,
            marginThreshold: this.manifest.thresholds.margin,
            temperature: this.manifest.thresholds.temperature,
          });
          if (decision.abstained) {
            return Object.freeze({
              requestId: item.request.requestId,
              abstained: true,
              reason: decision.reason,
              confidence: decision.confidence,
              margin: decision.margin,
              provider: this.provider,
              elapsedMs,
            });
          }
          const selected = item.request.candidates[decision.selectedIndex];
          return Object.freeze({
            requestId: item.request.requestId,
            abstained: false,
            selectedIndex: decision.selectedIndex,
            selectedCandidateId: selected.id,
            confidence: decision.confidence,
            margin: decision.margin,
            provider: this.provider,
            elapsedMs,
          });
        }),
      );
    } finally {
      output?.dispose?.();
      for (const tensor of Object.values(feeds)) tensor.dispose?.();
    }
  }

  async dispose() {
    this.generation += 1;
    this.initializationController?.abort();
    this.initializationController = null;
    const initializing = this.initializing;
    if (initializing !== null) await initializing.catch(() => undefined);
    const session = this.session;
    this.session = null;
    this.manifest = null;
    this.tokenizer = null;
    this.webgpuError = null;
    this.provider = "disposed";
    if (session !== null) await session.release?.();
  }
}

