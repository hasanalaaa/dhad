const UTF8 = new TextEncoder();
const UTF8_DECODER = new TextDecoder("utf-8");
const LATIN1_DECODER = new TextDecoder("latin1");

export const IMPORT_FORMATS = Object.freeze(["txt", "md", "docx", "pdf"]);
export const EXPORT_FORMATS = Object.freeze(["txt", "md", "docx", "pdf"]);

function extension(name = "") {
  const match = String(name).toLowerCase().match(/\.([a-z0-9]+)$/u);
  return match?.[1] ?? "";
}

export function safeDocumentName(name, fallback = "مستند-ضاد") {
  const clean = String(name || "")
    .replace(/\.[^.]+$/u, "")
    .replace(/[\\/:*?"<>|\u0000-\u001f]/gu, "-")
    .replace(/\s+/gu, " ")
    .replace(/^[-.\s]+|[-.\s]+$/gu, "")
    .replace(/\s*-\s*/gu, "-")
    .replace(/-{2,}/gu, "-");
  return (clean || fallback).slice(0, 120);
}

function escapeHtml(value) {
  return String(value).replace(/&/gu, "&amp;").replace(/</gu, "&lt;").replace(/>/gu, "&gt;").replace(/"/gu, "&quot;");
}
function escapeXml(value) {
  return escapeHtml(value).replace(/'/gu, "&apos;");
}

export function markdownToHtml(markdown) {
  if (typeof markdown !== "string") throw new TypeError("markdown must be a string");
  const lines = markdown.replace(/\r\n?/gu, "\n").split("\n");
  const out = [];
  let list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const inline = (value) => escapeHtml(value)
    .replace(/\*\*([^*]+)\*\*/gu, "<strong>$1</strong>")
    .replace(/__([^_]+)__/gu, "<strong>$1</strong>")
    .replace(/(?<!\*)\*([^*]+)\*(?!\*)/gu, "<em>$1</em>")
    .replace(/`([^`]+)`/gu, "<code>$1</code>");
  for (const raw of lines) {
    const line = raw.trimEnd();
    const heading = line.match(/^(#{1,3})\s+(.+)$/u);
    const unordered = line.match(/^[-*+]\s+(.+)$/u);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/u);
    if (heading) { closeList(); out.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`); }
    else if (unordered || ordered) {
      const next = unordered ? "ul" : "ol";
      if (list !== next) { closeList(); list = next; out.push(`<${list}>`); }
      out.push(`<li>${inline((unordered || ordered)[1])}</li>`);
    } else if (!line.trim()) { closeList(); }
    else { closeList(); out.push(`<p>${inline(line)}</p>`); }
  }
  closeList();
  return out.join("\n") || "<p></p>";
}

export function htmlToMarkdown(html, { domParser = globalThis.DOMParser } = {}) {
  if (typeof html !== "string") throw new TypeError("html must be a string");
  if (!domParser) {
    return html
      .replace(/<h([1-3])[^>]*>([\s\S]*?)<\/h\1>/giu, (_match, level, content) => `${"#".repeat(Number(level))} ${content}\n\n`)
      .replace(/<li[^>]*>([\s\S]*?)<\/li>/giu, (_match, content) => `- ${content}\n`)
      .replace(/<(?:strong|b)[^>]*>([\s\S]*?)<\/(?:strong|b)>/giu, "**$1**")
      .replace(/<(?:em|i)[^>]*>([\s\S]*?)<\/(?:em|i)>/giu, "*$1*")
      .replace(/<code[^>]*>([\s\S]*?)<\/code>/giu, "`$1`")
      .replace(/<br\s*\/?>/giu, "\n")
      .replace(/<\/(?:p|div|ul|ol)>/giu, "\n\n")
      .replace(/<[^>]+>/gu, "")
      .replace(/&lt;/gu, "<").replace(/&gt;/gu, ">").replace(/&amp;/gu, "&")
      .replace(/\n{3,}/gu, "\n\n")
      .trim();
  }
  const document = new domParser().parseFromString(html, "text/html");
  const renderInline = (node) => {
    if (node.nodeType === 3) return node.data;
    const content = [...node.childNodes].map(renderInline).join("");
    const tag = node.nodeName.toLowerCase();
    if (tag === "strong" || tag === "b") return `**${content}**`;
    if (tag === "em" || tag === "i") return `*${content}*`;
    if (tag === "code") return `\`${content}\``;
    if (tag === "br") return "\n";
    return content;
  };
  const blocks = [];
  for (const node of document.body.children) {
    const tag = node.nodeName.toLowerCase();
    const content = [...node.childNodes].map(renderInline).join("").trim();
    if (/^h[1-3]$/u.test(tag)) blocks.push(`${"#".repeat(Number(tag[1]))} ${content}`);
    else if (tag === "ul" || tag === "ol") {
      [...node.children].forEach((item, index) => blocks.push(`${tag === "ol" ? `${index + 1}.` : "-"} ${[...item.childNodes].map(renderInline).join("").trim()}`));
    } else if (content) blocks.push(content);
  }
  return blocks.join("\n\n");
}

function view(bytes) { return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength); }
function u16(bytes, offset) { return view(bytes).getUint16(offset, true); }
function u32(bytes, offset) { return view(bytes).getUint32(offset, true); }

async function inflateRaw(bytes) {
  if (typeof DecompressionStream !== "function") throw new Error("هذا المتصفح لا يدعم فك ضغط DOCX محليًا");
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export async function readZipEntries(input) {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
  let eocd = -1;
  for (let offset = Math.max(0, bytes.length - 65_557); offset <= bytes.length - 22; offset += 1) {
    if (u32(bytes, offset) === 0x06054b50) eocd = offset;
  }
  if (eocd < 0) throw new Error("ملف ZIP/DOCX غير صالح: لم يعثر على دليل النهاية");
  const entryCount = u16(bytes, eocd + 10);
  const centralOffset = u32(bytes, eocd + 16);
  if (entryCount > 10_000 || centralOffset >= bytes.length) throw new Error("بنية DOCX تتجاوز حدود الأمان");
  const entries = new Map();
  let cursor = centralOffset;
  let totalInflated = 0;
  for (let index = 0; index < entryCount; index += 1) {
    if (u32(bytes, cursor) !== 0x02014b50) throw new Error("دليل DOCX المركزي تالف");
    const method = u16(bytes, cursor + 10);
    const compressedSize = u32(bytes, cursor + 20);
    const uncompressedSize = u32(bytes, cursor + 24);
    const nameLength = u16(bytes, cursor + 28);
    const extraLength = u16(bytes, cursor + 30);
    const commentLength = u16(bytes, cursor + 32);
    const localOffset = u32(bytes, cursor + 42);
    const name = UTF8_DECODER.decode(bytes.subarray(cursor + 46, cursor + 46 + nameLength));
    if (name.includes("..") || name.startsWith("/") || name.startsWith("\\")) throw new Error("DOCX يحتوي مسارًا غير آمن");
    if (uncompressedSize > 50 * 1024 * 1024) throw new Error("أحد أجزاء DOCX أكبر من الحد المسموح");
    totalInflated += uncompressedSize;
    if (totalInflated > 120 * 1024 * 1024) throw new Error("DOCX يتجاوز حد الذاكرة الآمن");
    if (u32(bytes, localOffset) !== 0x04034b50) throw new Error("ترويسة DOCX المحلية تالفة");
    const localNameLength = u16(bytes, localOffset + 26);
    const localExtraLength = u16(bytes, localOffset + 28);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    const compressed = bytes.subarray(dataStart, dataStart + compressedSize);
    let payload;
    if (method === 0) payload = new Uint8Array(compressed);
    else if (method === 8) payload = await inflateRaw(compressed);
    else throw new Error(`طريقة ضغط DOCX غير مدعومة: ${method}`);
    if (uncompressedSize && payload.length !== uncompressedSize) throw new Error(`حجم جزء DOCX غير متطابق: ${name}`);
    entries.set(name, payload);
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

function decodeEntities(value) {
  return value.replace(/&lt;/gu, "<").replace(/&gt;/gu, ">").replace(/&quot;/gu, '"').replace(/&apos;/gu, "'").replace(/&amp;/gu, "&");
}

export function docxXmlToHtml(xml, { domParser = globalThis.DOMParser } = {}) {
  if (typeof xml !== "string") throw new TypeError("DOCX XML must be a string");
  if (!domParser) {
    const paragraphs = [...xml.matchAll(/<w:p\b[^>]*>([\s\S]*?)<\/w:p>/gu)].map((match) => {
      const text = [...match[1].matchAll(/<w:t\b[^>]*>([\s\S]*?)<\/w:t>/gu)].map((item) => decodeEntities(item[1])).join("");
      return `<p>${escapeHtml(text)}</p>`;
    });
    return paragraphs.join("\n") || "<p></p>";
  }
  const document = new domParser().parseFromString(xml, "application/xml");
  if (document.querySelector("parsererror")) throw new Error("تعذر تحليل XML داخل DOCX");
  const paragraphs = [];
  for (const paragraph of document.getElementsByTagNameNS("*", "p")) {
    const styleValue = paragraph.getElementsByTagNameNS("*", "pStyle")[0]?.getAttribute("w:val") || paragraph.getElementsByTagNameNS("*", "pStyle")[0]?.getAttribute("val") || "";
    const tag = /Heading1|Title|العنوان\s*1/iu.test(styleValue) ? "h1" : /Heading2|العنوان\s*2/iu.test(styleValue) ? "h2" : "p";
    const parts = [];
    for (const run of paragraph.getElementsByTagNameNS("*", "r")) {
      const props = run.getElementsByTagNameNS("*", "rPr")[0];
      const bold = Boolean(props?.getElementsByTagNameNS("*", "b").length);
      const italic = Boolean(props?.getElementsByTagNameNS("*", "i").length);
      const underline = Boolean(props?.getElementsByTagNameNS("*", "u").length);
      let text = [...run.getElementsByTagNameNS("*", "t")].map((item) => item.textContent || "").join("");
      if (run.getElementsByTagNameNS("*", "tab").length) text += "\t";
      if (run.getElementsByTagNameNS("*", "br").length) text += "\n";
      let content = escapeHtml(text);
      if (underline) content = `<u>${content}</u>`;
      if (italic) content = `<em>${content}</em>`;
      if (bold) content = `<strong>${content}</strong>`;
      parts.push(content);
    }
    paragraphs.push(`<${tag}>${parts.join("") || "<br>"}</${tag}>`);
  }
  return paragraphs.join("\n") || "<p></p>";
}

export async function importDocx(buffer, options = {}) {
  const entries = await readZipEntries(buffer);
  const documentXml = entries.get("word/document.xml");
  if (!documentXml) throw new Error("DOCX لا يحتوي word/document.xml");
  const xml = UTF8_DECODER.decode(documentXml);
  const html = docxXmlToHtml(xml, options);
  const text = html.replace(/<br\s*\/?>/giu, "\n").replace(/<\/p>|<\/h[1-3]>|<\/li>/giu, "\n").replace(/<[^>]+>/gu, "").replace(/\n{3,}/gu, "\n\n").trim();
  return Object.freeze({ format: "docx", html, text, preservedFormatting: true });
}

function pdfLiteral(value) {
  return value.replace(/\\([nrtbf()\\])/gu, (_match, code) => ({ n: "\n", r: "\r", t: "\t", b: "\b", f: "\f", "(": "(", ")": ")", "\\": "\\" })[code] ?? code).replace(/\\([0-7]{1,3})/gu, (_m, octal) => String.fromCharCode(parseInt(octal, 8)));
}

async function extractPdfStreamText(bytes) {
  const raw = LATIN1_DECODER.decode(bytes);
  const found = [];
  for (const match of raw.matchAll(/\(((?:\\.|[^\\)])*)\)\s*Tj/gu)) found.push(pdfLiteral(match[1]));
  for (const match of raw.matchAll(/\[((?:.|\n)*?)\]\s*TJ/gu)) {
    const parts = [...match[1].matchAll(/\(((?:\\.|[^\\)])*)\)/gu)].map((item) => pdfLiteral(item[1]));
    if (parts.length) found.push(parts.join(""));
  }
  return found.join("\n");
}

export async function importPdf(buffer) {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  if (LATIN1_DECODER.decode(bytes.subarray(0, 5)) !== "%PDF-") throw new Error("ملف PDF غير صالح");
  const raw = LATIN1_DECODER.decode(bytes);
  const chunks = [];
  let cursor = 0;
  while (true) {
    const streamAt = raw.indexOf("stream", cursor);
    if (streamAt < 0) break;
    let dataStart = streamAt + 6;
    if (raw[dataStart] === "\r" && raw[dataStart + 1] === "\n") dataStart += 2;
    else if (raw[dataStart] === "\n") dataStart += 1;
    const endAt = raw.indexOf("endstream", dataStart);
    if (endAt < 0) break;
    let dataEnd = endAt;
    while (dataEnd > dataStart && (raw[dataEnd - 1] === "\r" || raw[dataEnd - 1] === "\n")) dataEnd -= 1;
    let payload = bytes.subarray(dataStart, dataEnd);
    const dictionary = raw.slice(Math.max(0, streamAt - 400), streamAt);
    if (/\/FlateDecode\b/u.test(dictionary)) {
      if (typeof DecompressionStream !== "function") { cursor = endAt + 9; continue; }
      try {
        const inflated = new Blob([payload]).stream().pipeThrough(new DecompressionStream("deflate"));
        payload = new Uint8Array(await new Response(inflated).arrayBuffer());
      } catch { cursor = endAt + 9; continue; }
    }
    const text = await extractPdfStreamText(payload);
    if (text.trim()) chunks.push(text.trim());
    cursor = endAt + 9;
  }
  if (!chunks.length) throw new Error("تعذر استخراج طبقة النص من PDF؛ قد يكون ممسوحًا ضوئيًا أو يستخدم ترميزًا غير مدعوم محليًا");
  const text = chunks.join("\n\n");
  return Object.freeze({ format: "pdf", text, html: markdownToHtml(text), preservedFormatting: false, warning: "تم الحفاظ على ترتيب المقاطع قدر الإمكان؛ PDF ليس تنسيق تحرير دلاليًا." });
}

export async function importDocument(file, options = {}) {
  if (!file || typeof file.arrayBuffer !== "function") throw new TypeError("file must be a File-like object");
  if (Number(file.size) > 100 * 1024 * 1024) throw new RangeError("حجم المستند يتجاوز 100MB");
  const format = extension(file.name) || ({ "text/plain": "txt", "text/markdown": "md", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx", "application/pdf": "pdf" })[file.type];
  if (!IMPORT_FORMATS.includes(format)) throw new RangeError("صيغة المستند غير مدعومة");
  const buffer = await file.arrayBuffer();
  if (format === "docx") return { ...(await importDocx(buffer, options)), title: safeDocumentName(file.name) };
  if (format === "pdf") return { ...(await importPdf(buffer)), title: safeDocumentName(file.name) };
  const text = UTF8_DECODER.decode(buffer).replace(/^\uFEFF/u, "");
  const html = format === "md" ? markdownToHtml(text) : text.split(/\r?\n/gu).map((line) => `<p>${escapeHtml(line) || "<br>"}</p>`).join("\n");
  return Object.freeze({ format, text, html, title: safeDocumentName(file.name), preservedFormatting: format === "md" });
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i += 1) {
    let value = i;
    for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    table[i] = value >>> 0;
  }
  return table;
})();
function crc32(bytes) { let crc = 0xffffffff; for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8); return (crc ^ 0xffffffff) >>> 0; }
function write16(target, offset, value) { new DataView(target.buffer).setUint16(offset, value, true); }
function write32(target, offset, value) { new DataView(target.buffer).setUint32(offset, value >>> 0, true); }
function concat(parts) { const size = parts.reduce((sum, part) => sum + part.length, 0); const out = new Uint8Array(size); let offset = 0; for (const part of parts) { out.set(part, offset); offset += part.length; } return out; }

export function createStoredZip(entries) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const [name, content] of entries) {
    const nameBytes = UTF8.encode(name);
    const data = typeof content === "string" ? UTF8.encode(content) : new Uint8Array(content);
    const crc = crc32(data);
    const local = new Uint8Array(30 + nameBytes.length);
    write32(local, 0, 0x04034b50); write16(local, 4, 20); write16(local, 6, 0x0800); write16(local, 8, 0); write32(local, 14, crc); write32(local, 18, data.length); write32(local, 22, data.length); write16(local, 26, nameBytes.length); local.set(nameBytes, 30);
    locals.push(local, data);
    const central = new Uint8Array(46 + nameBytes.length);
    write32(central, 0, 0x02014b50); write16(central, 4, 20); write16(central, 6, 20); write16(central, 8, 0x0800); write16(central, 10, 0); write32(central, 16, crc); write32(central, 20, data.length); write32(central, 24, data.length); write16(central, 28, nameBytes.length); write32(central, 42, offset); central.set(nameBytes, 46);
    centrals.push(central);
    offset += local.length + data.length;
  }
  const central = concat(centrals);
  const eocd = new Uint8Array(22);
  write32(eocd, 0, 0x06054b50); write16(eocd, 8, entries.length); write16(eocd, 10, entries.length); write32(eocd, 12, central.length); write32(eocd, 16, offset);
  return concat([...locals, central, eocd]);
}

function htmlBlocks(html, domParser = globalThis.DOMParser) {
  if (!domParser) return [{ tag: "p", runs: [{ text: html.replace(/<[^>]+>/gu, ""), bold: false, italic: false, underline: false }] }];
  const document = new domParser().parseFromString(html, "text/html");
  const blocks = [];
  const walkRuns = (node, style = {}) => {
    if (node.nodeType === 3) return [{ text: node.data, ...style }];
    const tag = node.nodeName.toLowerCase();
    const next = { ...style, bold: style.bold || tag === "strong" || tag === "b", italic: style.italic || tag === "em" || tag === "i", underline: style.underline || tag === "u" };
    if (tag === "br") return [{ text: "\n", ...next }];
    return [...node.childNodes].flatMap((child) => walkRuns(child, next));
  };
  for (const node of document.body.children) {
    const tag = node.nodeName.toLowerCase();
    if (tag === "ul" || tag === "ol") {
      [...node.children].forEach((item, index) => blocks.push({ tag: "p", prefix: tag === "ol" ? `${index + 1}. ` : "• ", runs: walkRuns(item) }));
    } else blocks.push({ tag: /^h[1-3]$/u.test(tag) ? tag : "p", runs: walkRuns(node) });
  }
  return blocks.length ? blocks : [{ tag: "p", runs: [{ text: "", bold: false, italic: false, underline: false }] }];
}

export function createDocx(html, { domParser = globalThis.DOMParser } = {}) {
  const paragraphs = htmlBlocks(html, domParser).map((block) => {
    const style = block.tag === "h1" ? '<w:pPr><w:pStyle w:val="Heading1"/><w:bidi/></w:pPr>' : block.tag === "h2" ? '<w:pPr><w:pStyle w:val="Heading2"/><w:bidi/></w:pPr>' : '<w:pPr><w:bidi/></w:pPr>';
    const runs = [{ text: block.prefix || "", bold: false, italic: false, underline: false }, ...block.runs].map((run) => {
      const props = [run.bold ? "<w:b/>" : "", run.italic ? "<w:i/>" : "", run.underline ? '<w:u w:val="single"/>' : "", "<w:rtl/>", '<w:lang w:bidi="ar-SA"/>'].join("");
      return `<w:r><w:rPr>${props}</w:rPr><w:t xml:space="preserve">${escapeXml(run.text)}</w:t></w:r>`;
    }).join("");
    return `<w:p>${style}${runs}</w:p>`;
  }).join("");
  const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${paragraphs}<w:sectPr><w:bidi/><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>`;
  const contentTypes = `<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>`;
  const rels = `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>`;
  const docRels = `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>`;
  const styles = `<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr><w:rtl/><w:lang w:bidi="ar-SA"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:bidi/></w:pPr></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:bidi/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:bidi/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style></w:styles>`;
  return createStoredZip([["[Content_Types].xml", contentTypes], ["_rels/.rels", rels], ["word/document.xml", documentXml], ["word/_rels/document.xml.rels", docRels], ["word/styles.xml", styles]]);
}

export function downloadBlob(blob, filename, { document = globalThis.document, url = globalThis.URL } = {}) {
  if (!document || !url?.createObjectURL) throw new Error("تنزيل الملفات غير متاح في هذا السياق");
  const href = url.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href; anchor.download = filename; anchor.hidden = true;
  document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(() => url.revokeObjectURL(href), 1000);
}

export function exportDocument({ format, text, html = null, title = "مستند-ضاد", domParser = globalThis.DOMParser, window = globalThis.window } = {}) {
  if (!EXPORT_FORMATS.includes(format)) throw new RangeError("صيغة التصدير غير مدعومة");
  const base = safeDocumentName(title);
  if (format === "txt") return Object.freeze({ blob: new Blob([text], { type: "text/plain;charset=utf-8" }), filename: `${base}.txt` });
  if (format === "md") return Object.freeze({ blob: new Blob([html ? htmlToMarkdown(html, { domParser }) : text], { type: "text/markdown;charset=utf-8" }), filename: `${base}.md` });
  if (format === "docx") return Object.freeze({ blob: new Blob([createDocx(html || markdownToHtml(text), { domParser })], { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }), filename: `${base}.docx` });
  if (!window?.open) throw new Error("نافذة الطباعة غير متاحة");
  const popup = window.open("", "_blank", "noopener,noreferrer");
  if (!popup) throw new Error("منع المتصفح نافذة تصدير PDF");
  popup.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>${escapeHtml(base)}</title><style>@page{size:A4;margin:20mm}body{font-family:Tahoma,Arial,sans-serif;line-height:1.85;color:#111;direction:rtl}h1,h2,h3{page-break-after:avoid}p,li{orphans:3;widows:3}</style></head><body>${html || markdownToHtml(text)}<script>addEventListener('load',()=>setTimeout(()=>print(),50))<\/script></body></html>`);
  popup.document.close();
  return Object.freeze({ blob: null, filename: `${base}.pdf`, printWindow: popup });
}
