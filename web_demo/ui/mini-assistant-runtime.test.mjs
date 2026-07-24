import assert from "node:assert/strict";
import test from "node:test";

class FakeClassList {
  toggle() {}
}

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.textContent = "";
    this.innerHTML = "";
    this.className = "";
    this.classList = new FakeClassList();
    this.listeners = new Map();
  }

  addEventListener(type, handler) {
    this.listeners.set(type, handler);
  }

  setAttribute() {}
  append() {}
  focus() {}
  select() {}
}

function installBrowserHarness() {
  const ids = [
    "quickText",
    "resultBody",
    "resultTitle",
    "resultMeta",
    "btnCopyCurrent",
    "autoHide",
    "characterCount",
    "performanceStatus",
    "btnCheck",
    "btnRewrite",
    "btnClear",
    "btnPaste",
    "btnHide",
    "btnOpenMain",
    "rewriteMode",
    "shortcutHint",
    "nativeStatus",
  ];
  const elements = new Map(ids.map((id) => [id, new FakeElement(id)]));
  const resultPanel = new FakeElement("result-panel");
  const miniShell = new FakeElement("mini-shell");

  globalThis.document = {
    getElementById: (id) => elements.get(id) ?? null,
    querySelector: (selector) => {
      if (selector === ".result-panel") return resultPanel;
      if (selector === ".mini-shell") return miniShell;
      return null;
    },
    createElement: () => new FakeElement(),
    execCommand: () => true,
    hasFocus: () => true,
  };
  globalThis.window = {
    addEventListener() {},
    close() {},
  };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      userAgent: "Mozilla/5.0 Windows",
      clipboard: {
        async writeText() {},
        async readText() { return ""; },
      },
    },
  });
  globalThis.localStorage = {
    getItem: () => null,
    setItem() {},
  };
  globalThis.requestAnimationFrame = (callback) => {
    callback(0);
    return 1;
  };

  return { elements, resultPanel, miniShell };
}

test("mini assistant boots with all Sovereign UI bindings defined", async () => {
  const { elements, resultPanel, miniShell } = installBrowserHarness();

  await import(`../mini-assistant.js?runtime-test=${Date.now()}`);

  assert.match(elements.get("characterCount").textContent, /حرف/u);
  assert.match(elements.get("nativeStatus").textContent, /المتصفح/u);
  assert.equal(resultPanel.id, "result-panel");
  assert.equal(miniShell.id, "mini-shell");
  assert.ok(elements.get("quickText").listeners.has("compositionstart"));
  assert.ok(elements.get("quickText").listeners.has("compositionend"));
});
