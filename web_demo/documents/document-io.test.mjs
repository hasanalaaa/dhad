import assert from "node:assert/strict";
import test from "node:test";
import { createDocx, createStoredZip, docxXmlToHtml, htmlToMarkdown, importDocx, markdownToHtml, readZipEntries, safeDocumentName } from "./document-io.js";

const decoder = new TextDecoder();

test("markdown conversion preserves headings, emphasis and lists", () => {
  const html = markdownToHtml("# عنوان\n\n**مهم**\n\n- أول\n- ثان");
  assert.match(html, /<h1>عنوان<\/h1>/u);
  assert.match(html, /<strong>مهم<\/strong>/u);
  assert.match(htmlToMarkdown(html, { domParser: null }), /# عنوان/u);
});

test("stored ZIP writer and reader round-trip entries safely", async () => {
  const zip = createStoredZip([["word/document.xml", "<doc>ضاد</doc>"], ["a.txt", "ok"]]);
  const entries = await readZipEntries(zip);
  assert.equal(decoder.decode(entries.get("word/document.xml")), "<doc>ضاد</doc>");
});

test("DOCX export/import preserves semantic Arabic blocks offline", async () => {
  const docx = createDocx("<h1>عنوان</h1><p><strong>نص عربي</strong></p>", { domParser: null });
  const imported = await importDocx(docx, { domParser: null });
  assert.match(imported.text, /عنوان/u);
  assert.match(imported.text, /نص عربي/u);
  assert.equal(imported.preservedFormatting, true);
});

test("document names are safe and DOCX XML fallback escapes content", () => {
  assert.equal(safeDocumentName("../تقرير: نهائي.docx"), "تقرير-نهائي");
  assert.match(docxXmlToHtml("<w:document><w:p><w:r><w:t>&lt;ضاد&gt;</w:t></w:r></w:p></w:document>", { domParser: null }), /&lt;ضاد&gt;/u);
});
