import { AnalysisWorkerClient } from "../analysis/analysis-client.js";
import {
  analyzeWriting,
  applyLocalOverrides,
  buildExplanations,
  createDialectMatches,
} from "../intelligence/writing-intelligence.js";
import { rewriteText } from "../rewriting/offline-rewriter.js";

const VALID_ANALYSIS_MODES = new Set(["all", "style", "msa"]);

function tauriInvoke() {
  return globalThis.window?.__TAURI__?.core?.invoke
    ?? globalThis.__TAURI__?.core?.invoke
    ?? null;
}

export function isTauriEnvironment() {
  return typeof tauriInvoke() === "function";
}

async function invokeNative(command, request) {
  const invoke = tauriInvoke();
  if (typeof invoke !== "function") throw new Error("Tauri IPC is unavailable");
  return invoke(command, request === undefined ? undefined : { request });
}

function resolveDiagnostics(candidates) {
  const unique = new Map();
  for (const match of candidates) {
    unique.set(`${match.rule_id}:${match.offset}:${match.length}`, match);
  }
  const accepted = [];
  for (const match of [...unique.values()].sort(
    (a, b) => (b.priority ?? 0) - (a.priority ?? 0) || b.length - a.length || a.offset - b.offset,
  )) {
    const end = match.offset + match.length;
    if (!accepted.some((other) => match.offset < other.offset + other.length && other.offset < end)) {
      accepted.push(match);
    }
  }
  return accepted.sort((a, b) => a.offset - b.offset || b.length - a.length);
}

class NativeAnalysisClient {
  constructor() {
    this.disposed = false;
  }

  async check(text, mode = "all", { customWords = [], disabledRules = [] } = {}) {
    if (this.disposed) throw new Error("analysis client is disposed");
    if (typeof text !== "string") throw new TypeError("text must be a string");
    if (!VALID_ANALYSIS_MODES.has(mode)) throw new RangeError("unsupported analysis mode");
    if (!Array.isArray(customWords) || !Array.isArray(disabledRules)) {
      throw new TypeError("analysis preferences must be arrays");
    }

    const native = await invokeNative("analyze_text_native", { text });
    const intelligenceBase = analyzeWriting(text);
    let matches = resolveDiagnostics([
      ...(Array.isArray(native?.resolved) ? native.resolved : []),
      ...createDialectMatches(intelligenceBase.dialect),
    ]);
    if (mode === "style") {
      matches = matches.filter((match) => ["style", "grammar"].includes(match.category));
    } else if (mode === "msa") {
      matches = matches.filter((match) => match.category === "dialect");
    }
    matches = applyLocalOverrides(matches, text, { customWords, disabledRules });
    return Object.freeze({
      resolved: Object.freeze(matches),
      parsed: native?.parsed ?? null,
      intelligence: Object.freeze({
        ...intelligenceBase,
        explanations: buildExplanations(matches, text),
      }),
      elapsedMs: Number.isFinite(native?.elapsedMs) ? native.elapsedMs : 0,
      backend: native?.backend ?? "tauri-rust-native",
    });
  }

  dispose() {
    this.disposed = true;
  }
}

export function createAnalysisClient(options) {
  return isTauriEnvironment() ? new NativeAnalysisClient() : new AnalysisWorkerClient(options);
}

export async function analyzeText(text, mode = "all", preferences = {}) {
  const client = createAnalysisClient();
  try {
    return await client.check(text, mode, preferences);
  } finally {
    client.dispose();
  }
}

export async function paraphraseText(text, mode = "formal", {
  alternatives = 3,
  dialectConversions = [],
} = {}) {
  if (!isTauriEnvironment()) {
    return rewriteText(text, mode, { alternatives, dialectConversions });
  }
  return invokeNative("paraphrase_native", {
    text,
    mode,
    alternatives,
    dialectConversions,
  });
}

export async function getDesktopSystemInfo() {
  if (!isTauriEnvironment()) {
    return Object.freeze({
      appName: "ضاد",
      nativeIpc: false,
      backend: "browser-wasm-worker",
      platform: globalThis.navigator?.platform ?? "web",
    });
  }
  return invokeNative("get_system_info");
}

export const desktopAdapter = Object.freeze({
  isTauriEnvironment,
  createAnalysisClient,
  analyzeText,
  paraphraseText,
  getDesktopSystemInfo,
});
