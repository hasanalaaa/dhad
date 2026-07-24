"use strict";

(() => {
  if (globalThis.__dhadContentLoaded) return;
  globalThis.__dhadContentLoaded = true;

  const controllers = new WeakMap();
  const activeControllers = new Set();
  let currentSettings = null;

  function sendMessage(type, payload = {}) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ type, payload }, (response) => {
        if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
        if (!response?.ok) return reject(new Error(response?.error || "تعذر الاتصال بإضافة ضاد"));
        resolve(response.data);
      });
    });
  }

  function isSupportedField(element) {
    return element instanceof HTMLTextAreaElement || (element instanceof HTMLElement && element.isContentEditable);
  }

  function getText(element) {
    return element instanceof HTMLTextAreaElement ? element.value : element.textContent || "";
  }

  function copyTypography(source, target) {
    const computed = getComputedStyle(source);
    [
      "fontFamily", "fontSize", "fontWeight", "fontStyle", "fontVariant", "lineHeight",
      "letterSpacing", "wordSpacing", "textAlign", "textIndent", "textTransform",
      "direction", "writingMode", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
      "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
    ].forEach((property) => { target.style[property] = computed[property]; });
  }

  function textNodes(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    return nodes;
  }

  function replaceContentEditableRange(element, offset, length, replacement) {
    const nodes = textNodes(element);
    let position = 0;
    let startNode = null;
    let endNode = null;
    let startOffset = 0;
    let endOffset = 0;
    for (const node of nodes) {
      const next = position + node.data.length;
      if (!startNode && offset >= position && offset <= next) {
        startNode = node;
        startOffset = offset - position;
      }
      const targetEnd = offset + length;
      if (!endNode && targetEnd >= position && targetEnd <= next) {
        endNode = node;
        endOffset = targetEnd - position;
        break;
      }
      position = next;
    }
    if (!startNode || !endNode) return false;
    const range = document.createRange();
    range.setStart(startNode, startOffset);
    range.setEnd(endNode, endOffset);
    range.deleteContents();
    const inserted = document.createTextNode(replacement);
    range.insertNode(inserted);
    const selection = window.getSelection();
    selection.removeAllRanges();
    const caret = document.createRange();
    caret.setStartAfter(inserted);
    caret.collapse(true);
    selection.addRange(caret);
    element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertReplacementText", data: replacement }));
    return true;
  }

  class FieldController {
    constructor(element) {
      this.element = element;
      this.matches = [];
      this.timer = null;
      this.requestSequence = 0;
      this.overlay = document.createElement("div");
      this.overlay.className = "dhad-overlay";
      this.mirror = document.createElement("div");
      this.mirror.className = "dhad-overlay__mirror";
      this.overlay.append(this.mirror);
      this.badge = document.createElement("button");
      this.badge.type = "button";
      this.badge.className = "dhad-badge";
      this.badge.hidden = true;
      this.badge.setAttribute("aria-label", "ملاحظات ضاد");
      this.card = document.createElement("section");
      this.card.className = "dhad-card";
      this.card.hidden = true;
      document.documentElement.append(this.overlay, this.badge, this.card);
      this.onInput = () => this.schedule();
      this.onScroll = () => this.position();
      this.onFocus = () => this.position();
      this.element.addEventListener("input", this.onInput);
      this.element.addEventListener("scroll", this.onScroll, { passive: true });
      this.element.addEventListener("focus", this.onFocus);
      this.badge.addEventListener("mouseenter", () => this.showCard());
      this.badge.addEventListener("click", () => this.showCard());
      this.position();
      this.schedule();
    }

    destroy() {
      clearTimeout(this.timer);
      this.element.removeEventListener("input", this.onInput);
      this.element.removeEventListener("scroll", this.onScroll);
      this.element.removeEventListener("focus", this.onFocus);
      this.overlay.remove();
      this.badge.remove();
      this.card.remove();
      activeControllers.delete(this);
    }

    position() {
      if (!this.element.isConnected) return this.destroy();
      const rect = this.element.getBoundingClientRect();
      const visible = rect.width > 30 && rect.height > 20 && rect.bottom > 0 && rect.top < innerHeight;
      this.overlay.hidden = !visible;
      if (!visible) {
        this.badge.hidden = true;
        this.card.hidden = true;
        return;
      }
      Object.assign(this.overlay.style, {
        left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px`,
      });
      copyTypography(this.element, this.mirror);
      this.mirror.style.width = `${this.element.scrollWidth}px`;
      this.mirror.style.transform = `translate(${-this.element.scrollLeft}px, ${-this.element.scrollTop}px)`;
      const badgeLeft = Math.max(4, Math.min(innerWidth - 44, rect.left + 7));
      const badgeTop = Math.max(4, Math.min(innerHeight - 30, rect.top + 6));
      Object.assign(this.badge.style, { left: `${badgeLeft}px`, top: `${badgeTop}px` });
      this.badge.hidden = this.matches.length === 0;
      if (!this.card.hidden) {
        const cardTop = Math.min(innerHeight - 20, rect.top + 36);
        const cardLeft = Math.max(10, Math.min(innerWidth - 370, rect.left));
        Object.assign(this.card.style, { left: `${cardLeft}px`, top: `${Math.max(10, cardTop)}px` });
      }
    }

    schedule() {
      clearTimeout(this.timer);
      const delay = Math.max(250, Number(currentSettings?.debounceMs || 700));
      this.timer = setTimeout(() => this.analyze(), delay);
    }

    async analyze() {
      const text = getText(this.element);
      if (!currentSettings?.enabled || !text.trim()) {
        this.matches = [];
        this.render();
        return;
      }
      const sequence = ++this.requestSequence;
      try {
        const response = await sendMessage("DHAD_CHECK", { text });
        if (sequence !== this.requestSequence) return;
        const allowed = new Set(currentSettings.categories || []);
        this.matches = DhadShared.nonOverlappingMatches(response.matches || []).filter((item) => {
          if (!allowed.has(item.category)) return false;
          if (item.category === "style" && !currentSettings.showStyle) return false;
          if (item.category === "dialect" && !currentSettings.showDialect) return false;
          return true;
        });
        this.render();
      } catch (error) {
        if (sequence !== this.requestSequence) return;
        this.matches = [];
        this.render(error.message);
      }
    }

    render(error = "") {
      const text = getText(this.element);
      this.mirror.replaceChildren();
      let cursor = 0;
      for (const match of this.matches) {
        const start = Math.max(cursor, Math.min(text.length, match.offset));
        const end = Math.max(start, Math.min(text.length, match.offset + match.length));
        this.mirror.append(document.createTextNode(text.slice(cursor, start)));
        const span = document.createElement("span");
        span.className = "dhad-squiggle";
        span.dataset.category = match.category;
        span.textContent = text.slice(start, end);
        this.mirror.append(span);
        cursor = end;
      }
      this.mirror.append(document.createTextNode(text.slice(cursor)));
      this.badge.textContent = String(this.matches.length);
      this.badge.title = error || `${this.matches.length} ملاحظة من ضاد`;
      this.position();
      if (!this.card.hidden) this.showCard(error);
    }

    showCard(error = "") {
      this.card.replaceChildren();
      const header = document.createElement("div");
      header.className = "dhad-card__header";
      const title = document.createElement("strong");
      title.textContent = "ملاحظات ضاد";
      const close = document.createElement("button");
      close.type = "button";
      close.className = "dhad-card__close";
      close.textContent = "×";
      close.setAttribute("aria-label", "إغلاق");
      close.addEventListener("click", () => { this.card.hidden = true; });
      header.append(title, close);
      this.card.append(header);
      const tools = document.createElement("div");
      tools.className = "dhad-card__gold-tools";
      for (const [label, action] of [["إعادة صياغة", () => this.showRewrite()], ["تحليلات", () => this.showAnalytics()], ["قوالب", () => this.showTemplates()]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "dhad-card__tool";
        button.textContent = label;
        button.addEventListener("click", action);
        tools.append(button);
      }
      this.card.append(tools);
      if (error) {
        const message = document.createElement("p");
        message.className = "dhad-card__error";
        message.textContent = error;
        this.card.append(message);
      } else {
        for (const match of this.matches.slice(0, 8)) this.card.append(this.issueNode(match));
      }
      this.card.hidden = false;
      this.position();
    }

    resultPanel() {
      this.card.querySelector(".dhad-card__gold-result")?.remove();
      const panel = document.createElement("section");
      panel.className = "dhad-card__gold-result";
      this.card.append(panel);
      return panel;
    }

    replaceWholeText(text) {
      if (this.element instanceof HTMLTextAreaElement) {
        this.element.value = text;
        this.element.setSelectionRange(text.length, text.length);
      } else {
        this.element.textContent = text;
      }
      this.element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertReplacementText", data: text }));
      this.element.focus();
    }

    async showRewrite() {
      const panel = this.resultPanel();
      panel.textContent = "جارٍ إنشاء بدائل محافظة على المعنى…";
      try {
        const result = await sendMessage("DHAD_REWRITE", { text: getText(this.element), mode: currentSettings?.rewriteMode || "formal", alternatives: 3 });
        panel.replaceChildren();
        for (const candidate of result.candidates || []) {
          const article = document.createElement("article"); article.className = "dhad-card__rewrite";
          const title = document.createElement("strong"); title.textContent = candidate.label;
          const body = document.createElement("p"); body.textContent = candidate.text;
          const apply = document.createElement("button"); apply.type = "button"; apply.className = "dhad-card__button"; apply.textContent = "تطبيق النص";
          apply.addEventListener("click", () => { this.replaceWholeText(candidate.text); this.card.hidden = true; });
          article.append(title, body, apply); panel.append(article);
        }
        if (!panel.children.length) panel.textContent = "لا توجد إعادة صياغة آمنة لهذا النص.";
      } catch (error) { panel.textContent = error.message; panel.classList.add("dhad-card__error"); }
      this.position();
    }

    async showAnalytics() {
      const panel = this.resultPanel(); panel.textContent = "جارٍ تحليل المستند…";
      try {
        const result = await sendMessage("DHAD_ANALYTICS", { text: getText(this.element) });
        panel.replaceChildren();
        const grid = document.createElement("div"); grid.className = "dhad-card__metrics";
        for (const [label, value] of [["الوضوح", Math.round(result.clarity_score)], ["التفاعل", Math.round(result.engagement_score)], ["الثراء", Math.round(result.vocabulary_richness)], ["التعقيد", Math.round(result.complexity_score)]]) {
          const item = document.createElement("span");
          const number = document.createElement("b"); number.textContent = String(value);
          const caption = document.createElement("small"); caption.textContent = label;
          item.append(number, caption); grid.append(item);
        }
        const summary = document.createElement("p"); summary.textContent = `${result.words} كلمة · ${result.sentences} جملة · قراءة ${Math.max(1, Math.ceil(result.estimated_reading_seconds / 60))} د`;
        panel.append(grid, summary);
      } catch (error) { panel.textContent = error.message; panel.classList.add("dhad-card__error"); }
      this.position();
    }

    async showTemplates() {
      const panel = this.resultPanel(); panel.textContent = "جارٍ تحميل القوالب…";
      try {
        const result = await sendMessage("DHAD_TEMPLATES"); panel.replaceChildren();
        for (const template of result.templates || []) {
          const button = document.createElement("button"); button.type = "button"; button.className = "dhad-card__template";
          const title = document.createElement("strong"); title.textContent = template.title;
          const description = document.createElement("small"); description.textContent = template.description;
          button.append(title, description);
          button.addEventListener("click", async () => {
            panel.textContent = "جارٍ إنشاء القالب…";
            try {
              const generated = await sendMessage("DHAD_GENERATE_TEMPLATE", { templateId: template.id, values: {}, tone: template.supported_tones?.[0] || "formal" });
              this.replaceWholeText(generated.text); this.card.hidden = true;
            } catch (error) { panel.textContent = error.message; }
          });
          panel.append(button);
        }
      } catch (error) { panel.textContent = error.message; panel.classList.add("dhad-card__error"); }
      this.position();
    }

    issueNode(match) {
      const node = document.createElement("article");
      node.className = "dhad-card__issue";
      const title = document.createElement("strong");
      title.textContent = match.message;
      const explanation = document.createElement("p");
      explanation.textContent = match.explanation || `${match.category} · ثقة ${Math.round(match.confidence * 100)}%`;
      node.append(title, explanation);
      if (match.replacements?.length) {
        const actions = document.createElement("div");
        actions.className = "dhad-card__actions";
        for (const replacement of match.replacements.slice(0, 3)) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = `dhad-card__button${match.autofix ? "" : " dhad-card__button--review"}`;
          button.textContent = match.autofix ? `تطبيق: ${replacement}` : `مراجعة: ${replacement}`;
          button.addEventListener("click", () => this.apply(match, replacement));
          actions.append(button);
        }
        node.append(actions);
      }
      return node;
    }

    apply(match, replacement) {
      if (this.element instanceof HTMLTextAreaElement) {
        const next = DhadShared.applyTextReplacement(this.element.value, match.offset, match.length, replacement);
        this.element.value = next;
        const caret = match.offset + replacement.length;
        this.element.setSelectionRange(caret, caret);
        this.element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertReplacementText", data: replacement }));
      } else {
        replaceContentEditableRange(this.element, match.offset, match.length, replacement);
      }
      this.card.hidden = true;
      this.element.focus();
    }
  }

  function attach(element) {
    if (!isSupportedField(element) || controllers.has(element) || element.dataset.dhadIgnore === "true") return;
    const controller = new FieldController(element);
    controllers.set(element, controller);
    activeControllers.add(controller);
  }

  function scan(root = document) {
    if (isSupportedField(root)) attach(root);
    root.querySelectorAll?.("textarea, [contenteditable='true'], [contenteditable='plaintext-only']").forEach(attach);
  }

  async function initialize() {
    try {
      currentSettings = await sendMessage("DHAD_GET_SETTINGS");
    } catch (_) {
      currentSettings = { ...{ enabled: false, debounceMs: 700, categories: [] } };
    }
    scan();
    new MutationObserver((records) => {
      for (const record of records) record.addedNodes.forEach((node) => { if (node.nodeType === Node.ELEMENT_NODE) scan(node); });
    }).observe(document.documentElement, { childList: true, subtree: true });
    addEventListener("resize", () => activeControllers.forEach((controller) => controller.position()), { passive: true });
    addEventListener("scroll", () => activeControllers.forEach((controller) => controller.position()), { passive: true, capture: true });
    chrome.storage.onChanged.addListener(async (_changes, area) => {
      if (area !== "sync") return;
      currentSettings = await sendMessage("DHAD_GET_SETTINGS");
      activeControllers.forEach((controller) => controller.schedule());
    });
  }

  initialize();
})();
