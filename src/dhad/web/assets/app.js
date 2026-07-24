"use strict";

const SAMPLE_TEXT = "عايزين نلعب، وفي هذا الوقت الراهن قام الطالب بكتابة ثلاثة كتب مفيدة. ذهبت الى المدرسه ثم عاد الطالب.";
const API = Object.freeze({
  health: "/api/health",
  check: "/api/v1/check",
  style: "/api/v1/style",
  dialect: "/api/v1/dialect",
  diacritize: "/api/v1/diacritize",
});

const state = {
  text: "",
  matches: [],
  style: null,
  dialect: null,
  diacritics: null,
  filter: "all",
  requestId: 0,
  debounceTimer: null,
  toastTimer: null,
};

const elements = {};

function byId(id) {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing required element: ${id}`);
  return element;
}

function cacheElements() {
  [
    "editor", "analysisPreview", "connectionStatus", "themeToggle", "styleProfile",
    "sampleButton", "clearButton", "analyzeButton", "wordCount", "characterCount",
    "issueCount", "issuesList", "styleSummary", "styleList", "dialectSummary",
    "diacriticsMode", "diacritizeButton", "diacriticsOutput", "busyIndicator",
    "appVersion", "toast", "issueFilters",
  ].forEach((id) => { elements[id] = byId(id); });
}

async function fetchJson(endpoint, payload, signal) {
  const response = await fetch(endpoint, {
    method: payload === undefined ? "GET" : "POST",
    headers: payload === undefined ? { Accept: "application/json" } : {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail ? JSON.stringify(body.detail) : detail;
    } catch (_) {
      // The status line remains the most useful fallback.
    }
    throw new Error(detail);
  }
  return response.json();
}

function setConnection(stateName, label) {
  elements.connectionStatus.dataset.state = stateName;
  elements.connectionStatus.lastElementChild.textContent = label;
}

function setBusy(busy) {
  elements.busyIndicator.hidden = !busy;
  elements.analyzeButton.disabled = busy;
  elements.diacritizeButton.disabled = busy;
}

function showToast(message, isError = false) {
  clearTimeout(state.toastTimer);
  elements.toast.textContent = message;
  elements.toast.dataset.state = isError ? "error" : "ok";
  elements.toast.hidden = false;
  state.toastTimer = setTimeout(() => { elements.toast.hidden = true; }, 3500);
}

function updateCounts() {
  const text = elements.editor.value;
  const words = (text.match(/[\p{L}\p{N}]+/gu) || []).length;
  elements.wordCount.textContent = String(words);
  elements.characterCount.textContent = String(text.length);
  elements.issueCount.textContent = String(state.matches.length);
}

function sortedNonOverlapping(matches) {
  const sorted = [...matches].sort((a, b) => a.offset - b.offset || b.length - a.length || b.priority - a.priority);
  const accepted = [];
  let end = -1;
  for (const match of sorted) {
    if (match.offset < end || match.length <= 0) continue;
    accepted.push(match);
    end = match.offset + match.length;
  }
  return accepted;
}

function renderPreview() {
  const text = elements.editor.value;
  elements.analysisPreview.replaceChildren();
  if (!text) return;
  const fragment = document.createDocumentFragment();
  let cursor = 0;
  for (const match of sortedNonOverlapping(state.matches)) {
    const start = Math.max(cursor, Math.min(text.length, match.offset));
    const end = Math.max(start, Math.min(text.length, match.offset + match.length));
    fragment.append(document.createTextNode(text.slice(cursor, start)));
    const mark = document.createElement("span");
    mark.className = "issue-mark";
    mark.dataset.category = match.category;
    mark.title = match.message;
    mark.textContent = text.slice(start, end);
    fragment.append(mark);
    cursor = end;
  }
  fragment.append(document.createTextNode(text.slice(cursor)));
  elements.analysisPreview.append(fragment);
}

function categoryName(category) {
  return {
    spelling: "إملاء", grammar: "نحو", punctuation: "ترقيم", style: "أسلوب",
    dialect: "لهجة", neural_suggestion: "اقتراح سياقي", semantics: "دلالة",
    consistency: "اتساق", diacritics: "تشكيل",
  }[category] || category;
}

function applyReplacement(match, replacement) {
  const text = elements.editor.value;
  const start = Math.max(0, Math.min(text.length, match.offset));
  const end = Math.max(start, Math.min(text.length, match.offset + match.length));
  elements.editor.value = text.slice(0, start) + replacement + text.slice(end);
  elements.editor.focus();
  const caret = start + replacement.length;
  elements.editor.setSelectionRange(caret, caret);
  scheduleAnalysis(true);
  showToast(match.autofix ? "طُبّق التصحيح الآمن." : "طُبّق الاقتراح بعد موافقتك الصريحة.");
}

function issueCard(match) {
  const card = document.createElement("article");
  card.className = "result-card";
  card.dataset.category = match.category;

  const title = document.createElement("div");
  title.className = "result-title";
  const strong = document.createElement("strong");
  strong.textContent = `${categoryName(match.category)} — ${match.message}`;
  const safety = document.createElement("span");
  safety.className = `safety-label${match.autofix ? " safe" : ""}`;
  safety.textContent = match.autofix ? "تصحيح آمن" : "يتطلب موافقة";
  title.append(strong, safety);

  const fragment = document.createElement("div");
  fragment.className = "result-fragment";
  fragment.textContent = `«${elements.editor.value.slice(match.offset, match.offset + match.length)}»`;

  const explanation = document.createElement("p");
  explanation.className = "result-explanation";
  explanation.textContent = match.explanation || "اقتراح قابل للمراجعة.";

  const meta = document.createElement("div");
  meta.className = "result-meta";
  meta.textContent = `${match.rule_id} · ثقة ${Math.round(match.confidence * 100)}%`;

  const actions = document.createElement("div");
  actions.className = "result-actions";
  for (const replacement of match.replacements.slice(0, 3)) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `button button-small ${match.autofix ? "button-primary" : "button-ghost"}`;
    button.textContent = replacement;
    button.addEventListener("click", () => applyReplacement(match, replacement));
    actions.append(button);
  }
  card.append(title, fragment, explanation, meta);
  if (actions.childElementCount) card.append(actions);
  return card;
}

function renderIssues() {
  elements.issuesList.replaceChildren();
  const matches = state.filter === "all"
    ? state.matches
    : state.matches.filter((item) => item.category === state.filter);
  if (!matches.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = state.text ? "لا توجد ملاحظات ضمن هذا التصنيف." : "اكتب نصًا لبدء التحليل.";
    elements.issuesList.append(empty);
    return;
  }
  matches.forEach((match) => elements.issuesList.append(issueCard(match)));
}

function summaryCard(label, value) {
  const card = document.createElement("div");
  card.className = "summary-card";
  const caption = document.createElement("span");
  caption.textContent = label;
  const strong = document.createElement("strong");
  strong.textContent = value;
  card.append(caption, strong);
  return card;
}

function renderStyle() {
  elements.styleSummary.replaceChildren();
  elements.styleList.replaceChildren();
  if (!state.style) {
    elements.styleList.innerHTML = '<div class="empty-state">لا يوجد تحليل أسلوبي بعد.</div>';
    return;
  }
  const readability = state.style.readability;
  elements.styleSummary.append(
    summaryCard("النبرة", state.style.tone.primary),
    summaryCard("وضوح النص", `${Math.round(readability.clarity_score)} / 100`),
    summaryCard("متوسط طول الجملة", readability.average_words_per_sentence.toFixed(1)),
    summaryCard("الكثافة المعجمية", `${Math.round(readability.lexical_density * 100)}%`),
  );
  if (!state.style.matches.length) {
    elements.styleList.innerHTML = '<div class="empty-state">لا توجد اقتراحات أسلوبية لهذا الملف.</div>';
    return;
  }
  state.style.matches.forEach((match) => elements.styleList.append(issueCard(match)));
}

function renderDialect() {
  elements.dialectSummary.replaceChildren();
  if (!state.dialect) {
    elements.dialectSummary.innerHTML = '<div class="empty-state">لا يوجد تحليل لهجي بعد.</div>';
    return;
  }
  const box = document.createElement("div");
  box.className = "dialect-box";
  const heading = document.createElement("h3");
  heading.textContent = `اللهجة المرجحة: ${state.dialect.primary}`;
  const confidence = document.createElement("p");
  confidence.className = "result-meta";
  confidence.textContent = `الثقة ${Math.round(state.dialect.confidence * 100)}% · ${state.dialect.conversions.length} تحويل مقترح`;
  const converted = document.createElement("p");
  converted.className = "converted-text";
  converted.textContent = state.dialect.converted_text || state.text;
  box.append(heading, confidence, converted);
  if (state.dialect.converted_text && state.dialect.converted_text !== state.text) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button button-ghost";
    button.textContent = "استبدال النص بالفصحى";
    button.addEventListener("click", () => {
      elements.editor.value = state.dialect.converted_text;
      scheduleAnalysis(true);
      showToast("طُبّق التحويل إلى الفصحى بموافقتك.");
    });
    box.append(button);
  }
  elements.dialectSummary.append(box);
}

function renderDiacritics() {
  elements.diacriticsOutput.textContent = state.diacritics?.text || "اختر مستوى التشكيل ثم اضغط «تشكيل النص».";
  if (state.diacritics?.text) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button button-ghost";
    button.textContent = "نسخ النص المشكول";
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(state.diacritics.text);
      showToast("نُسخ النص المشكول.");
    });
    elements.diacriticsOutput.append(document.createElement("br"), button);
  }
}

function renderAll() {
  updateCounts();
  renderPreview();
  renderIssues();
  renderStyle();
  renderDialect();
  renderDiacritics();
}

async function analyzeAll() {
  const text = elements.editor.value;
  state.text = text;
  updateCounts();
  if (!text.trim()) {
    state.matches = [];
    state.style = null;
    state.dialect = null;
    state.diacritics = null;
    renderAll();
    return;
  }
  const requestId = ++state.requestId;
  const controller = new AbortController();
  setBusy(true);
  try {
    const [check, style, dialect] = await Promise.all([
      fetchJson(API.check, { text, profiles: ["default"], disabled_rules: [], disabled_categories: [] }, controller.signal),
      fetchJson(API.style, { text, profile: elements.styleProfile.value }, controller.signal),
      fetchJson(API.dialect, { text }, controller.signal),
    ]);
    if (requestId !== state.requestId) return;
    state.matches = check.matches;
    state.style = style;
    state.dialect = dialect;
    setConnection("online", `متصل · v${check.version}`);
    elements.appVersion.textContent = check.version;
    renderAll();
  } catch (error) {
    if (requestId !== state.requestId || error.name === "AbortError") return;
    setConnection("offline", "تعذر الاتصال");
    showToast(`تعذر تحليل النص: ${error.message}`, true);
  } finally {
    if (requestId === state.requestId) setBusy(false);
  }
}

function scheduleAnalysis(immediate = false) {
  clearTimeout(state.debounceTimer);
  updateCounts();
  state.debounceTimer = setTimeout(analyzeAll, immediate ? 0 : 550);
}

async function runDiacritization() {
  const text = elements.editor.value;
  if (!text.trim()) {
    showToast("اكتب نصًا أولًا.", true);
    return;
  }
  setBusy(true);
  try {
    state.diacritics = await fetchJson(API.diacritize, {
      text,
      mode: elements.diacriticsMode.value,
      neural_refine: true,
    });
    renderDiacritics();
  } catch (error) {
    showToast(`تعذر تشكيل النص: ${error.message}`, true);
  } finally {
    setBusy(false);
  }
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    const active = panel.dataset.panel === name;
    panel.classList.toggle("is-active", active);
    panel.hidden = !active;
  });
}

function bindEvents() {
  elements.editor.addEventListener("input", () => scheduleAnalysis(false));
  elements.analyzeButton.addEventListener("click", () => scheduleAnalysis(true));
  elements.diacritizeButton.addEventListener("click", runDiacritization);
  elements.styleProfile.addEventListener("change", () => scheduleAnalysis(true));
  elements.sampleButton.addEventListener("click", () => {
    elements.editor.value = SAMPLE_TEXT;
    scheduleAnalysis(true);
  });
  elements.clearButton.addEventListener("click", () => {
    elements.editor.value = "";
    scheduleAnalysis(true);
    elements.editor.focus();
  });
  elements.themeToggle.addEventListener("click", () => {
    const root = document.documentElement;
    const next = root.dataset.theme === "light" ? "dark" : "light";
    root.dataset.theme = next;
    localStorage.setItem("dhad-theme", next);
  });
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));
  elements.issueFilters.addEventListener("click", (event) => {
    const button = event.target.closest("[data-category]");
    if (!button) return;
    state.filter = button.dataset.category;
    elements.issueFilters.querySelectorAll(".filter-chip").forEach((chip) => chip.classList.toggle("is-active", chip === button));
    renderIssues();
  });
}

async function initialize() {
  cacheElements();
  const savedTheme = localStorage.getItem("dhad-theme");
  if (savedTheme === "light" || savedTheme === "dark") document.documentElement.dataset.theme = savedTheme;
  bindEvents();
  renderAll();
  try {
    const health = await fetchJson(API.health);
    setConnection("online", `متصل · v${health.version}`);
    elements.appVersion.textContent = health.version;
  } catch (error) {
    setConnection("offline", "الخادم غير متاح");
  }
  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("/service-worker.js").catch(() => undefined);
  }
  elements.editor.focus();
}

document.addEventListener("DOMContentLoaded", initialize);
