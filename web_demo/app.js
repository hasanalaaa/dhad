/**
 * app.js — ضاد web demo: premium RTL editor wired to the dhad-core WASM engine.
 *
 * Everything runs locally: the engine (dhad-core.js bridge over dhad_core.wasm)
 * checks text deterministically; the Web Speech API handles Arabic dictation.
 * The editor is a plaintext contenteditable with a marks layer (Grammarly-style
 * squiggles) rebuilt from engine offsets, which arrive in Unicode code points.
 */

import { loadEngine } from "./dhad-core.js";
import { NeuralInferenceClient } from "./neural/neural-client.js";
import { collectMorphologyRequests } from "./neural/neural-core.js";
import { DhadStorage, OutboxRecovery } from "./storage/db.js";
import {
  analyzeWriting,
  applyLocalOverrides,
  buildExplanations,
  createDialectMatches,
  guidanceForTarget,
  parseLexiconInput,
} from "./intelligence/writing-intelligence.js";
import {
  VIRTUALIZATION_THRESHOLD,
  buildOverlaySegments,
  chunkOverlaySegments,
  computeVirtualWindow,
} from "./ui/rendering.js";
import { REWRITE_MODES } from "./rewriting/offline-rewriter.js";
import { createAnalysisClient, paraphraseText } from "./js/desktop-adapter.js";
import { nativeDocumentDialogsAvailable, pickNativeDocument, saveNativeDocument } from "./js/native-file-dialogs.js";
import { advancedAnalytics, analyticsTrend } from "./analytics/writing-analytics.js";
import { SMART_TEMPLATES, generateFromTemplate, templateById } from "./templates/smart-templates.js";
import { ThemeController } from "./themes/theme-controller.js";
import { downloadBlob, exportDocument, importDocument, markdownToHtml } from "./documents/document-io.js";
import { GOLD_CAPABILITIES, assertCapabilityParity } from "./shared/capabilities.js";

/* ── DOM handles ─────────────────────────────────────────────── */
const $ = (id) => document.getElementById(id);
const editor = $("editor");
const editorOverlay = $("editorOverlay");
const issuesList = $("issues");
const emptyState = $("emptyState");
const hoverCard = $("hoverCard");
const toastBox = $("toast");
const engineDot = $("engineDot");
const engineLabel = $("engineLabel");
const lexiconDialog = $("lexiconDialog");
const lexiconWords = $("lexiconWords");
const disabledRulesList = $("disabledRulesList");

const stat = {
  rules: $("statRules"),
  words: $("statWords"),
  issues: $("statIssues"),
  latency: $("statLatency"),
};

let customWords = [];
let disabledRules = new Set();
let writingIntelligence = null;
let documentTitle = "مستند-ضاد";
let currentAnalytics = null;
let lastAnalyticsSnapshotAt = 0;
let selectedRewriteMode = "formal";
let generatedTemplateText = "";
let templateInsertOffset = null;
let themeController = null;

const TONE_LABELS = Object.freeze({
  academic: "أكاديمية",
  formal: "رسمية",
  casual: "ودّية",
  persuasive: "إقناعية",
});
const DIALECT_LABELS = Object.freeze({
  msa: "فصحى",
  iraqi: "عراقية",
  egyptian: "مصرية",
  levantine: "شامية",
  gulf: "خليجية",
  shared: "لهجية مشتركة",
});

function updateConnectivityStatus() {
  const status = $("connectivityStatus");
  const online = navigator.onLine;
  status.classList.toggle("offline", !online);
  status.textContent = online ? "متصل · المزامنة جاهزة" : "دون اتصال · محفوظ محليًا";
}
window.addEventListener("online", updateConnectivityStatus);
window.addEventListener("offline", updateConnectivityStatus);

const desktopEventApi = globalThis.window?.__TAURI__?.event;
if (typeof desktopEventApi?.listen === "function") {
  void desktopEventApi.listen("desktop:open-settings", () => {
    $("btnLexicon").click();
    setTimeout(() => $("themeSelect")?.focus(), 50);
  });
}
updateConnectivityStatus();

function observeAsync(promise, context, userMessage = null) {
  void Promise.resolve(promise).catch((error) => {
    console.error(`Dhad ${context} failed`, error);
    if (userMessage) toast(userMessage);
  });
}

/* ── Local logo fallback ────────────────────────────────────── */
{
  const img = $("logoImg");
  const fallback = () => {
    img.hidden = true;
    $("logoMono").hidden = false;
  };
  img.addEventListener("error", fallback);
  // The 404 may have fired before this module ran.
  if (img.complete && img.naturalWidth === 0) fallback();
}

/* ── PWA lifecycle ──────────────────────────────────────────── */
let deferredInstallPrompt = null;
const installButton = $("btnInstall");

if ("serviceWorker" in navigator) {
  window.addEventListener("load", async () => {
    try {
      await navigator.serviceWorker.register("./service-worker.js", { type: "module" });
    } catch (error) {
      console.warn("Dhad service worker registration failed", error);
    }
  });
}

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  installButton.hidden = false;
});

installButton.addEventListener("click", () => {
  if (!deferredInstallPrompt) return;
  const prompt = deferredInstallPrompt;
  deferredInstallPrompt = null;
  observeAsync(
    prompt.prompt().then(() => prompt.userChoice),
    "installation prompt",
    "تعذر بدء تثبيت التطبيق.",
  );
  installButton.hidden = true;
});

window.addEventListener("appinstalled", () => {
  deferredInstallPrompt = null;
  installButton.hidden = true;
});

/* ── Durable local state and reconnect recovery ─────────────── */
let storage = null;
let outboxRecovery = null;
try {
  storage = new DhadStorage();
  await storage.open();
  outboxRecovery = new OutboxRecovery(
    storage,
    async (entry) => {
      if (typeof entry.url !== "string") throw new Error("outbox entry has no sync URL");
      const response = await fetch(entry.url, {
        method: entry.method ?? "POST",
        headers: entry.headers ?? { "content-type": "application/octet-stream" },
        body: entry.payload instanceof Uint8Array ? entry.payload : JSON.stringify(entry.payload),
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error(`outbox sync failed (${response.status})`);
    },
    { onError: (error) => console.warn("Dhad background outbox recovery failed", error) },
  );
  outboxRecovery.start();
  if (navigator.onLine) observeAsync(outboxRecovery.flush(), "outbox recovery");
  navigator.serviceWorker?.addEventListener("message", (event) => {
    if (event.data?.type === "dhad:outbox-sync") {
      observeAsync(outboxRecovery.flush(), "background outbox recovery");
    }
  });
} catch (error) {
  console.warn("Dhad persistent storage is unavailable", error);
}

/* Runtime evidence for the 50ms long-task budget. */
const longTasks = [];
if ("PerformanceObserver" in globalThis) {
  try {
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) longTasks.push(entry.duration);
    });
    observer.observe({ type: "longtask", buffered: true });
  } catch {
    // Long Task API is optional; worker isolation remains the primary guardrail.
  }
}

/* ── Engine boot ─────────────────────────────────────────────── */
let engine = null;
try {
  const [wasmResponse, rulesResponse] = await Promise.all([
    fetch("dhad_core.wasm"),
    fetch("rules.json"),
  ]);
  if (!wasmResponse.ok || !rulesResponse.ok) {
    throw new Error(
      `تعذر جلب ملفات المحرك (WASM: ${wasmResponse.status}, rules: ${rulesResponse.status})`,
    );
  }
  engine = await loadEngine(await wasmResponse.arrayBuffer(), await rulesResponse.text());
  stat.rules.textContent = String(engine.ruleCount);
  stat.latency.nextElementSibling.textContent = "وقت القراءة";
  engineDot.classList.add("ready");
  engineLabel.textContent = "المحرك جاهز · WASM";
} catch (error) {
  engineDot.classList.add("failed");
  engineLabel.textContent = "تعذر تحميل المحرك";
  toast("تعذر تحميل نواة ضاد — تحقق من الخادم المحلي.");
  throw error;
}

const analysisClient = createAnalysisClient();

/* ── Candidate-constrained neural worker ───────────────────── */
const neuralClient = new NeuralInferenceClient({
  manifestUrl:
    globalThis.__DHAD_NEURAL_MANIFEST__ ??
    new URL("./models/student-manifest.json", import.meta.url),
});
const neuralState = {
  status: "idle",
  provider: null,
  modelId: null,
  decisions: Object.freeze([]),
  error: null,
  generation: 0,
};
let neuralIdleHandle = null;
let neuralPermanentlyUnavailable = false;
let neuralCacheWarmRequested = false;

function requestNeuralCacheWarmup() {
  if (neuralCacheWarmRequested) return;
  const controller = navigator.serviceWorker?.controller;
  if (!controller) return;
  neuralCacheWarmRequested = true;
  controller.postMessage({ type: "dhad:warm-neural-cache" });
}

function isPermanentNeuralFailure(error) {
  const message = error instanceof Error ? error.message : String(error);
  return /(?:SHA-256 mismatch|invalid model manifest|missing declared inputs|missing output|candidate-only contract|unsupported tokenizer|INT8|UINT8)/iu.test(message);
}

function setNeuralEngineLabel(provider, selected, total) {
  const accelerator = provider === "webgpu-preferred" ? "WebGPU" : "WASM SIMD";
  engineLabel.textContent = `المحرك جاهز · WASM + AI (${accelerator}) · حسم ${selected}/${total}`;
}

function scheduleIdle(callback) {
  if ("requestIdleCallback" in globalThis) {
    return globalThis.requestIdleCallback(callback, { timeout: 800 });
  }
  return globalThis.setTimeout(callback, 0);
}

function cancelScheduledIdle(handle) {
  if (handle === null) return;
  if ("cancelIdleCallback" in globalThis) globalThis.cancelIdleCallback(handle);
  else globalThis.clearTimeout(handle);
}

function scheduleNeuralAnalysis(text, existingParse = null) {
  neuralState.generation += 1;
  const generation = neuralState.generation;
  cancelScheduledIdle(neuralIdleHandle);
  neuralIdleHandle = null;
  if (neuralPermanentlyUnavailable || !text.trim()) {
    neuralState.decisions = Object.freeze([]);
    neuralState.status = neuralPermanentlyUnavailable ? "unavailable" : "idle";
    return;
  }
  neuralIdleHandle = scheduleIdle(async () => {
    neuralIdleHandle = null;
    if (generation !== neuralState.generation) return;
    try {
      const parsed = existingParse ?? engine.parse(text);
      const requests = collectMorphologyRequests(parsed);
      if (generation !== neuralState.generation) return;
      if (requests.length === 0) {
        neuralState.status = "no-ambiguity";
        neuralState.decisions = Object.freeze([]);
        return;
      }
      neuralState.status = "loading";
      requestNeuralCacheWarmup();
      engineLabel.textContent = "المحرك جاهز · WASM · تحميل AI محليًا…";
      const decisions = [];
      for (let start = 0; start < requests.length; start += 64) {
        decisions.push(...(await neuralClient.rankMany(requests.slice(start, start + 64))));
        if (generation !== neuralState.generation) return;
      }
      const status = neuralClient.readyStatus;
      neuralState.status = "ready";
      neuralState.provider = status.provider;
      neuralState.modelId = status.modelId;
      neuralState.decisions = Object.freeze(decisions);
      neuralState.error = null;
      setNeuralEngineLabel(
        status.provider,
        decisions.filter((decision) => !decision.abstained).length,
        decisions.length,
      );
    } catch (error) {
      if (generation !== neuralState.generation) return;
      const permanent = isPermanentNeuralFailure(error);
      neuralPermanentlyUnavailable = permanent;
      neuralState.status = permanent ? "unavailable" : "degraded";
      neuralState.error = error instanceof Error ? error.message : String(error);
      neuralState.decisions = Object.freeze([]);
      engineLabel.textContent = permanent
        ? "المحرك جاهز · WASM · AI غير متاح"
        : "المحرك جاهز · WASM · AI سيُعاد تلقائيًا";
      if (permanent) await neuralClient.dispose();
    }
  });
}

globalThis.addEventListener("pagehide", (event) => {
  if (!event.persisted) {
    observeAsync(neuralClient.dispose(), "neural runtime disposal");
    analysisClient.dispose();
    outboxRecovery?.stop();
    storage?.close();
  }
});

/* ── Editor text model ───────────────────────────────────────── */
/* The editor DOM only ever contains: text nodes, <br>, and
   <mark class="err"> wrapping a single text node. */

const SENTINEL_BR = "data-sentinel";

const ALLOWED_EDITOR_TAGS = new Set(["P", "DIV", "BR", "H1", "H2", "H3", "STRONG", "B", "EM", "I", "U", "UL", "OL", "LI", "CODE"]);
const BLOCK_EDITOR_TAGS = new Set(["P", "DIV", "H1", "H2", "H3", "LI"]);

function serialize(root) {
  let out = "";
  let previousWasBlock = false;
  for (const node of root.childNodes) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (previousWasBlock && out && !out.endsWith("\n")) out += "\n";
      out += node.data;
      previousWasBlock = false;
      continue;
    }
    if (node.nodeName === "BR") {
      if (!(node.hasAttribute?.(SENTINEL_BR))) out += "\n";
      previousWasBlock = false;
      continue;
    }
    const isBlock = BLOCK_EDITOR_TAGS.has(node.nodeName) || ["UL", "OL"].includes(node.nodeName);
    if (isBlock && out && !out.endsWith("\n")) out += "\n";
    out += serialize(node);
    previousWasBlock = isBlock;
  }
  return out.replace(/\n{3,}/gu, "\n\n");
}

function pointAtSerializedOffset(offset) {
  if (!Number.isInteger(offset) || offset < 0) return null;
  const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const prefix = document.createRange();
    prefix.selectNodeContents(editor);
    prefix.setEnd(node, 0);
    const start = serialize(prefix.cloneContents()).length;
    const end = start + node.data.length;
    if (offset >= start && offset <= end) return { node, offset: offset - start };
  }
  if (offset === getText().length) return { node: editor, offset: editor.childNodes.length };
  return null;
}

function replaceEditorTextSpan(start, end, replacement) {
  const startPoint = pointAtSerializedOffset(start);
  const endPoint = pointAtSerializedOffset(end);
  if (!startPoint || !endPoint) return false;
  try {
    const range = document.createRange();
    range.setStart(startPoint.node, startPoint.offset);
    range.setEnd(endPoint.node, endPoint.offset);
    range.deleteContents();
    const inserted = document.createTextNode(replacement);
    range.insertNode(inserted);
    const selection = window.getSelection();
    range.setStartAfter(inserted);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    return true;
  } catch (error) {
    console.warn("Rich-text replacement fell back to plaintext", error);
    return false;
  }
}

function sanitizeEditorFragment(source) {
  const template = document.createElement("template");
  template.innerHTML = String(source ?? "");
  const clean = document.createDocumentFragment();
  const appendClean = (input, output) => {
    for (const child of input.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        output.append(document.createTextNode(child.data));
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        if (!ALLOWED_EDITOR_TAGS.has(child.nodeName)) {
          appendClean(child, output);
          continue;
        }
        const element = document.createElement(child.nodeName.toLowerCase());
        if (element.nodeName === "A") continue;
        appendClean(child, element);
        output.append(element);
      }
    }
  };
  appendClean(template.content, clean);
  return clean;
}

function setEditorHtml(html) {
  editor.replaceChildren(sanitizeEditorFragment(html));
}

function setEditorText(text) {
  const lines = String(text ?? "").split(/\r?\n/gu);
  const fragment = document.createDocumentFragment();
  for (const line of lines) {
    const paragraph = document.createElement("p");
    paragraph.textContent = line;
    if (!line) paragraph.append(document.createElement("br"));
    fragment.append(paragraph);
  }
  editor.replaceChildren(fragment);
}

function sanitizedEditorHtml() {
  const wrapper = document.createElement("div");
  wrapper.append(sanitizeEditorFragment(editor.innerHTML));
  return wrapper.innerHTML;
}

function getText() {
  return serialize(editor);
}

function caretOffset() {
  const selection = window.getSelection();
  if (!selection.rangeCount) return null;
  const range = selection.getRangeAt(0);
  if (!editor.contains(range.endContainer)) return null;
  const pre = document.createRange();
  pre.selectNodeContents(editor);
  pre.setEnd(range.endContainer, range.endOffset);
  return serialize(pre.cloneContents()).length;
}

function setCaret(offset) {
  const selection = window.getSelection();
  const range = document.createRange();
  let remaining = offset;
  let placed = false;

  (function walk(node) {
    if (placed) return;
    for (const child of node.childNodes) {
      if (placed) return;
      if (child.nodeType === Node.TEXT_NODE) {
        if (remaining <= child.data.length) {
          range.setStart(child, remaining);
          placed = true;
          return;
        }
        remaining -= child.data.length;
      } else if (child.nodeName === "BR") {
        if (!child.hasAttribute(SENTINEL_BR)) {
          if (remaining === 0) {
            range.setStartBefore(child);
            placed = true;
            return;
          }
          remaining -= 1;
        }
      } else {
        walk(child);
      }
    }
  })(editor);

  if (!placed) {
    range.selectNodeContents(editor);
    range.collapse(false);
  }
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

/* Engine offsets are code points; DOM/JS strings are UTF-16. */
function codePointIndex(text) {
  const map = [0];
  let utf16 = 0;
  for (const ch of text) {
    utf16 += ch.length;
    map.push(utf16);
  }
  return map;
}

/* ── State ───────────────────────────────────────────────────── */
const MODES = {
  all: { label: "تدقيق شامل", categories: null },
  style: { label: "الأسلوب والنحو", categories: new Set(["style", "grammar"]) },
  msa: { label: "تحويل للفصحى", categories: new Set(["dialect"]) },
};

let mode = "all"; // which check the toolbar last requested
let sideFilter = "all"; // sidebar chip filter
let matches = []; // current matches, sorted by offset (code points)
let dismissed = new Set(); // `${rule_id}:${offset}` the user chose to ignore
let composing = false;
let activeMatchIndex = -1;

/* ── Rendering: composited squiggle overlay ─────────────────── */
async function renderOverlay(text, visibleMatches, generation = checkGeneration) {
  const matchIndexes = new Map(visibleMatches.map((match, index) => [match, index]));

  const pushText = (fragment, chunk, match) => {
    const parts = chunk.split("\n");
    parts.forEach((part, i) => {
      if (i > 0) fragment.appendChild(document.createElement("br"));
      if (!part) return;
      if (!match) {
        fragment.appendChild(document.createTextNode(part));
        return;
      }
      const markNode = document.createElement("mark");
      markNode.className = `err sev-${match.severity} cat-${match.category}`;
      markNode.dataset.i = String(matchIndexes.get(match));
      markNode.textContent = part;
      fragment.appendChild(markNode);
    });
  };

  const chunks = chunkOverlaySegments(buildOverlaySegments(text, visibleMatches));
  editorOverlay.replaceChildren();
  for (const chunk of chunks) {
    if (generation !== checkGeneration || text !== getText()) return false;
    const fragment = document.createDocumentFragment();
    for (const segment of chunk) pushText(fragment, segment.text, segment.match);
    editorOverlay.appendChild(fragment);
    if (chunk !== chunks.at(-1)) await nextAnimationFrame();
  }
  editorOverlay.style.transform = `translate3d(0, ${-editor.scrollTop}px, 0)`;
  return true;
}

/* ── Rendering: sidebar ──────────────────────────────────────── */
const CATEGORY_LABEL = {
  spelling: "إملاء",
  grammar: "نحو",
  style: "أسلوب",
  dialect: "فصحى",
  tashkeel: "تشكيل",
};
const SEVERITY_LABEL = { error: "خطأ", warning: "تنبيه", hint: "اقتراح" };

let sidebarModel = { text: "", codePoints: [0], shown: [] };
let sidebarRenderFrame = null;

function createIssueCard({ match, index }) {
  const item = document.createElement("li");
  item.className = `issue sev-${match.severity} cat-${match.category}`;
  item.dataset.i = String(index);
  item.tabIndex = 0;
  item.role = "button";
  item.setAttribute("aria-label", `${CATEGORY_LABEL[match.category] ?? match.category}: ${match.message}`);

  const start = sidebarModel.codePoints[match.offset];
  const end = sidebarModel.codePoints[match.offset + match.length];
  const swap = document.createElement("div");
  swap.className = "issue-swap";
  const dot = document.createElement("span");
  dot.className = "issue-dot";
  const wrong = document.createElement("s");
  wrong.textContent = sidebarModel.text.slice(start, end);
  const arrow = document.createElement("span");
  arrow.className = "sw-arrow";
  arrow.textContent = "←";
  const right = document.createElement("b");
  right.textContent = match.replacements[0] ?? "؟";
  swap.append(dot, wrong, arrow, right);

  const message = document.createElement("div");
  message.className = "issue-msg";
  message.textContent = match.message;
  const explanation = explanationFor(match);
  if (explanation) {
    const why = document.createElement("p");
    why.className = "issue-why";
    why.textContent = explanation.whyItMatters;
    message.appendChild(why);
  }

  const foot = document.createElement("div");
  foot.className = "issue-foot";
  const category = document.createElement("span");
  category.className = "issue-cat";
  category.textContent = CATEGORY_LABEL[match.category] ?? match.category;
  foot.appendChild(category);
  if (match.replacements.length) {
    const apply = document.createElement("button");
    apply.className = "issue-apply";
    apply.textContent = "تطبيق";
    apply.type = "button";
    apply.dataset.action = "apply";
    apply.dataset.i = String(index);
    foot.appendChild(apply);
  }

  const dismiss = document.createElement("button");
  dismiss.className = "issue-apply issue-dismiss";
  dismiss.textContent = "تجاهل";
  dismiss.type = "button";
  dismiss.dataset.action = "dismiss";
  dismiss.dataset.i = String(index);
  foot.appendChild(dismiss);
  item.append(swap, message, foot);
  return item;
}

function renderSidebarWindow() {
  sidebarRenderFrame = null;
  const { shown } = sidebarModel;
  const windowed = computeVirtualWindow({
    count: shown.length,
    scrollTop: issuesList.scrollTop,
    viewportHeight: Math.min(issuesList.clientHeight || 600, window.innerHeight || 600),
  });
  const virtualized = shown.length > VIRTUALIZATION_THRESHOLD;
  issuesList.classList.toggle("virtualized", virtualized);
  issuesList.style.paddingBlockStart = virtualized ? `${windowed.paddingStart + 10}px` : "";
  issuesList.style.paddingBlockEnd = virtualized ? `${windowed.paddingEnd + 10}px` : "";
  issuesList.replaceChildren(...shown.slice(windowed.start, windowed.end).map(createIssueCard));
}

function renderSidebar(text, visibleMatches) {
  sidebarModel = {
    text,
    codePoints: codePointIndex(text),
    shown: visibleMatches
      .map((match, index) => ({ match, index }))
      .filter(({ match }) => sideFilter === "all" || match.category === sideFilter),
  };
  emptyState.classList.toggle("show", sidebarModel.shown.length === 0);
  renderSidebarWindow();
}

issuesList.addEventListener("scroll", () => {
  if (sidebarModel.shown.length <= VIRTUALIZATION_THRESHOLD || sidebarRenderFrame !== null) return;
  sidebarRenderFrame = requestAnimationFrame(renderSidebarWindow);
}, { passive: true });

/* ── Writing intelligence dashboard ───────────────────────── */
function formatPercent(value) {
  return String(Math.round(Math.max(0, Math.min(1, value || 0)) * 100));
}

function renderWritingIntelligence(report) {
  writingIntelligence = report;
  const hasText = Boolean(getText().trim());
  if (!report || !hasText) {
    $("wiTone").textContent = "—";
    $("wiToneConfidence").textContent = "ابدأ الكتابة لرصد النبرة";
    $("wiClarity").textContent = "100";
    $("wiComplexity").textContent = "تعقيد منخفض";
    $("wiRichness").textContent = "0";
    $("wiDensity").textContent = "كثافة متوازنة";
    $("wiDialect").textContent = "فصحى";
    $("wiDialectCount").textContent = "لا تحويلات مقترحة";
    $("toneChips").replaceChildren();
    return;
  }
  const { tone, readability, dialect, suggestionChips } = report;
  $("wiTone").textContent = TONE_LABELS[tone.primary] ?? tone.primary;
  $("wiToneConfidence").textContent = `ثقة ${formatPercent(tone.confidence)}%`;
  $("wiClarity").textContent = String(Math.round(readability.clarityScore));
  $("wiComplexity").textContent = `تعقيد ${Math.round(readability.complexityScore)}/100`;
  $("wiRichness").textContent = formatPercent(readability.lexicalRichness);
  $("wiDensity").textContent = `${readability.averageWordsPerSentence.toFixed(1)} كلمة/جملة`;
  $("wiDialect").textContent = DIALECT_LABELS[dialect.primary] ?? dialect.primary;
  $("wiDialectCount").textContent = dialect.conversions.length
    ? `${dialect.conversions.length} تحويل فصيح مقترح`
    : "لا تحويلات مقترحة";

  const fragment = document.createDocumentFragment();
  for (const chip of suggestionChips.slice(0, 3)) {
    const wrapper = document.createElement("span");
    wrapper.className = "tone-chip-wrap";
    const button = document.createElement("button");
    const tooltip = document.createElement("span");
    const tooltipId = `tone-tip-${chip.target}`;
    button.type = "button";
    button.className = "tone-chip";
    button.dataset.target = chip.target;
    button.setAttribute("aria-describedby", tooltipId);
    button.textContent = chip.label;
    tooltip.id = tooltipId;
    tooltip.className = "tone-tooltip";
    tooltip.role = "tooltip";
    tooltip.textContent = chip.rationale;
    wrapper.append(button, tooltip);
    fragment.appendChild(wrapper);
  }
  $("toneChips").replaceChildren(fragment);
}

function explanationFor(match) {
  return writingIntelligence?.explanations?.find(
    (item) => item.ruleId === match.rule_id && item.offset === match.offset && item.length === match.length,
  ) ?? null;
}

function renderDisabledRules() {
  const fragment = document.createDocumentFragment();
  for (const ruleId of [...disabledRules].sort()) {
    const item = document.createElement("li");
    const code = document.createElement("code");
    code.textContent = ruleId;
    const restore = document.createElement("button");
    restore.type = "button";
    restore.dataset.ruleId = ruleId;
    restore.textContent = "إعادة التفعيل";
    item.append(code, restore);
    fragment.appendChild(item);
  }
  disabledRulesList.replaceChildren(fragment);
  $("disabledRuleCount").textContent = `${disabledRules.size} قاعدة`;
  $("noDisabledRules").hidden = disabledRules.size > 0;
}

async function persistWritingPreferences() {
  if (!storage) return;
  await Promise.all([
    storage.putDictionary({ id: "personal", words: customWords }),
    storage.setSetting("disabledRules", [...disabledRules]),
  ]);
}

/* ── Check pipeline ──────────────────────────────────────────── */
function visibleOf(allMatches) {
  const categories = MODES[mode]?.categories ?? null;
  return allMatches.filter((match) => {
    if (dismissed.has(`${match.rule_id}:${match.offset}`)) return false;
    if (match.category === "tashkeel") return true; // tashkeel survives any mode
    return categories === null || categories.has(match.category);
  });
}

/* syntaxCheck() returns raw grammar matches. Merge them with style rules while
   retaining one deterministic, non-overlapping diagnostic per text span. */
function resolveDiagnostics(candidates) {
  const unique = new Map();
  for (const match of candidates) {
    unique.set(`${match.rule_id}:${match.offset}:${match.length}`, match);
  }

  const accepted = [];
  for (const match of [...unique.values()].sort(
    (a, b) =>
      (b.priority ?? 0) - (a.priority ?? 0) ||
      b.length - a.length ||
      a.offset - b.offset,
  )) {
    const end = match.offset + match.length;
    const overlaps = accepted.some(
      (other) => match.offset < other.offset + other.length && other.offset < end,
    );
    if (!overlaps) accepted.push(match);
  }
  return accepted.sort((a, b) => a.offset - b.offset || b.length - a.length);
}

let checkGeneration = 0;

function nextAnimationFrame() {
  return new Promise((resolve) => requestAnimationFrame(resolve));
}

async function runCheck({ keepTashkeel = false } = {}) {
  const text = getText();
  const generation = ++checkGeneration;
  let analysis;
  try {
    analysis = await analysisClient.check(text, mode, {
      customWords,
      disabledRules: [...disabledRules],
    });
  } catch (error) {
    console.warn("Analysis worker unavailable; using deterministic local fallback", error);
    const started = performance.now();
    const { resolved } = engine.check(text);
    const parsed = text.trim() ? engine.parse(text) : null;
    const intelligenceBase = analyzeWriting(text);
    let checked = resolveDiagnostics([
      ...resolved,
      ...createDialectMatches(intelligenceBase.dialect),
    ]);
    if (mode === "style") {
      checked = resolveDiagnostics([
        ...checked.filter((match) => ["style", "grammar"].includes(match.category)),
        ...engine.syntaxCheck(text),
      ]);
    } else if (mode === "msa") {
      checked = checked.filter((match) => match.category === "dialect");
    }
    const locallyFiltered = applyLocalOverrides(checked, text, {
      customWords,
      disabledRules: [...disabledRules],
    });
    analysis = {
      resolved: locallyFiltered,
      parsed,
      intelligence: Object.freeze({
        ...intelligenceBase,
        explanations: buildExplanations(locallyFiltered, text),
      }),
      elapsedMs: performance.now() - started,
    };
  }
  if (generation !== checkGeneration || text !== getText()) return [];

  const kept = keepTashkeel ? matches.filter((m) => m.category === "tashkeel") : [];
  matches = resolveDiagnostics([...analysis.resolved, ...kept]);
  renderWritingIntelligence(analysis.intelligence);

  const visible = visibleOf(matches);
  await nextAnimationFrame();
  if (generation !== checkGeneration || text !== getText()) return [];
  renderSidebar(text, visible);
  updateStats(text, visible, analysis.elapsedMs, analysis.parsed);
  updateFixAll(visible);
  hideCard();
  if (!(await renderOverlay(text, visible, generation))) return [];
  scheduleNeuralAnalysis(text, analysis.parsed);
  return visible;
}

function updateStats(text, visible, elapsed, parsed = null) {
  stat.issues.textContent = String(visible.length);
  const wordCount = text.match(/[\p{L}\p{N}]+/gu)?.length ?? 0;
  stat.words.textContent = String(wordCount);
  stat.latency.textContent =
    wordCount === 0 ? "0 د" : wordCount < 180 ? "< 1 د" : `${Math.ceil(wordCount / 180)} د`;
  const sentenceCount = parsed?.sentences?.length;
  stat.latency.title =
    `زمن آخر فحص: ${elapsed.toFixed(2)} م.ث` +
    (Number.isInteger(sentenceCount) ? ` · الجمل المحللة: ${sentenceCount}` : "");
}

function updateFixAll(visible) {
  const fixable = visible.filter((m) => m.autofix && m.replacements.length);
  const button = $("btnFixAll");
  button.hidden = fixable.length === 0;
  button.style.display = fixable.length === 0 ? "none" : "";
  $("fixCount").textContent = String(fixable.length);
}

/* ── Applying corrections ────────────────────────────────────── */
function applyMatch(match) {
  const text = getText();
  const cpIndex = codePointIndex(text);
  const start = cpIndex[match.offset];
  const end = cpIndex[match.offset + match.length];
  const replacement = match.replacements[0];
  if (start === undefined || end === undefined || replacement === undefined) return;
  const next = text.slice(0, start) + replacement + text.slice(end);
  const preservedFormatting = replaceEditorTextSpan(start, end, replacement);
  if (!preservedFormatting) {
    setEditorText(next);
    setCaret(start + replacement.length);
  }
  scheduleDocumentSave(next);
  observeAsync(runCheck(), "document analysis");
}

function applyAll() {
  const visible = visibleOf(matches).filter((m) => m.autofix && m.replacements.length);
  if (!visible.length) return;
  let text = getText();
  const cpIndex = codePointIndex(text);
  let richReplacementSucceeded = true;
  for (const match of [...visible].sort((a, b) => b.offset - a.offset)) {
    const start = cpIndex[match.offset];
    const end = cpIndex[match.offset + match.length];
    const replacement = match.replacements[0];
    if (start === undefined || end === undefined || replacement === undefined) continue;
    if (!replaceEditorTextSpan(start, end, replacement)) richReplacementSucceeded = false;
    text = text.slice(0, start) + replacement + text.slice(end);
  }
  if (!richReplacementSucceeded) setEditorText(text);
  scheduleDocumentSave(text);
  observeAsync(runCheck(), "document analysis");
  toast(`أُصلحت ${visible.length} ملاحظة تلقائيًا ✓`);
}

/* ── Partial tashkeel (experimental, via dc_tokenize) ────────── */
/* Deterministic vocalization for unambiguous, high-frequency words.
   Tokens come from the WASM tokenizer with code-point offsets. */
const TASHKEEL_LEXICON = {
  "من": "مِنْ", "عن": "عَنْ", "على": "عَلَى", "إلى": "إِلَى", "في": "فِي",
  "حتى": "حَتَّى", "لكن": "لَكِنْ", "قد": "قَدْ", "لن": "لَنْ", "لم": "لَمْ",
  "لا": "لَا", "ما": "مَا", "إذا": "إِذَا", "ثم": "ثُمَّ", "أو": "أَوْ",
  "بل": "بَلْ", "هل": "هَلْ", "نعم": "نَعَمْ", "هو": "هُوَ", "هي": "هِيَ",
  "هم": "هُمْ", "أنا": "أَنَا", "نحن": "نَحْنُ", "الذي": "الَّذِي",
  "التي": "الَّتِي", "الذين": "الَّذِينَ", "هنا": "هُنَا", "هناك": "هُنَاكَ",
  "هذا": "هَذَا", "هذه": "هَذِهِ", "ذلك": "ذَلِكَ", "بعد": "بَعْدَ",
  "قبل": "قَبْلَ", "عند": "عِنْدَ", "مع": "مَعَ", "بين": "بَيْنَ",
  "فوق": "فَوْقَ", "تحت": "تَحْتَ", "أمام": "أَمَامَ", "خلف": "خَلْفَ",
  "حول": "حَوْلَ", "دون": "دُونَ", "غير": "غَيْر", "مثل": "مِثْل",
  "كل": "كُلّ", "بعض": "بَعْض", "أيضا": "أَيْضًا", "جدا": "جِدًّا",
  "شكرا": "شُكْرًا", "مرحبا": "مَرْحَبًا", "صباح": "صَبَاح", "مساء": "مَسَاء",
  "خير": "خَيْر", "سلام": "سَلَام", "يوم": "يَوْم", "اليوم": "اليَوْم",
};
const HAS_DIACRITICS = /[ً-ْٰ]/;

function runTashkeel() {
  const text = getText();
  if (!text.trim()) {
    toast("اكتب نصًا أولًا ليُشكَّل.");
    return;
  }
  const tokens = engine.tokenize(text);
  const suggestions = [];
  for (const token of tokens) {
    if (token.kind !== "arabic_word") continue;
    if (HAS_DIACRITICS.test(token.text)) continue;
    const vocalized = TASHKEEL_LEXICON[token.text];
    if (!vocalized) continue;
    const morphology = engine.analyze(token.text, 0.8)[0] ?? null;
    const morphologyNote = morphology?.lemma
      ? ` التحليل الصرفي الأرجح: «${morphology.lemma}».`
      : "";
    suggestions.push({
      rule_id: `TASHKEEL_${token.text}`,
      offset: token.start,
      length: token.end - token.start,
      replacements: [vocalized],
      message: `تشكيل مقترح: «${vocalized}»`,
      explanation: `تشكيل جزئي تجريبي لكلمة شائعة غير ملتبسة، عبر مُقطِّع النواة.${morphologyNote}`,
      category: "tashkeel",
      severity: "hint",
      autofix: true,
      confidence: 0.9,
      priority: 10,
    });
  }
  const others = matches.filter((m) => m.category !== "tashkeel");
  matches = resolveDiagnostics([...others, ...suggestions]);
  const visible = visibleOf(matches);
  observeAsync(renderOverlay(text, visible), "overlay rendering");
  renderSidebar(text, visible);
  updateFixAll(visible);
  stat.issues.textContent = String(visible.length);
  toast(
    suggestions.length
      ? `اقتُرح تشكيل ${suggestions.length} كلمة — مرّر فوقها أو طبّقها من القائمة.`
      : "لا كلمات مشمولة بالتشكيل الجزئي في هذا النص."
  );
}

/* ── Hover card ──────────────────────────────────────────────── */
let hideTimer = null;

function showCard(markElement) {
  const index = Number(markElement.dataset.i);
  const visible = visibleOf(matches);
  const match = visible[index];
  if (!match) return;
  activeMatchIndex = index;
  const markRect = markElement.getBoundingClientRect();

  $("hcRule").textContent = match.rule_id;
  const severity = $("hcSev");
  severity.textContent = SEVERITY_LABEL[match.severity] ?? match.severity;
  severity.className = `hc-sev sev-${match.severity}`;
  $("hcWrong").textContent = markElement.textContent;
  $("hcRight").textContent = match.replacements[0] ?? "—";
  $("hcMsg").textContent = match.message;
  const explanation = explanationFor(match);
  $("hcExplain").textContent = explanation
    ? `${explanation.reasoning} — ${explanation.whyItMatters}`
    : match.explanation ?? "";
  $("hcApply").style.display = match.replacements.length ? "" : "none";

  hoverCard.style.visibility = "hidden";
  hoverCard.hidden = false;
  requestAnimationFrame(() => {
    if (activeMatchIndex !== index) return;
    const cardRect = hoverCard.getBoundingClientRect();
    let top = markRect.bottom + 10;
    if (top + cardRect.height > window.innerHeight - 12) top = markRect.top - cardRect.height - 10;
    let left = markRect.left + markRect.width / 2 - cardRect.width / 2;
    left = Math.max(12, Math.min(left, window.innerWidth - cardRect.width - 12));
    hoverCard.style.top = `${Math.max(12, top)}px`;
    hoverCard.style.left = `${left}px`;
    hoverCard.style.visibility = "";
  });
}

function hideCard() {
  hoverCard.hidden = true;
  activeMatchIndex = -1;
}

function scheduleHide() {
  clearTimeout(hideTimer);
  hideTimer = setTimeout(hideCard, 260);
}

editor.addEventListener("mouseover", (event) => {
  const markElement = event.target.closest("mark.err");
  if (!markElement) return;
  clearTimeout(hideTimer);
  showCard(markElement);
});
editor.addEventListener("mouseout", (event) => {
  if (event.target.closest("mark.err")) scheduleHide();
});
hoverCard.addEventListener("mouseenter", () => clearTimeout(hideTimer));
hoverCard.addEventListener("mouseleave", scheduleHide);

$("hcApply").addEventListener("click", () => {
  const match = visibleOf(matches)[activeMatchIndex];
  if (match) applyMatch(match);
});
$("hcDismiss").addEventListener("click", () => {
  const match = visibleOf(matches)[activeMatchIndex];
  if (match) dismissMatch(match);
});
$("hcDisableRule").addEventListener("click", () => {
  const match = visibleOf(matches)[activeMatchIndex];
  if (!match) return;
  disabledRules.add(match.rule_id);
  hideCard();
  observeAsync(
    persistWritingPreferences().then(() => runCheck({ keepTashkeel: true })),
    "rule override persistence",
    "تعذر حفظ تعطيل القاعدة.",
  );
  toast(`عُطلت القاعدة ${match.rule_id} محليًا.`);
});

/* ── Sidebar interactions ────────────────────────────────────── */
function dismissMatch(match) {
  dismissed.add(`${match.rule_id}:${match.offset}`);
  observeAsync(runCheck({ keepTashkeel: true }), "document analysis");
}

function focusIssue(item) {
  const markElement = editorOverlay.querySelector(`mark.err[data-i="${item.dataset.i}"]`);
  if (!markElement) return;
  markElement.scrollIntoView({ block: "center", behavior: "smooth" });
  markElement.classList.add("lit");
  setTimeout(() => markElement.classList.remove("lit"), 1200);
  showCard(markElement);
  scheduleHide();
}

issuesList.addEventListener("click", (event) => {
  const actionButton = event.target.closest("button[data-action]");
  const visible = visibleOf(matches);
  if (actionButton) {
    const match = visible[Number(actionButton.dataset.i)];
    if (match && actionButton.dataset.action === "apply") applyMatch(match);
    if (match && actionButton.dataset.action === "dismiss") dismissMatch(match);
    return;
  }
  const item = event.target.closest(".issue");
  if (item) focusIssue(item);
});

issuesList.addEventListener("keydown", (event) => {
  if (!['Enter', ' '].includes(event.key) || event.target.closest("button")) return;
  const item = event.target.closest(".issue");
  if (!item) return;
  event.preventDefault();
  focusIssue(item);
});

$("filters").addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;
  sideFilter = chip.dataset.cat;
  for (const other of $("filters").children) {
    const selected = other === chip;
    other.classList.toggle("active", selected);
    other.setAttribute("aria-pressed", String(selected));
  }
  issuesList.scrollTop = 0;
  renderSidebar(getText(), visibleOf(matches));
  observeAsync(storage?.setSetting("sidebarFilter", sideFilter), "filter persistence");
});

$("toneChips").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-target]");
  if (!button || !writingIntelligence) return;
  try {
    const guidance = guidanceForTarget(writingIntelligence, button.dataset.target);
    toast(guidance.actions[0]);
  } catch (error) {
    console.warn("Tone guidance unavailable", error);
  }
});

$("btnLexicon").addEventListener("click", () => {
  lexiconWords.value = customWords.join("\n");
  renderDisabledRules();
  lexiconDialog.showModal();
});

disabledRulesList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-rule-id]");
  if (!button) return;
  disabledRules.delete(button.dataset.ruleId);
  renderDisabledRules();
});

$("btnResetPreferences").addEventListener("click", () => {
  customWords = [];
  disabledRules = new Set();
  lexiconWords.value = "";
  renderDisabledRules();
});

$("lexiconForm").addEventListener("submit", (event) => {
  if (event.submitter?.value !== "save") return;
  event.preventDefault();
  try {
    customWords = [...parseLexiconInput(lexiconWords.value)];
  } catch (error) {
    toast(error instanceof Error ? error.message : "تعذر قراءة المعجم.");
    return;
  }
  observeAsync(
    persistWritingPreferences().then(async () => {
      lexiconDialog.close("save");
      await runCheck({ keepTashkeel: true });
      toast(`حُفظ ${customWords.length} مصطلحًا و${disabledRules.size} تجاوزًا محليًا.`);
    }),
    "writing preferences persistence",
    "تعذر حفظ إعدادات الكتابة.",
  );
});

/* ── Toolbar wiring ──────────────────────────────────────────── */
const modeButtons = { all: $("btnCheck"), style: $("btnStyle"), msa: $("btnMsa") };

async function setMode(nextMode) {
  mode = nextMode;
  for (const [key, button] of Object.entries(modeButtons)) {
    const selected = key === nextMode;
    button.classList.toggle("active-mode", selected);
    button.setAttribute("aria-pressed", String(selected));
  }
  observeAsync(storage?.setSetting("mode", mode), "mode persistence");
  return runCheck({ keepTashkeel: true });
}

$("btnCheck").addEventListener("click", () => {
  observeAsync(
    setMode("all").then((visible) =>
      toast(visible.length ? `وُجدت ${visible.length} ملاحظة.` : "لا ملاحظات — النص سليم ✓"),
    ),
    "all-mode analysis",
    "تعذر إكمال التدقيق.",
  );
});
$("btnStyle").addEventListener("click", () => {
  observeAsync(
    setMode("style").then((visible) =>
      toast(visible.length ? `ملاحظات الأسلوب والنحو: ${visible.length}` : "أسلوبك سليم ✓"),
    ),
    "style-mode analysis",
    "تعذر إكمال تدقيق الأسلوب.",
  );
});
$("btnMsa").addEventListener("click", () => {
  observeAsync(
    setMode("msa").then((visible) =>
      toast(visible.length ? `ألفاظ عامية لها مقابل فصيح: ${visible.length}` : "لا ألفاظ عامية مرصودة ✓"),
    ),
    "MSA-mode analysis",
    "تعذر إكمال تدقيق الفصحى.",
  );
});
$("btnTashkeel").addEventListener("click", runTashkeel);
$("btnFixAll").addEventListener("click", applyAll);

$("btnCopy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(getText());
    toast("نُسخ النص ✓");
  } catch {
    toast("تعذر النسخ — انسخ يدويًا.");
  }
});
$("btnClear").addEventListener("click", () => {
  editor.textContent = "";
  dismissed = new Set();
  scheduleDocumentSave("");
  observeAsync(runCheck(), "document analysis");
  editor.focus();
});

/* ── Live checking while typing ──────────────────────────────── */
let debounceTimer = null;
let saveTimer = null;

function scheduleDocumentSave(content = getText()) {
  if (!storage) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    void storage.putDocument({
      id: "local-default",
      title: documentTitle,
      content,
      html: sanitizedEditorHtml(),
    }).catch((error) => {
      console.warn("Local document save failed", error);
    });
  }, 120);
}

editor.addEventListener("input", () => {
  if (composing) return;
  scheduleDocumentSave(getText());
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => observeAsync(runCheck(), "document analysis"), 280);
});
editor.addEventListener("compositionstart", () => (composing = true));
editor.addEventListener("compositionend", () => {
  composing = false;
  scheduleDocumentSave(getText());
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => observeAsync(runCheck(), "document analysis"), 280);
});

let editorScrollFrame = null;
editor.addEventListener("scroll", () => {
  if (editorScrollFrame !== null) return;
  editorScrollFrame = requestAnimationFrame(() => {
    editorScrollFrame = null;
    editorOverlay.style.transform = `translate3d(0, ${-editor.scrollTop}px, 0)`;
  });
}, { passive: true });

/* Rich editor paste policy: preserve safe semantic formatting, never scripts or inline styles. */
editor.addEventListener("paste", (event) => {
  event.preventDefault();
  const html = event.clipboardData?.getData("text/html");
  const text = event.clipboardData?.getData("text/plain") ?? "";
  const fragment = html ? sanitizeEditorFragment(html) : document.createTextNode(text);
  const selection = window.getSelection();
  if (!selection?.rangeCount || !editor.contains(selection.anchorNode)) {
    editor.append(fragment);
  } else {
    const range = selection.getRangeAt(0);
    range.deleteContents();
    range.insertNode(fragment);
    selection.collapseToEnd();
  }
  scheduleDocumentSave();
  observeAsync(runCheck(), "document analysis");
});

function insertAtCaret(insertText, explicitOffset = null) {
  const offset = explicitOffset ?? caretOffset();
  const text = getText();
  const position = offset === null ? text.length : offset;
  const next = text.slice(0, position) + insertText + text.slice(position);
  if (!replaceEditorTextSpan(position, position, insertText)) {
    setEditorText(next);
    setCaret(position + insertText.length);
  }
  scheduleDocumentSave(next);
  observeAsync(runCheck(), "document analysis");
}

/* ── Voice input (Web Speech API) ────────────────────────────── */
const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
const micButton = $("btnMic");
let recognition = null;
let listening = false;

if (!SpeechRecognitionImpl) {
  micButton.addEventListener("click", () =>
    toast("متصفحك لا يدعم الإملاء الصوتي — جرّب Chrome أو Edge.")
  );
} else {
  micButton.addEventListener("click", () => (listening ? stopDictation() : startDictation()));
}

function startDictation() {
  recognition = new SpeechRecognitionImpl();
  recognition.lang = $("micLang").value;
  recognition.continuous = true;
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    listening = true;
    micButton.classList.add("recording");
    micButton.setAttribute("aria-label", "إيقاف الإملاء الصوتي");
    $("footHint").textContent = "🎙 يجري الاستماع… تحدث بوضوح، واضغط الزر مجددًا للإيقاف.";
  };
  recognition.onresult = (event) => {
    let transcript = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) transcript += event.results[i][0].transcript;
    }
    transcript = transcript.trim();
    if (!transcript) return;
    const text = getText();
    const glue = text && !/\s$/.test(text) ? " " : "";
    // Append through the rich-text offset bridge so dictation does not flatten
    // headings, emphasis, lists, or other semantic formatting in the document.
    insertAtCaret(`${glue}${transcript}`, text.length);
  };
  recognition.onerror = (event) => {
    if (event.error === "not-allowed") toast("رُفض الوصول إلى الميكروفون — فعّله من إعدادات المتصفح.");
    else if (event.error !== "no-speech") toast(`خطأ في الإملاء الصوتي: ${event.error}`);
    stopDictation();
  };
  recognition.onend = () => {
    if (listening) {
      try { recognition.start(); } catch { stopDictation(); } // keep continuous sessions alive
    }
  };

  try {
    recognition.start();
  } catch {
    toast("تعذر بدء الإملاء الصوتي.");
  }
}

function stopDictation() {
  listening = false;
  micButton.classList.remove("recording");
  micButton.setAttribute("aria-label", "بدء الإملاء الصوتي");
  $("footHint").textContent = "يُدقَّق النص لحظيًا أثناء الكتابة، وكل شيء يجري محليًا في جهازك.";
  try { recognition?.stop(); } catch { /* already stopped */ }
  recognition = null;
}

$("micLang").addEventListener("change", () => {
  observeAsync(storage?.setSetting("microphoneLanguage", $("micLang").value), "microphone preference persistence");
});

/* ── Toast ───────────────────────────────────────────────────── */
let toastTimer = null;
function toast(message) {
  toastBox.textContent = message;
  toastBox.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toastBox.hidden = true), 2600);
}


/* ── Gold Master product capabilities ───────────────────────── */
assertCapabilityParity(GOLD_CAPABILITIES);

themeController = new ThemeController({ storage });
await themeController.initialize();
$("themeSelect").value = themeController.preference;
$("themeSelect").addEventListener("change", (event) => {
  themeController.setPreference(event.target.value);
  toast(`تم تطبيق المظهر: ${event.target.selectedOptions[0]?.textContent ?? event.target.value}`);
});
globalThis.addEventListener("pagehide", () => themeController?.dispose(), { once: true });

for (const button of document.querySelectorAll("[data-close]")) {
  button.addEventListener("click", () => $(button.dataset.close)?.close());
}
for (const dialog of document.querySelectorAll("dialog")) {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

function selectedEditorRange() {
  const selection = window.getSelection();
  if (!selection?.rangeCount) return null;
  const range = selection.getRangeAt(0);
  if (range.collapsed || !editor.contains(range.commonAncestorContainer)) return null;
  return range.cloneRange();
}

function renderRewriteModes() {
  const container = $("rewriteModes");
  container.replaceChildren(...Object.entries(REWRITE_MODES).map(([id, metadata]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tb-btn";
    button.dataset.mode = id;
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(id === selectedRewriteMode));
    button.textContent = metadata.label;
    button.title = metadata.description;
    return button;
  }));
}

let rewriteContext = null;
async function renderRewriteCandidates() {
  const source = rewriteContext?.sourceText ?? getText();
  const result = await paraphraseText(source, selectedRewriteMode, {
    alternatives: 3,
    dialectConversions: rewriteContext?.range ? [] : (writingIntelligence?.dialect?.conversions ?? []),
  });
  const container = $("rewriteCandidates");
  container.replaceChildren();
  if (!result.candidates.length) {
    const empty = document.createElement("p");
    empty.className = "muted-note";
    empty.textContent = "لا توجد إعادة صياغة آمنة لهذا المقطع في الوضع المختار.";
    container.append(empty);
    return;
  }
  for (const candidate of result.candidates) {
    const card = document.createElement("article");
    card.className = "rewrite-card";
    const header = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = candidate.label;
    const meta = document.createElement("span");
    meta.className = "rewrite-meta";
    meta.textContent = `حفظ المعنى ${Math.round(candidate.meaningPreservation * 100)}% · ثقة ${Math.round(candidate.confidence * 100)}%`;
    header.append(title, meta);
    const text = document.createElement("p");
    text.textContent = candidate.text;
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const apply = document.createElement("button");
    apply.type = "button"; apply.className = "tb-btn primary"; apply.textContent = "تطبيق";
    apply.addEventListener("click", () => {
      if (rewriteContext?.range && editor.contains(rewriteContext.range.commonAncestorContainer)) {
        const range = rewriteContext.range;
        range.deleteContents();
        const node = document.createTextNode(candidate.text);
        range.insertNode(node);
        range.setStartAfter(node); range.collapse(true);
        const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
      } else {
        setEditorText(candidate.text);
      }
      $("rewriteDialog").close();
      scheduleDocumentSave();
      observeAsync(runCheck(), "rewrite analysis");
      toast("طُبقت إعادة الصياغة محليًا ✓");
    });
    const copy = document.createElement("button");
    copy.type = "button"; copy.className = "tb-btn ghost"; copy.textContent = "نسخ";
    copy.addEventListener("click", () => observeAsync(navigator.clipboard.writeText(candidate.text).then(() => toast("نُسخ البديل ✓")), "rewrite copy", "تعذر نسخ البديل."));
    actions.append(apply, copy);
    card.append(header, text, actions);
    container.append(card);
  }
}

$("btnRewrite").addEventListener("click", () => {
  const range = selectedEditorRange();
  const selected = range?.toString().trim();
  rewriteContext = { range, sourceText: selected || getText() };
  if (!rewriteContext.sourceText.trim()) { toast("اكتب نصًا أو حدّد جملة أولًا."); return; }
  renderRewriteModes();
  $("rewriteDialog").showModal();
  observeAsync(renderRewriteCandidates(), "native rewrite", "تعذر إنشاء بدائل إعادة الصياغة.");
});
$("rewriteModes").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-mode]");
  if (!button) return;
  selectedRewriteMode = button.dataset.mode;
  renderRewriteModes();
  observeAsync(renderRewriteCandidates(), "native rewrite", "تعذر إنشاء بدائل إعادة الصياغة.");
});

function populateTemplateFields() {
  const template = templateById($("templateSelect").value) ?? SMART_TEMPLATES[0];
  const tones = $("templateTone");
  tones.replaceChildren(...template.tones.map((tone) => {
    const option = document.createElement("option"); option.value = tone; option.textContent = TONE_LABELS[tone] ?? tone; return option;
  }));
  const fields = $("templateFields");
  fields.replaceChildren(...template.fields.map((field) => {
    const label = document.createElement("label");
    label.textContent = `${field.label}${field.required ? " *" : ""}`;
    const input = document.createElement(field.multiline ? "textarea" : "input");
    input.name = field.id; input.maxLength = field.maxLength; input.required = field.required;
    if (field.multiline) input.rows = 3;
    input.addEventListener("input", updateTemplatePreview);
    label.append(input); return label;
  }));
  updateTemplatePreview();
}

function updateTemplatePreview() {
  const values = Object.fromEntries(new FormData($("templateFields")).entries());
  try {
    const generated = generateFromTemplate($("templateSelect").value, values, { tone: $("templateTone").value || undefined });
    generatedTemplateText = generated.text;
    $("templatePreview").textContent = generated.text;
    $("templateMissing").textContent = generated.missingFields.length
      ? `أكمل الحقول المطلوبة: ${generated.missingFields.join("، ")}`
      : "القالب مكتمل ولا يحتوي معلومات غير مدخلة.";
  } catch (error) {
    generatedTemplateText = "";
    $("templatePreview").textContent = error instanceof Error ? error.message : "تعذر إنشاء القالب";
  }
}

const templateSelect = $("templateSelect");
templateSelect.replaceChildren(...SMART_TEMPLATES.map((template) => {
  const option = document.createElement("option"); option.value = template.id; option.textContent = template.title; option.title = template.description; return option;
}));
templateSelect.addEventListener("change", populateTemplateFields);
$("templateTone").addEventListener("change", updateTemplatePreview);
$("btnTemplates").addEventListener("click", () => { templateInsertOffset = caretOffset(); populateTemplateFields(); $("templateDialog").showModal(); });
$("btnTemplateInsert").addEventListener("click", () => {
  if (!generatedTemplateText) return;
  insertAtCaret(`${getText().trim() ? "\n\n" : ""}${generatedTemplateText}`, templateInsertOffset);
  $("templateDialog").close(); toast("أُدرج القالب في المستند ✓");
});
$("btnTemplateReplace").addEventListener("click", () => {
  if (!generatedTemplateText) return;
  setEditorText(generatedTemplateText); scheduleDocumentSave(); observeAsync(runCheck(), "template analysis");
  $("templateDialog").close(); toast("أُنشئ المستند من القالب ✓");
});

function formatDuration(seconds) {
  if (seconds < 60) return `${seconds} ث`;
  const minutes = Math.floor(seconds / 60); const remainder = seconds % 60;
  return remainder ? `${minutes} د ${remainder} ث` : `${minutes} د`;
}
function signed(value, suffix = "") {
  const rounded = Math.round(value * 10) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded}${suffix}`;
}
async function renderAnalyticsDashboard({ saveSnapshot = true } = {}) {
  const metrics = advancedAnalytics(getText(), writingIntelligence);
  currentAnalytics = metrics;
  const history = storage ? await storage.listAnalyticsHistory("local-default", { limit: 30 }).catch(() => []) : [];
  const trend = analyticsTrend(history, metrics);
  $("gaClarity").textContent = `${Math.round(metrics.clarityScore)}/100`;
  $("gaEngagement").textContent = `${Math.round(metrics.engagementScore)}/100`;
  $("gaRichness").textContent = `${Math.round(metrics.vocabularyRichness)}%`;
  $("gaComplexity").textContent = `${Math.round(metrics.complexityScore)}/100`;
  $("gaReading").textContent = formatDuration(metrics.estimatedReadingSeconds);
  $("gaSpeaking").textContent = `إلقاء: ${formatDuration(metrics.estimatedSpeakingSeconds)}`;
  $("gaToneBalance").textContent = `${Math.round(metrics.toneBalance.balanceScore)}/100`;
  $("gaToneDominant").textContent = `السائدة: ${TONE_LABELS[metrics.toneBalance.dominant] ?? metrics.toneBalance.dominant}`;
  $("gaCounts").textContent = `${metrics.words} كلمة · ${metrics.sentences} جملة · ${metrics.paragraphs} فقرة`;
  $("gaClarityTrend").textContent = trend.hasBaseline ? `من القياس السابق ${signed(trend.clarityDelta)}` : "بداية خط القياس";
  $("gaEngagementTrend").textContent = trend.hasBaseline ? `من القياس السابق ${signed(trend.engagementDelta)}` : "بداية خط القياس";
  $("gaRichnessTrend").textContent = trend.hasBaseline ? `من القياس السابق ${signed(trend.richnessDelta, "%")}` : "بداية خط القياس";
  const heatmap = $("sentenceHeatmap");
  heatmap.replaceChildren(...metrics.sentenceHeatmap.map((item) => {
    const card = document.createElement("article"); card.className = "heat-sentence"; card.dataset.heat = item.heat;
    const header = document.createElement("header"); header.innerHTML = `<span>جملة ${item.index + 1}</span><span>وضوح ${Math.round(item.clarityScore)} · ${item.words} كلمة</span>`;
    const body = document.createElement("p"); body.textContent = item.text;
    card.append(header, body); return card;
  }));
  if (!metrics.sentenceHeatmap.length) { const empty = document.createElement("p"); empty.className = "muted-note"; empty.textContent = "اكتب نصًا لعرض خريطة الجمل."; heatmap.append(empty); }
  if (saveSnapshot && storage && Date.now() - lastAnalyticsSnapshotAt > 30_000 && metrics.words) {
    lastAnalyticsSnapshotAt = Date.now();
    observeAsync(storage.appendAnalyticsSnapshot("local-default", metrics), "analytics snapshot");
  }
  return metrics;
}
$("btnAnalytics").addEventListener("click", () => observeAsync(renderAnalyticsDashboard().then(() => $("analyticsDialog").showModal()), "analytics dashboard", "تعذر إنشاء التحليلات."));

async function importSelectedDocument(file) {
  const imported = await importDocument(file);
  documentTitle = imported.title || documentTitle;
  setEditorHtml(imported.html || markdownToHtml(imported.text));
  dismissed = new Set(); scheduleDocumentSave(); await runCheck();
  toast(`استُورد ${file.name}${imported.warning ? " مع ملاحظة حول تنسيق PDF" : ""} ✓`);
}

$("btnImport").addEventListener("click", () => {
  if (!nativeDocumentDialogsAvailable()) {
    $("documentFile").click();
    return;
  }
  observeAsync((async () => {
    const selected = await pickNativeDocument();
    if (!selected) return;
    await importSelectedDocument(selected.file);
  })(), "native document import", "تعذر استيراد المستند؛ تحقق من الصيغة أو طبقة النص.");
});
$("documentFile").addEventListener("change", (event) => {
  const file = event.target.files?.[0]; if (!file) return;
  observeAsync((async () => {
    await importSelectedDocument(file);
    event.target.value = "";
  })(), "document import", "تعذر استيراد المستند؛ تحقق من الصيغة أو طبقة النص.");
});
$("btnExport").addEventListener("click", () => { $("documentTitle").value = documentTitle; $("exportDialog").showModal(); });
$("exportDialog").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-export]"); if (!button) return;
  observeAsync((async () => {
    const format = button.dataset.export;
    documentTitle = $("documentTitle").value.trim() || "مستند-ضاد";
    const output = exportDocument({ format, text: getText(), html: sanitizedEditorHtml(), title: documentTitle });
    if (output.blob) {
      if (nativeDocumentDialogsAvailable()) {
        const saved = await saveNativeDocument(output.blob, output.filename, format);
        if (!saved) return;
      } else {
        downloadBlob(output.blob, output.filename);
      }
    }
    scheduleDocumentSave(); $("exportDialog").close();
    toast(format === "pdf" ? "فُتح مربع الطباعة الأصلي لحفظ PDF ✓" : `جُهز ${output.filename} ✓`);
  })(), "document export", "تعذر تصدير المستند.");
});

/* ── Restore local state, otherwise boot with a demo paragraph ─ */
const demoText =
  "انا ذهبت الى المدرسه قبل ثلاثة سنوات، لاكن الطريق كان طويلا. شلونك اليوم؟ سأعود انشاء الله.";
if (storage) {
  const [savedDocument, savedMode, savedFilter, savedMicrophoneLanguage, savedDictionary, savedDisabledRules] = await Promise.all([
    storage.getDocument("local-default"),
    storage.getSetting("mode"),
    storage.getSetting("sidebarFilter"),
    storage.getSetting("microphoneLanguage"),
    storage.getDictionary("personal"),
    storage.getSetting("disabledRules"),
  ]);
  documentTitle = savedDocument?.title || "مستند-ضاد";
  if (savedDocument?.html) setEditorHtml(savedDocument.html);
  else editor.textContent = savedDocument?.content ?? demoText;
  if (MODES[savedMode]) mode = savedMode;
  if (["all", ...Object.keys(CATEGORY_LABEL)].includes(savedFilter)) sideFilter = savedFilter;
  if ([...$("micLang").options].some((option) => option.value === savedMicrophoneLanguage)) {
    $("micLang").value = savedMicrophoneLanguage;
  }
  customWords = Array.isArray(savedDictionary?.words) ? [...savedDictionary.words] : [];
  disabledRules = new Set(Array.isArray(savedDisabledRules) ? savedDisabledRules : []);
} else {
  editor.textContent = demoText;
}
for (const [key, button] of Object.entries(modeButtons)) {
  const selected = key === mode;
  button.classList.toggle("active-mode", selected);
  button.setAttribute("aria-pressed", String(selected));
}
for (const chip of $("filters").children) {
  const selected = chip.dataset.cat === sideFilter;
  chip.classList.toggle("active", selected);
  chip.setAttribute("aria-pressed", String(selected));
}
await runCheck();

/* Hook for automated verification (browser_proof.mjs). */
window.__dhad = {
  engine,
  neural: neuralState,
  neuralClient,
  analysisClient,
  storage,
  outboxRecovery,
  performance: { longTasks },
  writingIntelligence: () => writingIntelligence,
  preferences: () => ({ customWords: [...customWords], disabledRules: [...disabledRules] }),
  capabilities: GOLD_CAPABILITIES,
  rewrite: (rewriteMode = "formal") => paraphraseText(getText(), rewriteMode, { dialectConversions: writingIntelligence?.dialect?.conversions ?? [] }),
  analytics: () => advancedAnalytics(getText(), writingIntelligence),
  render: () => runCheck(),
};
