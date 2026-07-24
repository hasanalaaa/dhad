import { analyzeText, isTauriEnvironment, paraphraseText } from "./js/desktop-adapter.js";

const $ = (id) => document.getElementById(id);
const textBox = $("quickText");
const resultBody = $("resultBody");
const resultTitle = $("resultTitle");
const resultMeta = $("resultMeta");
const resultPanel = document.querySelector(".result-panel");
const miniShell = document.querySelector(".mini-shell");
const copyButton = $("btnCopyCurrent");
const autoHide = $("autoHide");
const characterCount = $("characterCount");
const performanceStatus = $("performanceStatus");
const AUTO_HIDE_KEY = "dhad.desktop.mini.autoHide";
let currentResultText = "";
let analysisTimer = 0;
let autoHideTimer = 0;
let operationSequence = 0;
let isComposing = false;

function tauriRoot() {
  return globalThis.window?.__TAURI__ ?? globalThis.__TAURI__ ?? null;
}

async function invoke(command, request) {
  const fn = tauriRoot()?.core?.invoke;
  if (typeof fn !== "function") return null;
  return fn(command, request === undefined ? undefined : { request });
}

function setBusy(value, title = "جارٍ التنفيذ…") {
  resultPanel.setAttribute("aria-busy", String(value));
  miniShell?.classList.toggle("is-busy", value);
  $("btnCheck").disabled = value;
  $("btnRewrite").disabled = value;
  if (value) {
    resultTitle.textContent = title;
    resultMeta.textContent = "المعالجة محلية";
    performanceStatus.textContent = "تنفيذ خارج خيط الواجهة";
  }
}

function updateCharacterCount() {
  const count = [...textBox.value].length;
  characterCount.textContent = `${count.toLocaleString("ar-IQ")} حرف`;
}

function focusQuickText({ select = false } = {}) {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    textBox.focus({ preventScroll: true });
    if (select && textBox.value) textBox.select();
  }));
}

function emptyState(message) {
  resultBody.innerHTML = "";
  const wrapper = document.createElement("div");
  wrapper.className = "empty-result";
  const mark = document.createElement("span"); mark.textContent = "ض";
  const paragraph = document.createElement("p"); paragraph.textContent = message;
  wrapper.append(mark, paragraph); resultBody.append(wrapper);
}

function showError(error) {
  currentResultText = "";
  copyButton.disabled = true;
  resultTitle.textContent = "تعذر التنفيذ";
  resultMeta.textContent = "راجع النص وأعد المحاولة";
  resultBody.innerHTML = "";
  const card = document.createElement("div");
  card.className = "issue-card error-card";
  card.textContent = error instanceof Error ? error.message : String(error);
  resultBody.append(card);
}

function codePointToCodeUnit(text, offset) {
  if (!Number.isFinite(offset) || offset <= 0) return 0;
  let points = 0;
  let units = 0;
  for (const character of text) {
    if (points >= offset) break;
    units += character.length;
    points += 1;
  }
  return units;
}

function applyIssue(issue) {
  const source = textBox.value;
  const replacement = issue?.replacements?.[0];
  if (typeof replacement !== "string") return;
  const start = codePointToCodeUnit(source, Number(issue.offset) || 0);
  const end = codePointToCodeUnit(source, (Number(issue.offset) || 0) + (Number(issue.length) || 0));
  textBox.value = `${source.slice(0, start)}${replacement}${source.slice(end)}`;
  textBox.focus();
  queueCheck(80);
}

function issueTitle(issue) {
  return issue?.message || issue?.description || issue?.rule_id || issue?.ruleId || "ملاحظة لغوية";
}

function renderAnalysis(result, elapsed) {
  const issues = Array.isArray(result?.resolved) ? result.resolved : [];
  currentResultText = textBox.value;
  copyButton.disabled = !currentResultText;
  resultTitle.textContent = issues.length ? `${issues.length} ملاحظة` : "النص سليم مبدئيًا";
  const nativeElapsed = Number(result?.elapsedMs);
  const shownElapsed = Number.isFinite(nativeElapsed) && nativeElapsed > 0 ? nativeElapsed : elapsed;
  resultMeta.textContent = `${result?.backend || "محلي"} · ${shownElapsed.toFixed(2)} ms`;
  performanceStatus.textContent = shownElapsed < 16 ? "ضمن ميزانية إطار واحد" : "اكتملت المعالجة المحلية";
  resultBody.innerHTML = "";
  if (!issues.length) {
    emptyState("لم يعثر الفحص السريع على أخطاء ضمن القواعد المحلية المفعلة.");
    return;
  }
  const list = document.createElement("div"); list.className = "issue-list";
  for (const issue of issues.slice(0, 12)) {
    const card = document.createElement("article"); card.className = "issue-card";
    const header = document.createElement("header");
    const title = document.createElement("strong"); title.textContent = issueTitle(issue);
    const category = document.createElement("small"); category.textContent = issue?.category || "تدقيق";
    header.append(title, category); card.append(header);
    const replacement = issue?.replacements?.[0];
    if (replacement) {
      const paragraph = document.createElement("p");
      paragraph.append("الاقتراح: ");
      const value = document.createElement("span"); value.className = "replacement"; value.textContent = replacement;
      paragraph.append(value); card.append(paragraph);
      const actions = document.createElement("div"); actions.className = "issue-actions";
      const apply = document.createElement("button"); apply.className = "soft-button"; apply.type = "button"; apply.textContent = "تطبيق";
      apply.addEventListener("click", () => applyIssue(issue)); actions.append(apply); card.append(actions);
    }
    list.append(card);
  }
  resultBody.append(list);
}

function renderRewrite(result, elapsed) {
  const candidates = Array.isArray(result?.candidates) ? result.candidates : [];
  resultTitle.textContent = candidates.length ? "بدائل جاهزة" : "لا توجد بدائل";
  resultMeta.textContent = `${result?.backend || "محلي"} · ${elapsed.toFixed(2)} ms`;
  performanceStatus.textContent = elapsed < 16 ? "ضمن ميزانية إطار واحد" : "اكتملت المعالجة المحلية";
  resultBody.innerHTML = "";
  currentResultText = candidates[0]?.text || "";
  copyButton.disabled = !currentResultText;
  if (!candidates.length) {
    emptyState("أدخل نصًا أطول قليلًا للحصول على بدائل مفيدة.");
    return;
  }
  const list = document.createElement("div"); list.className = "candidate-list";
  for (const candidate of candidates) {
    const card = document.createElement("article"); card.className = "candidate-card";
    const header = document.createElement("header");
    const title = document.createElement("strong"); title.textContent = candidate.label || "بديل";
    const confidence = document.createElement("small");
    confidence.textContent = Number.isFinite(candidate.confidence) ? `ثقة ${Math.round(candidate.confidence * 100)}%` : "محلي";
    header.append(title, confidence); card.append(header);
    const paragraph = document.createElement("p"); paragraph.textContent = candidate.text; card.append(paragraph);
    const actions = document.createElement("div"); actions.className = "candidate-actions";
    const use = document.createElement("button"); use.className = "primary-button"; use.type = "button"; use.textContent = "استخدمه";
    use.addEventListener("click", () => {
      textBox.value = candidate.text;
      currentResultText = candidate.text;
      copyButton.disabled = false;
      textBox.focus();
    });
    const copy = document.createElement("button"); copy.className = "soft-button"; copy.type = "button"; copy.textContent = "نسخ";
    copy.addEventListener("click", () => copyText(candidate.text));
    actions.append(use, copy); card.append(actions); list.append(card);
  }
  resultBody.append(list);
}

async function runCheck() {
  const text = textBox.value.trim();
  const sequence = ++operationSequence;
  if (!text) {
    currentResultText = ""; copyButton.disabled = true;
    resultTitle.textContent = "جاهز"; resultMeta.textContent = "ألصق نصًا للبدء";
    emptyState("التدقيق وإعادة الصياغة يعملان محليًا دون إرسال النص إلى خادم.");
    return;
  }
  setBusy(true, "جارٍ التدقيق…");
  const started = performance.now();
  try {
    const result = await analyzeText(text);
    if (sequence !== operationSequence) return;
    renderAnalysis(result, performance.now() - started);
  } catch (error) {
    if (sequence === operationSequence) showError(error);
  } finally {
    if (sequence === operationSequence) setBusy(false);
  }
}

async function runRewrite() {
  const text = textBox.value.trim();
  if (!text) { textBox.focus(); return; }
  const sequence = ++operationSequence;
  setBusy(true, "جارٍ إعداد البدائل…");
  const started = performance.now();
  try {
    const result = await paraphraseText(text, $("rewriteMode").value, { alternatives: 3 });
    if (sequence !== operationSequence) return;
    renderRewrite(result, performance.now() - started);
  } catch (error) {
    if (sequence === operationSequence) showError(error);
  } finally {
    if (sequence === operationSequence) setBusy(false);
  }
}

function queueCheck(delay = 280) {
  if (isComposing) return;
  clearTimeout(analysisTimer);
  analysisTimer = setTimeout(() => void runCheck(), delay);
}

async function copyText(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    resultMeta.textContent = `${resultMeta.textContent.split(" · نُسخ")[0]} · نُسخ`;
  } catch {
    textBox.focus(); textBox.select(); document.execCommand("copy");
  }
}

async function hideWindow() {
  if (isTauriEnvironment()) await invoke("hide_mini_assistant");
  else globalThis.close?.();
}

$("btnCheck").addEventListener("click", () => void runCheck());
$("btnRewrite").addEventListener("click", () => void runRewrite());
$("btnClear").addEventListener("click", () => {
  textBox.value = ""; currentResultText = ""; copyButton.disabled = true; operationSequence += 1;
  resultTitle.textContent = "جاهز"; resultMeta.textContent = "ألصق نصًا للبدء";
  emptyState("التدقيق وإعادة الصياغة يعملان محليًا دون إرسال النص إلى خادم.");
  updateCharacterCount();
  focusQuickText();
});
$("btnPaste").addEventListener("click", async () => {
  try { textBox.value = await navigator.clipboard.readText(); updateCharacterCount(); queueCheck(40); }
  catch { textBox.focus(); }
});
copyButton.addEventListener("click", () => void copyText(currentResultText || textBox.value));
$("btnHide").addEventListener("click", () => void hideWindow());
$("btnOpenMain").addEventListener("click", async () => { await invoke("open_main_window"); await hideWindow(); });
textBox.addEventListener("input", () => { updateCharacterCount(); queueCheck(); });
textBox.addEventListener("paste", () => { updateCharacterCount(); queueCheck(70); });
textBox.addEventListener("compositionstart", () => { isComposing = true; });
textBox.addEventListener("compositionend", () => { isComposing = false; updateCharacterCount(); queueCheck(120); });
textBox.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") { event.preventDefault(); void runCheck(); }
  if (event.shiftKey && event.key === "Enter") { event.preventDefault(); void runRewrite(); }
});
window.addEventListener("keydown", (event) => { if (event.key === "Escape") void hideWindow(); });

autoHide.checked = localStorage.getItem(AUTO_HIDE_KEY) === "1";
autoHide.addEventListener("change", () => localStorage.setItem(AUTO_HIDE_KEY, autoHide.checked ? "1" : "0"));
window.addEventListener("blur", () => {
  clearTimeout(autoHideTimer);
  if (autoHide.checked) autoHideTimer = setTimeout(() => {
    if (!document.hasFocus()) void hideWindow();
  }, 140);
});
window.addEventListener("focus", () => clearTimeout(autoHideTimer));

const platform = navigator.userAgent.includes("Mac") ? "macOS · ⌥ Space" : "Windows · Alt+Space";
$("shortcutHint").textContent = navigator.userAgent.includes("Mac") ? "⌥ Space" : "Alt Space";
$("nativeStatus").textContent = isTauriEnvironment() ? `Rust IPC محلي · ${platform}` : "وضع المتصفح";

const listen = tauriRoot()?.event?.listen;
if (typeof listen === "function") {
  void listen("mini-assistant:activated", () => {
    focusQuickText({ select: textBox.value.length === 0 });
  });
}
updateCharacterCount();
focusQuickText();
