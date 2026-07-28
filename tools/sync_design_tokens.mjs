#!/usr/bin/env node
/**
 * The design system is one system with four shipping surfaces. Three of them
 * cannot import the canonical file at runtime — the served PWA is a separate
 * artefact, the landing page deploys standalone, and the extension ships as its
 * own package — so each carries a copy of two blocks: the @font-face
 * declarations and the token block.
 *
 * `design-system.test.mjs` fails when a copy drifts. This script is how you
 * stop drifting: it rewrites every copy from the canonical file, rewriting the
 * font path for each surface on the way.
 *
 *   node tools/sync_design_tokens.mjs          # rewrite the copies
 *   node tools/sync_design_tokens.mjs --check  # exit 1 if any copy is stale
 */

import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repository = resolve(here, "..");
const at = (relative) => resolve(repository, relative);

const CANONICAL = "web_demo/design/dhad-system.css";

/** Each copy declares which blocks it carries and where its fonts live. */
const COPIES = [
  { file: "src/dhad/web/assets/app.css", blocks: ["font", "token"], fonts: "fonts/" },
  { file: "docs/site.css", blocks: ["font", "token"], fonts: "fonts/" },
  { file: "extension/popup.css", blocks: ["font"], fonts: "fonts/" },
];

const MARKERS = {
  font: ["dhad-font-block:start", "dhad-font-block:end"],
  token: ["dhad-token-block:start", "dhad-token-block:end"],
};

function bounds(source, kind, label) {
  const [START, END] = MARKERS[kind];
  const from = source.indexOf(START);
  const to = source.indexOf(END);
  if (from === -1 || to <= from) {
    throw new Error(`${label} is missing the ${kind} block markers (${START} … ${END})`);
  }
  return [from + START.length, to];
}

const canonical = await readFile(at(CANONICAL), "utf8");
const source = {};
for (const kind of Object.keys(MARKERS)) {
  const [from, to] = bounds(canonical, kind, CANONICAL);
  source[kind] = canonical.slice(from, to);
}

const check = process.argv.includes("--check");
let stale = 0;

for (const { file, blocks, fonts } of COPIES) {
  let text = await readFile(at(file), "utf8");
  let dirty = false;

  for (const kind of blocks) {
    // The canonical file sits in web_demo/design/, so it reaches the typefaces
    // as ../fonts/. Every copy sits somewhere else.
    const wanted = source[kind].replaceAll("../fonts/", fonts);
    const [from, to] = bounds(text, kind, file);
    if (text.slice(from, to) === wanted) continue;
    dirty = true;
    if (!check) text = text.slice(0, from) + wanted + text.slice(to);
  }

  if (!dirty) continue;
  stale += 1;
  if (check) {
    console.error(`stale: ${file}`);
    continue;
  }
  await writeFile(at(file), text);
  console.log(`synced: ${file}`);
}

if (check && stale) {
  console.error(`\n${stale} copy/copies drifted. Run: node tools/sync_design_tokens.mjs`);
  process.exit(1);
}
if (!stale) console.log("every copy matches the canonical blocks");
