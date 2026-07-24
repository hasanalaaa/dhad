import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  nativeDocumentDialogsAvailable,
  pickNativeDocument,
  saveNativeDocument,
} from "../js/native-file-dialogs.js";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repository = resolve(webRoot, "..");

function withTauriMock(mock, operation) {
  const previousWindow = globalThis.window;
  globalThis.window = { __TAURI__: mock };
  return Promise.resolve()
    .then(operation)
    .finally(() => {
      if (previousWindow === undefined) delete globalThis.window;
      else globalThis.window = previousWindow;
    });
}

test("Phase 2 config defines a hidden frameless always-on-top mini assistant", async () => {
  const config = JSON.parse(await readFile(resolve(repository, "src-tauri/tauri.conf.json"), "utf8"));
  const mini = config.app.windows.find((window) => window.label === "mini-assistant");
  assert.ok(mini);
  assert.equal(mini.url, "mini-assistant.html");
  assert.equal(mini.visible, false);
  assert.equal(mini.decorations, false);
  assert.equal(mini.alwaysOnTop, true);
  assert.equal(mini.skipTaskbar, true);
});

test("tray and hotkey sources use main-thread dispatch and requested Arabic actions", async () => {
  const tray = await readFile(resolve(repository, "src-tauri/src/tray.rs"), "utf8");
  const lib = await readFile(resolve(repository, "src-tauri/src/lib.rs"), "utf8");
  for (const label of ["افتح ضاد", "التدقيق السريع", "الإعدادات", "إنهاء"]) assert.match(tray, new RegExp(label, "u"));
  assert.match(tray, /run_on_main_thread/u);
  assert.match(lib, /Modifiers::ALT/u);
  assert.match(lib, /Code::Space/u);
  assert.match(lib, /tauri_plugin_dialog::init/u);
});

test("mini assistant exposes check, rewrite, copy-back and auto-hide controls", async () => {
  const html = await readFile(resolve(webRoot, "mini-assistant.html"), "utf8");
  const script = await readFile(resolve(webRoot, "mini-assistant.js"), "utf8");
  for (const id of ["quickText", "btnCheck", "btnRewrite", "btnCopyCurrent", "autoHide", "btnOpenMain"]) {
    assert.match(html, new RegExp(`id="${id}"`, "u"));
  }
  assert.match(html, /data-tauri-drag-region/u);
  assert.match(script, /analyzeText/u);
  assert.match(script, /paraphraseText/u);
  assert.match(script, /window\.addEventListener\("blur"/u);
  assert.match(script, /navigator\.clipboard\.writeText/u);
});

test("native document adapter preserves browser fallback", () => {
  assert.equal(nativeDocumentDialogsAvailable(), false);
});

test("native document adapter opens and reads a selected file", { concurrency: false }, async () => {
  const calls = [];
  await withTauriMock({
    dialog: {
      open: async () => "/tmp/notes.txt",
      save: async () => null,
    },
    core: {
      invoke: async (command, payload) => {
        calls.push([command, payload]);
        return {
          name: "notes.txt",
          path: "/tmp/notes.txt",
          extension: "txt",
          sizeBytes: 5,
          bytes: [104, 101, 108, 108, 111],
        };
      },
    },
  }, async () => {
    assert.equal(nativeDocumentDialogsAvailable(), true);
    const selected = await pickNativeDocument();
    assert.equal(selected.file.name, "notes.txt");
    assert.equal(await selected.file.text(), "hello");
    assert.equal(calls[0][0], "read_document_file");
  });
});

test("native document adapter saves Blob bytes through Rust IPC", { concurrency: false }, async () => {
  const calls = [];
  await withTauriMock({
    dialog: {
      open: async () => null,
      save: async () => "/tmp/export.md",
    },
    core: {
      invoke: async (command, payload) => {
        calls.push([command, payload]);
        return { path: payload.request.path, sizeBytes: payload.request.bytes.length };
      },
    },
  }, async () => {
    const result = await saveNativeDocument(new Blob(["مرحبا"], { type: "text/markdown" }), "export.md", "md");
    assert.equal(result.path, "/tmp/export.md");
    assert.equal(calls[0][0], "write_document_file");
    assert.ok(calls[0][1].request.bytes.length > 0);
  });
});
