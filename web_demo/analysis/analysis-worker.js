import { loadEngine } from "../dhad-core.js";
import {
  analyzeWriting,
  applyLocalOverrides,
  buildExplanations,
  createDialectMatches,
} from "../intelligence/writing-intelligence.js";

const enginePromise = Promise.all([
  fetch(new URL("../dhad_core.wasm", import.meta.url)),
  fetch(new URL("../rules.json", import.meta.url)),
]).then(async ([wasmResponse, rulesResponse]) => {
  if (!wasmResponse.ok || !rulesResponse.ok) {
    throw new Error("deterministic engine assets are unavailable");
  }
  return loadEngine(await wasmResponse.arrayBuffer(), await rulesResponse.text());
});

function resolveDiagnostics(candidates) {
  const unique = new Map();
  for (const match of candidates) unique.set(`${match.rule_id}:${match.offset}:${match.length}`, match);
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

async function check(text, mode, preferences = {}) {
  const engine = await enginePromise;
  const started = performance.now();
  const { resolved } = engine.check(text);
  const parsed = text.trim() ? engine.parse(text) : null;
  const intelligenceBase = analyzeWriting(text);
  const dialectMatches = createDialectMatches(intelligenceBase.dialect);
  let matches = resolveDiagnostics([...resolved, ...dialectMatches]);
  if (mode === "style") {
    matches = resolveDiagnostics([
      ...matches.filter((match) => ["style", "grammar"].includes(match.category)),
      ...engine.syntaxCheck(text),
    ]);
  } else if (mode === "msa") {
    matches = matches.filter((match) => match.category === "dialect");
  }
  matches = applyLocalOverrides(matches, text, preferences);
  const intelligence = Object.freeze({
    ...intelligenceBase,
    explanations: buildExplanations(matches, text),
  });
  return {
    resolved: matches,
    parsed,
    intelligence,
    elapsedMs: performance.now() - started,
  };
}

globalThis.addEventListener("message", async (event) => {
  const message = event.data;
  if (message?.type !== "check" || typeof message.operationId !== "string") return;
  try {
    globalThis.postMessage({
      type: "checked",
      operationId: message.operationId,
      result: await check(message.text, message.mode, message.preferences),
    });
  } catch (error) {
    globalThis.postMessage({
      type: "error",
      operationId: message.operationId,
      error: { name: error instanceof Error ? error.name : "Error", message: String(error?.message ?? error) },
    });
  }
});
