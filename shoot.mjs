import { chromium } from 'playwright-core';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

/**
 * Render a surface at a given width, theme and colour scheme, then report the
 * two facts a screenshot alone will not tell you: whether anything overflows
 * horizontally, and whether the console stayed clean.
 *
 *   node shoot.mjs <root> <outDir> file.html:width:height:scheme[:fold]
 *
 * `fold` captures the viewport only. Use it whenever the page uses
 * content-visibility: auto — a full-page capture does not force off-screen
 * content to paint, and empty rows in the image are an artefact, not a bug.
 */
const ROOT = process.argv[2] || process.cwd();
const SHOTS = process.argv[3] || path.join(ROOT, 'shots');
const TARGETS = process.argv.slice(4);
const MIME = { '.html': 'text/html;charset=utf-8', '.css': 'text/css;charset=utf-8', '.js': 'text/javascript;charset=utf-8', '.mjs': 'text/javascript;charset=utf-8', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json', '.wasm': 'application/wasm', '.webmanifest': 'application/manifest+json', '.txt': 'text/plain;charset=utf-8', '.onnx': 'application/octet-stream' };

const server = http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split('?')[0]);
  const file = path.join(ROOT, url === '/' ? '/index.html' : url);
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404); return res.end('404');
  }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream', 'access-control-allow-origin': '*' });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, r));
const port = server.address().port;

fs.mkdirSync(SHOTS, { recursive: true });
const browser = await chromium.launch({
  executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  args: ['--no-sandbox', '--font-render-hinting=none'],
});

let failures = 0;
for (const spec of TARGETS) {
  const [file, w = 1440, h = 1200, scheme = 'light', mode] = spec.split(':');
  const ctx = await browser.newContext({ viewport: { width: +w, height: +h }, deviceScaleFactor: 2, colorScheme: scheme });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 160)); });
  page.on('pageerror', (e) => errors.push('PAGEERROR ' + String(e).slice(0, 160)));

  await page.goto(`http://127.0.0.1:${port}/${file}`, { waitUntil: 'load', timeout: 45000 });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(2500);

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  const out = path.join(SHOTS, `${path.basename(file, '.html')}-${w}-${scheme}${mode ? '-' + mode : ''}.png`);
  await page.screenshot({ path: out, fullPage: mode !== 'fold' });

  const bad = overflow > 0 || errors.length > 0;
  if (bad) failures += 1;
  console.log(`${bad ? 'FAIL' : ' ok '} ${out}  overflowX=${overflow}px  consoleErrors=${errors.length}${errors.length ? ' :: ' + errors.join(' | ') : ''}`);
  await ctx.close();
}
await browser.close();
server.close();
process.exit(failures ? 1 : 0);
