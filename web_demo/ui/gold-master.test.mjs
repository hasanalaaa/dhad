import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repository = resolve(root, "..");
const webPackage = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
const releaseVersion = webPackage.version;
const escapedReleaseVersion = releaseVersion.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");

test("Gold Master shell exposes rewriting, documents, analytics, templates and themes accessibly", async () => {
  const html = await readFile(resolve(root, "index.html"), "utf8");
  const app = await readFile(resolve(root, "app.js"), "utf8");
  for (const id of ["btnRewrite", "btnTemplates", "btnAnalytics", "btnImport", "btnExport", "themeSelect", "rewriteDialog", "templateDialog", "analyticsDialog", "exportDialog"]) {
    assert.match(html, new RegExp(`id="${id}"`, "u"), `missing ${id}`);
  }
  assert.match(html, /aria-labelledby="rewriteTitle"/u);
  assert.match(html, /accept="\.txt,\.md,\.docx,\.pdf/u);
  assert.match(app, /sanitizeEditorFragment/u);
  assert.match(app, /replaceEditorTextSpan/u);
  assert.match(app, /assertCapabilityParity\(GOLD_CAPABILITIES\)/u);
});

test("all Gold modules are part of the atomic offline shell", async () => {
  const policy = await readFile(resolve(root, "pwa/cache-policy.js"), "utf8");
  for (const module of ["js/desktop-adapter.js", "rewriting/offline-rewriter.js", "analytics/writing-analytics.js", "templates/smart-templates.js", "themes/theme-controller.js", "documents/document-io.js", "shared/capabilities.js"]) {
    assert.match(policy, new RegExp(module.replaceAll("/", "\\/"), "u"));
  }
  assert.match(policy, new RegExp(`gold-${escapedReleaseVersion}-desktop-goldmaster`, "u"));
});

test("browser extension exposes the same Gold service capabilities", async () => {
  const background = await readFile(resolve(repository, "extension/background.js"), "utf8");
  const content = await readFile(resolve(repository, "extension/content.js"), "utf8");
  const manifest = JSON.parse(await readFile(resolve(repository, "extension/manifest.json"), "utf8"));
  for (const message of ["DHAD_INTELLIGENCE", "DHAD_REWRITE", "DHAD_ANALYTICS", "DHAD_TEMPLATES", "DHAD_GENERATE_TEMPLATE"]) assert.match(background, new RegExp(message, "u"));
  assert.match(content, /showRewrite/u);
  assert.match(content, /showAnalytics/u);
  assert.match(content, /showTemplates/u);
  assert.equal(manifest.version, releaseVersion);
  assert.equal(manifest.version_name, `${releaseVersion} Gold Master`);
});
