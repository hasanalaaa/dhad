#!/usr/bin/env node
import { readdir } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { extname, join, relative, resolve } from "node:path";

const root = resolve(new URL("..", import.meta.url).pathname);
const roots = ["web_demo", "extension", "tools"];
const excluded = new Set(["node_modules", "vendor", "models", ".git"]);
const extensions = new Set([".js", ".mjs"]);

async function collect(directory, output = []) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (excluded.has(entry.name)) continue;
    const path = join(directory, entry.name);
    if (entry.isDirectory()) await collect(path, output);
    else if (entry.isFile() && extensions.has(extname(entry.name))) output.push(path);
  }
  return output;
}

const files = [];
for (const directory of roots) await collect(join(root, directory), files);
files.sort();
const failures = [];
for (const file of files) {
  const result = spawnSync(process.execPath, ["--check", file], { encoding: "utf8" });
  if (result.status !== 0) {
    failures.push(`${relative(root, file)}\n${result.stderr || result.stdout}`);
  }
}
if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else {
  console.log(`JavaScript syntax verified: ${files.length} first-party files`);
}
