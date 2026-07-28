/**
 * The design system claims to be one system. This test is what makes that
 * claim enforceable rather than aspirational.
 *
 * `web_demo/design/dhad-system.css` is canonical. Three other surfaces cannot
 * import it at runtime (the served PWA is a separate artefact, the landing page
 * is deployed standalone, and the extension ships as its own package), so each
 * carries a copy. This test fails the moment a copy drifts.
 */

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const repository = resolve(here, "..", "..");
const read = (relative) => readFile(resolve(repository, relative), "utf8");

const START = "dhad-token-block:start";
const END = "dhad-token-block:end";

function tokenBlock(source, label) {
  const from = source.indexOf(START);
  const to = source.indexOf(END);
  assert.ok(from !== -1 && to > from, `${label} is missing the token block markers`);
  return source.slice(from + START.length, to);
}

const canonical = await read("web_demo/design/dhad-system.css");
const canonicalTokens = tokenBlock(canonical, "canonical");

test("every embedded copy of the token block matches the canonical one", async () => {
  for (const copy of ["src/dhad/web/assets/app.css", "docs/site.css"]) {
    assert.equal(
      tokenBlock(await read(copy), copy),
      canonicalTokens,
      `${copy} has drifted from web_demo/design/dhad-system.css`,
    );
  }
});

test("the extension only uses colours that exist in the canonical tokens", async () => {
  // The extension ships separately and writes literals rather than var(), so
  // the guarantee we can enforce is that no literal is off-palette.
  const palette = new Set(
    [...canonicalTokens.matchAll(/#[0-9a-f]{6}\b/giu)].map((match) => match[0].toLowerCase()),
  );
  // Panel-on-accent text and pure black/white are deliberate, and appear in the
  // canonical file inside component rules rather than in the token block.
  for (const allowed of ["#f2fbf6", "#04150f", "#000000", "#ffffff", "#1b1503"]) {
    palette.add(allowed);
  }
  for (const surface of ["extension/popup.css", "extension/content.css"]) {
    const source = await read(surface);
    // Strip the inline SVG data URLs: those encode the same hues, %23-escaped.
    const stripped = source.replaceAll(/url\("data:[^"]*"\)/gu, "");
    for (const found of new Set(
      [...stripped.matchAll(/#[0-9a-f]{6}\b/giu)].map((match) => match[0].toLowerCase()),
    )) {
      assert.ok(palette.has(found), `${surface} uses off-palette colour ${found}`);
    }
  }
});

test("no surface still references the retired visual identity", async () => {
  // Hex values from the pre-redesign obsidian/copper palette. If any of these
  // come back, some part of the old design survived the migration.
  const retired = [
    // the original obsidian/copper palette
    "#0c0f14", "#07090c", "#12161d", "#171c25", "#1e2430", "#262d3a", "#1c222d",
    "#d9b25a", "#eccb7b", "#b87848", "#ece7db", "#9aa3b0", "#626c7a",
    "#ff6b6b", "#f2b53f", "#6fb7ff", "#55c98a", "#c99cff", "#5fd0c0",
    "#080b10", "#10151d", "#151b24", "#f7f1e7", "#aeb6c2", "#b87333", "#d4af37",
    "#0a1512", "#07100d", "#0b0e14",
    // Midād's *interface* colours, replaced by Al-Ḥāshiya. The brand mark's own
    // gradient stops are deliberately NOT in this list: the mark survived the
    // redesign intact, and its emerald ribbon and gold light are the one place
    // those hues are still correct. What changed is where the interface spends
    // them — gold is now an edge and never a fill.
    "#111310", "#0b0c0a", "#161814", "#1c1f1a", "#23261f", "#353a31",
    "#f4f6f0", "#e2e7dc", "#9ba396", "#97a094", "#8f978b",
    "#35bc90", "#12a075", "#0b8560", "#a6e7cd", "#fbe9a8",
    "#f5806a", "#edb255", "#86b2ec", "#b99bee", "#58ccbe",
  ];
  const surfaces = [
    "web_demo/design/dhad-system.css",
    "web_demo/app.css",
    "web_demo/index.html",
    "web_demo/mini-assistant.css",
    "web_demo/mini-assistant.html",
    "web_demo/offline.html",
    "web_demo/manifest.json",
    "src/dhad/web/assets/app.css",
    "src/dhad/web/index.html",
    "src/dhad/web/manifest.webmanifest",
    "extension/popup.css",
    "extension/popup.html",
    "extension/content.css",
    "docs/index.html",
    "docs/site.css",
    "src-tauri/tauri.conf.json",
  ];
  for (const surface of surfaces) {
    const source = (await read(surface)).toLowerCase();
    for (const colour of retired) {
      assert.ok(!source.includes(colour), `${surface} still uses retired colour ${colour}`);
    }
  }
});

test("the canonical system defines the full brand ramp and all four themes", async () => {
  for (const token of [
    "--emerald-600", "--gold-400", "--ink-900", "--carnelian", "--saffron",
    "--lapis", "--amethyst", "--verdigris", "--font-display", "--font-text",
    "--font-doc", "--font-mono", "--ease-ribbon", "--focus-ring",
    // the three layers must all be present, or a "token" is just a variable
    "--paper-100", "--graphite-800", "--bg", "--accent", "--btn-primary-bg",
    "--gloss-width", "--mark-spelling",
  ]) {
    assert.match(canonical, new RegExp(`${token}\\s*:`, "u"), `missing token ${token}`);
  }
  for (const theme of ['\\[data-theme="light"\\]', '\\[data-theme="contrast"\\]']) {
    assert.match(canonical, new RegExp(theme, "u"), `missing theme ${theme}`);
  }
  // The identity must survive offline, so the typefaces are self-hosted.
  assert.match(canonical, /@font-face/u);
  for (const face of [
    "dhad-display.woff2",       // Alexandria — the Arabic display voice
    "dhad-text-arabic.woff2",   // IBM Plex Sans Arabic 400
    "dhad-text-arabic-600.woff2", // ...and a real 600, never synthesised
    "dhad-naskh-arabic.woff2",  // Noto Naskh — the document itself
    "dhad-mono.woff2",          // IBM Plex Mono — Latin ids and numerals
  ]) {
    assert.match(canonical, new RegExp(face.replaceAll(".", "\\."), "u"), `missing face ${face}`);
  }
  // Arabic is a connected script: a synthesised bold smears the joins, and
  // tracking breaks them outright. Both bans live in the canonical file.
  assert.match(canonical, /font-synthesis:\s*none/u, "font-synthesis: none is missing");
  assert.match(canonical, /letter-spacing:\s*0/u, "the Arabic letter-spacing reset is missing");
});

test("no surface uses a physical direction property", async () => {
  // Every physical direction is an RTL bug waiting for a language switch.
  const physical =
    /(?:^|[\s{;])(?:margin|padding|border|inset)-(?:left|right)\s*:|(?:^|[\s{;])(?:left|right)\s*:|text-align\s*:\s*(?:left|right)\b/u;
  for (const surface of [
    "web_demo/design/dhad-system.css",
    "web_demo/app.css",
  ]) {
    const source = await read(surface);
    for (const [index, line] of source.split("\n").entries()) {
      const code = line.split("/*")[0];
      assert.ok(
        !physical.test(code),
        `${surface}:${index + 1} uses a physical direction: ${line.trim()}`,
      );
    }
  }
});
