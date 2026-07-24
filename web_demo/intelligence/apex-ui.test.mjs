import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

async function source(name) {
  return readFile(resolve(root, name), "utf8");
}

test("Apex shell exposes the five writing-intelligence capabilities accessibly", async () => {
  const html = await source("index.html");
  assert.match(html, /id="wiTone"/u);
  assert.match(html, /id="wiClarity"/u);
  assert.match(html, /id="wiRichness"/u);
  assert.match(html, /id="wiDialect"/u);
  assert.match(html, /id="lexiconDialog"[^>]*aria-labelledby="lexiconTitle"/u);
  assert.match(html, /id="connectivityStatus"[^>]*role="status"/u);
  assert.match(html, /id="hcDisableRule"/u);
});

test("Apex app persists local lexicon and rule overrides and renders ARIA tooltips", async () => {
  const app = await source("app.js");
  assert.match(app, /storage\.putDictionary\(\{ id: "personal", words: customWords \}\)/u);
  assert.match(app, /storage\.setSetting\("disabledRules"/u);
  assert.match(app, /analysisClient\.check\(text, mode, \{/u);
  assert.match(app, /tooltip\.role = "tooltip"/u);
  assert.match(app, /item\.tabIndex = 0/u);
  assert.match(app, /window\.addEventListener\("offline", updateConnectivityStatus\)/u);
});

test("Apex intelligence module is part of the atomic offline shell", async () => {
  const policy = await source("pwa/cache-policy.js");
  assert.match(policy, /CACHE_VERSION = "gold-1\.0\.0-desktop-goldmaster"/u);
  assert.match(policy, /\.\/intelligence\/writing-intelligence\.js/u);
});
