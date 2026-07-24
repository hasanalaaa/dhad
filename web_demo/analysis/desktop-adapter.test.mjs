import assert from "node:assert/strict";
import test from "node:test";

import {
  createAnalysisClient,
  getDesktopSystemInfo,
  isTauriEnvironment,
  paraphraseText,
} from "../js/desktop-adapter.js";

test("desktop adapter keeps the browser fallback active outside Tauri", async () => {
  assert.equal(isTauriEnvironment(), false);
  const result = await paraphraseText("هسه أريد نص مهم", "formal", { alternatives: 1 });
  assert.equal(result.offline, true);
  assert.ok(result.candidates.length >= 1);
  assert.match(result.candidates[0].text, /الآن/u);
});

test("desktop adapter reports a browser backend outside Tauri", async () => {
  const info = await getDesktopSystemInfo();
  assert.equal(info.nativeIpc, false);
  assert.equal(info.backend, "browser-wasm-worker");
});

test("desktop adapter constructs the existing worker client as browser fallback", () => {
  const fakeWorker = {
    addEventListener() {},
    removeEventListener() {},
    postMessage() {},
    terminate() {},
  };
  const client = createAnalysisClient({ workerFactory: () => fakeWorker, timeoutMs: 1_000 });
  assert.equal(typeof client.check, "function");
  client.dispose();
});
