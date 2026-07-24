/**
 * Real-browser proof: serve web_demo/, open it in headless Chromium, and run
 * the parity gate + latency benchmark *inside the page* — the numbers below
 * come from browser JS executing the WASM engine, not from Node.
 *
 *   node web_demo/browser_proof.mjs
 */

import { createServer } from "node:http";
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { dirname, join, extname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const types = {
  ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".json": "application/json", ".wasm": "application/wasm",
};

const server = createServer((request, response) => {
  const path = request.url === "/" ? "/index.html" : request.url.split("?")[0];
  const file = join(here, path);
  if (!file.startsWith(here) || !existsSync(file)) {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, { "content-type": types[extname(file)] ?? "application/octet-stream" });
  response.end(readFileSync(file));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const port = server.address().port;

function chromiumBinary() {
  const roots = ["/opt/pw-browsers"];
  for (const root of roots) {
    for (const entry of readdirSync(root)) {
      const candidate = join(root, entry, "chrome-linux", "chrome");
      if (existsSync(candidate)) return candidate;
      const headless = join(root, entry, "chrome-linux", "headless_shell");
      if (existsSync(headless)) return headless;
    }
  }
  throw new Error("no chromium found under /opt/pw-browsers");
}

const { chromium } = await import("playwright-core");
const browser = await chromium.launch({
  executablePath: chromiumBinary(),
  args: ["--no-sandbox"],
});
const page = await browser.newPage();
await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle" });
await page.waitForFunction(() => window.__dhad !== undefined);

const golden = readFileSync(
  join(here, "..", "rust", "dhad-core-rs", "tests", "data", "rules_golden.jsonl"),
  "utf8"
)
  .split("\n")
  .filter((line) => line.trim())
  .map((line) => JSON.parse(line));

const report = await page.evaluate((records) => {
  const engine = window.__dhad.engine;
  let parity = 0;
  for (const record of records) {
    const result = engine.check(record.text);
    const actual = result.resolved.map((m) => [m.rule_id, m.offset, m.length]);
    if (JSON.stringify(actual) !== JSON.stringify(record.resolved)) {
      return { error: `parity failure for: ${record.text}` };
    }
    parity += 1;
  }
  const morphology = engine.analyze("وبالمدرسة", 0.9)[0];
  const unicodeCase = "😀 هذه الكتاب";
  const parsed = engine.parse(unicodeCase);
  const syntaxIssues = engine.syntaxCheck(unicodeCase);
  if (
    morphology.lemma !== "مدرسة" ||
    parsed.sentences[0].tokens[0].start !== 2 ||
    syntaxIssues[0]?.offset !== 2
  ) {
    return { error: "morphology/syntax Unicode offset contract failure" };
  }
  const sentence = "انا ذهبت الى المدرسه قبل ثلاثة سنوات وكان اليوم جميلا. ";
  const cases = [
    ["sentence ", sentence, 300],
    ["paragraph", sentence.repeat(8), 150],
    ["document ", sentence.repeat(180), 40],
  ];
  const benches = cases.map(([label, text, n]) => {
    const times = [];
    for (let i = 0; i < n; i++) {
      const start = performance.now();
      engine.check(text);
      times.push(performance.now() - start);
    }
    times.sort((a, b) => a - b);
    return {
      label,
      chars: text.length,
      p50: times[Math.floor(n * 0.5)],
      p95: times[Math.floor(n * 0.95)],
    };
  });
  return { parity, total: records.length, ruleCount: engine.ruleCount, benches, ua: navigator.userAgent };
}, golden);

await browser.close();
server.close();

if (report.error) {
  console.error("BROWSER PARITY FAILURE:", report.error);
  process.exit(1);
}
console.log(`browser: ${report.ua}`);
console.log(`in-browser parity vs Python oracle: ${report.parity}/${report.total} ✔  (rules: ${report.ruleCount})`);
console.log("— in-browser WASM check latency —");
for (const bench of report.benches) {
  console.log(
    `${bench.label}: chars=${bench.chars} p50=${bench.p50.toFixed(3)}ms p95=${bench.p95.toFixed(3)}ms`
  );
}
console.log("BROWSER PROOF: PASSED");
