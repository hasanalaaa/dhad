const DEFAULT_MAX_CANDIDATES = 16;
const DEFAULT_MAX_TEXT_SCALARS = 4096;

function assertFiniteProbability(value, name) {
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    throw new RangeError(`${name} must be between 0 and 1`);
  }
}

export function stableSoftmax(logits, temperature = 1) {
  if (!Array.isArray(logits) && !ArrayBuffer.isView(logits)) {
    throw new TypeError("logits must be an array or typed array");
  }
  if (!Number.isFinite(temperature) || temperature <= 0) {
    throw new RangeError("temperature must be positive");
  }
  if (logits.length === 0) return [];
  const scaled = Array.from(logits, (value) => Number(value) / temperature);
  if (!scaled.every(Number.isFinite)) return [];
  const maximum = Math.max(...scaled);
  const exponents = scaled.map((value) => Math.exp(value - maximum));
  const total = exponents.reduce((sum, value) => sum + value, 0);
  if (!Number.isFinite(total) || total <= 0) return [];
  return exponents.map((value) => value / total);
}

export function selectConstrainedCandidate(
  candidates,
  logits,
  {
    confidenceThreshold = 0.999,
    marginThreshold = 0,
    temperature = 1,
  } = {},
) {
  assertFiniteProbability(confidenceThreshold, "confidenceThreshold");
  assertFiniteProbability(marginThreshold, "marginThreshold");
  if (!Array.isArray(candidates) || candidates.length === 0) {
    return Object.freeze({ abstained: true, reason: "no_candidates", confidence: 0, margin: 0 });
  }
  if (logits.length !== candidates.length) {
    return Object.freeze({ abstained: true, reason: "invalid_logits", confidence: 0, margin: 0 });
  }
  const probabilities = stableSoftmax(logits, temperature);
  if (probabilities.length !== candidates.length) {
    return Object.freeze({ abstained: true, reason: "invalid_logits", confidence: 0, margin: 0 });
  }
  const ranked = probabilities
    .map((probability, index) => ({ probability, index }))
    .sort((left, right) => right.probability - left.probability || left.index - right.index);
  const confidence = ranked[0].probability;
  const margin = Math.max(0, confidence - (ranked[1]?.probability ?? 0));
  if (confidence < confidenceThreshold) {
    return Object.freeze({ abstained: true, reason: "low_confidence", confidence, margin });
  }
  if (margin < marginThreshold) {
    return Object.freeze({ abstained: true, reason: "low_margin", confidence, margin });
  }
  const selectedIndex = ranked[0].index;
  return Object.freeze({
    abstained: false,
    selectedIndex,
    selected: candidates[selectedIndex],
    confidence,
    margin,
    probabilities: Object.freeze(probabilities),
  });
}

function requireString(value, name, { allowEmpty = false, maxScalars = 512 } = {}) {
  if (typeof value !== "string") throw new TypeError(`${name} must be a string`);
  const length = [...value].length;
  if ((!allowEmpty && length === 0) || length > maxScalars) {
    throw new RangeError(`${name} has an invalid length`);
  }
  return value;
}

function sanitizeCandidate(candidate) {
  if (candidate === null || typeof candidate !== "object" || Array.isArray(candidate)) {
    throw new TypeError("candidate must be an object");
  }
  const prior = candidate.prior === undefined ? 0 : Number(candidate.prior);
  if (!Number.isFinite(prior) || prior < -20 || prior > 20) {
    throw new RangeError("candidate prior is invalid");
  }
  return Object.freeze({
    id: requireString(candidate.id, "candidate id", { maxScalars: 256 }),
    value: requireString(candidate.value, "candidate value", { maxScalars: 128 }),
    lemma: requireString(candidate.lemma ?? "", "candidate lemma", {
      allowEmpty: true,
      maxScalars: 128,
    }),
    pos: requireString(candidate.pos ?? "unknown", "candidate pos", { maxScalars: 64 }),
    root:
      candidate.root === null || candidate.root === undefined || candidate.root === ""
        ? null
        : requireString(candidate.root, "candidate root", { maxScalars: 64 }),
    prior,
  });
}

export function validateRankRequest(request, { maxCandidates = DEFAULT_MAX_CANDIDATES } = {}) {
  if (request === null || typeof request !== "object" || Array.isArray(request)) {
    throw new TypeError("rank request must be an object");
  }
  const requestId = requireString(request.requestId, "requestId", { maxScalars: 128 });
  const sentence = requireString(request.sentence, "sentence", {
    maxScalars: DEFAULT_MAX_TEXT_SCALARS,
  });
  if (!Array.isArray(request.tokens) || request.tokens.length === 0 || request.tokens.length > 512) {
    throw new RangeError("tokens must contain between 1 and 512 items");
  }
  const tokens = Object.freeze(
    request.tokens.map((value, index) =>
      requireString(value, `tokens[${index}]`, { maxScalars: 256 }),
    ),
  );
  const tokenIndex = Number(request.tokenIndex);
  if (!Number.isInteger(tokenIndex) || tokenIndex < 0 || tokenIndex >= tokens.length) {
    throw new RangeError("tokenIndex is outside tokens");
  }
  const sentenceStart = Number(request.sentenceStart);
  const targetStart = Number(request.targetStart);
  const targetEnd = Number(request.targetEnd);
  if (![sentenceStart, targetStart, targetEnd].every(Number.isSafeInteger)) {
    throw new RangeError("source offsets must be safe integers");
  }
  if (sentenceStart < 0 || targetStart < sentenceStart || targetEnd <= targetStart) {
    throw new RangeError("source offsets are invalid");
  }
  if (
    !Array.isArray(request.candidates) ||
    request.candidates.length < 2 ||
    request.candidates.length > maxCandidates
  ) {
    throw new RangeError(`candidates must contain between 2 and ${maxCandidates} items`);
  }
  const candidates = Object.freeze(request.candidates.map(sanitizeCandidate));
  const identities = new Set();
  for (const candidate of candidates) {
    if (identities.has(candidate.id)) throw new RangeError("duplicate candidate id");
    identities.add(candidate.id);
  }
  return Object.freeze({
    requestId,
    sentence,
    sentenceStart,
    tokenIndex,
    tokens,
    targetStart,
    targetEnd,
    candidates,
  });
}

function analysisIdentity(analysis) {
  return `${analysis.lemma ?? analysis.token ?? ""}|${analysis.pos ?? "unknown"}|${analysis.root ?? "-"}`;
}

export function collectMorphologyRequests(parsed) {
  if (parsed === null || typeof parsed !== "object" || !Array.isArray(parsed.sentences)) {
    throw new TypeError("Rust parse must contain a sentences array");
  }
  const requests = [];
  for (const [sentenceIndex, sentence] of parsed.sentences.entries()) {
    if (!sentence || !Array.isArray(sentence.tokens) || typeof sentence.text !== "string") continue;
    const tokens = sentence.tokens.map((token) => String(token.text ?? ""));
    for (const [tokenIndex, token] of sentence.tokens.entries()) {
      const analyses = [token.analysis, ...(Array.isArray(token.alternatives) ? token.alternatives : [])]
        .filter((value) => value && typeof value === "object");
      const distinct = new Map();
      for (const analysis of analyses) {
        const id = analysisIdentity(analysis);
        const prior = Number(analysis.confidence ?? 0);
        const existing = distinct.get(id);
        if (existing === undefined || prior > existing.prior) {
          distinct.set(
            id,
            Object.freeze({
              id,
              value: String(token.text ?? analysis.token ?? ""),
              lemma: String(analysis.lemma ?? ""),
              pos: String(analysis.pos ?? "unknown"),
              root: analysis.root == null ? null : String(analysis.root),
              prior: Number.isFinite(prior) ? Math.log(Math.max(prior, 1e-6)) * 0.08 : 0,
            }),
          );
        }
      }
      if (distinct.size < 2) continue;
      requests.push(
        validateRankRequest({
          requestId: `morph:${sentenceIndex}:${tokenIndex}:${token.start}`,
          sentence: sentence.text,
          sentenceStart: Number(sentence.start ?? 0),
          tokenIndex,
          tokens,
          targetStart: Number(token.start),
          targetEnd: Number(token.end),
          candidates: [...distinct.values()],
        }),
      );
    }
  }
  return Object.freeze(requests);
}

function basicTokens(text, lowercase) {
  let normalized = text.normalize("NFC").replace(/[\u0000\uFFFD]/gu, " ");
  if (lowercase) normalized = normalized.toLocaleLowerCase("und");
  return normalized.match(/[\p{L}\p{M}\p{N}]+|[^\s]/gu) ?? [];
}

export class WordPieceTokenizer {
  static fromVocabText(text, options = {}) {
    if (typeof text !== "string" || text.length === 0) {
      throw new TypeError("vocab text must be non-empty");
    }
    const vocabulary = text
      .split(/\r?\n/u)
      .map((token) => token.trimEnd())
      .filter((token, index, values) => token.length > 0 || index < values.length - 1);
    return new WordPieceTokenizer(vocabulary, options);
  }

  constructor(vocabulary, { maxLength = 128, lowercase = false, maxWordScalars = 100 } = {}) {
    if (!Array.isArray(vocabulary) || vocabulary.length < 4) {
      throw new RangeError("vocabulary is too small");
    }
    if (!Number.isInteger(maxLength) || maxLength < 8 || maxLength > 512) {
      throw new RangeError("maxLength must be between 8 and 512");
    }
    this.vocabulary = Object.freeze([...vocabulary]);
    this.ids = new Map(this.vocabulary.map((token, index) => [token, index]));
    this.maxLength = maxLength;
    this.lowercase = Boolean(lowercase);
    this.maxWordScalars = maxWordScalars;
    for (const special of ["[PAD]", "[UNK]", "[CLS]", "[SEP]"]) {
      if (!this.ids.has(special)) throw new Error(`vocabulary is missing ${special}`);
    }
  }

  tokenize(text) {
    const output = [];
    for (const token of basicTokens(String(text), this.lowercase)) {
      if (this.ids.has(token)) {
        output.push(token);
        continue;
      }
      const scalars = [...token];
      if (scalars.length > this.maxWordScalars) {
        output.push("[UNK]");
        continue;
      }
      const pieces = [];
      let start = 0;
      let failed = false;
      while (start < scalars.length) {
        let end = scalars.length;
        let found = null;
        while (end > start) {
          const surface = scalars.slice(start, end).join("");
          const candidate = start === 0 ? surface : `##${surface}`;
          if (this.ids.has(candidate)) {
            found = candidate;
            break;
          }
          end -= 1;
        }
        if (found === null) {
          failed = true;
          break;
        }
        pieces.push(found);
        start = end;
      }
      output.push(...(failed ? ["[UNK]"] : pieces));
    }
    return output;
  }

  encodePair(first, second = "") {
    const left = this.tokenize(first);
    const right = second ? this.tokenize(second) : [];
    const specialCount = right.length > 0 ? 3 : 2;
    while (left.length + right.length + specialCount > this.maxLength) {
      if (right.length > left.length) right.pop();
      else left.pop();
    }
    const tokens = ["[CLS]", ...left, "[SEP]"];
    const tokenTypeIds = new Array(tokens.length).fill(0);
    if (right.length > 0) {
      tokens.push(...right, "[SEP]");
      tokenTypeIds.push(...new Array(right.length + 1).fill(1));
    }
    const inputIds = tokens.map((token) => this.ids.get(token) ?? this.ids.get("[UNK]"));
    const attentionMask = new Array(inputIds.length).fill(1);
    const padId = this.ids.get("[PAD]");
    while (inputIds.length < this.maxLength) {
      inputIds.push(padId);
      attentionMask.push(0);
      tokenTypeIds.push(0);
    }
    return Object.freeze({
      inputIds: Object.freeze(inputIds),
      attentionMask: Object.freeze(attentionMask),
      tokenTypeIds: Object.freeze(tokenTypeIds),
    });
  }
}

export function meanPool(hidden, dimensions, attentionMask) {
  if (!Array.isArray(dimensions) || dimensions.length !== 3) {
    throw new RangeError("hidden dimensions must be [batch, sequence, width]");
  }
  const [batch, sequence, width] = dimensions;
  if (![batch, sequence, width].every((value) => Number.isInteger(value) && value > 0)) {
    throw new RangeError("hidden dimensions must be positive integers");
  }
  if (hidden.length !== batch * sequence * width || attentionMask.length !== batch * sequence) {
    throw new RangeError("hidden state or attention mask has an invalid length");
  }
  const rows = [];
  for (let batchIndex = 0; batchIndex < batch; batchIndex += 1) {
    const pooled = new Float64Array(width);
    let count = 0;
    for (let tokenIndex = 0; tokenIndex < sequence; tokenIndex += 1) {
      const mask = Number(attentionMask[batchIndex * sequence + tokenIndex]);
      if (mask === 0) continue;
      count += 1;
      const base = (batchIndex * sequence + tokenIndex) * width;
      for (let column = 0; column < width; column += 1) pooled[column] += hidden[base + column];
    }
    if (count === 0) throw new RangeError("cannot pool an empty sequence");
    let magnitude = 0;
    for (let column = 0; column < width; column += 1) {
      pooled[column] /= count;
      magnitude += pooled[column] * pooled[column];
    }
    magnitude = Math.sqrt(magnitude);
    if (magnitude > 0) {
      for (let column = 0; column < width; column += 1) pooled[column] /= magnitude;
    }
    rows.push(pooled);
  }
  return Object.freeze(rows);
}

export function cosineSimilarity(left, right) {
  if (left.length !== right.length || left.length === 0) {
    throw new RangeError("cosine vectors must have the same non-zero length");
  }
  let dot = 0;
  let leftMagnitude = 0;
  let rightMagnitude = 0;
  for (let index = 0; index < left.length; index += 1) {
    dot += left[index] * right[index];
    leftMagnitude += left[index] * left[index];
    rightMagnitude += right[index] * right[index];
  }
  const denominator = Math.sqrt(leftMagnitude) * Math.sqrt(rightMagnitude);
  return denominator === 0 ? 0 : dot / denominator;
}

export function rankCandidateEmbeddings(candidates, embeddings, options = {}) {
  if (!Array.isArray(embeddings) || embeddings.length !== candidates.length + 1) {
    return Object.freeze({ abstained: true, reason: "invalid_embeddings", confidence: 0, margin: 0 });
  }
  const context = embeddings[0];
  const logits = candidates.map((candidate, index) => {
    const prior = Number(candidate.prior ?? 0);
    return cosineSimilarity(context, embeddings[index + 1]) + (Number.isFinite(prior) ? prior : 0);
  });
  return selectConstrainedCandidate(candidates, logits, options);
}

const POS_ARABIC = Object.freeze({
  verb: "فعل",
  noun: "اسم",
  adjective: "صفة",
  adverb: "ظرف",
  proper_noun: "اسم علم",
  verbal_noun: "مصدر",
  particle: "حرف",
  pronoun: "ضمير",
});

export function candidateDescription(candidate) {
  const fields = [candidate.value, candidate.lemma, POS_ARABIC[candidate.pos] ?? candidate.pos];
  if (candidate.root) fields.push(`الجذر ${candidate.root}`);
  return fields.filter(Boolean).join("؛ ");
}
