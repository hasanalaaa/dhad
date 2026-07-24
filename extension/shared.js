"use strict";

(function exposeShared(globalObject) {
  function normalizeApiBase(value) {
    const raw = String(value || "").trim();
    const parsed = new URL(raw || "http://127.0.0.1:8010");
    if (!/^https?:$/.test(parsed.protocol)) throw new Error("عنوان الخادم يجب أن يستخدم HTTP أو HTTPS");
    parsed.username = "";
    parsed.password = "";
    parsed.hash = "";
    parsed.search = "";
    return parsed.href.replace(/\/$/, "");
  }

  function nonOverlappingMatches(matches) {
    const sorted = [...(matches || [])].sort((a, b) => a.offset - b.offset || b.length - a.length || (b.priority || 0) - (a.priority || 0));
    const accepted = [];
    let end = -1;
    for (const item of sorted) {
      const offset = Number(item.offset);
      const length = Number(item.length);
      if (!Number.isInteger(offset) || !Number.isInteger(length) || offset < 0 || length <= 0 || offset < end) continue;
      accepted.push(item);
      end = offset + length;
    }
    return accepted;
  }

  function applyTextReplacement(text, offset, length, replacement) {
    const source = String(text);
    const start = Math.max(0, Math.min(source.length, Number(offset)));
    const end = Math.max(start, Math.min(source.length, start + Number(length)));
    return source.slice(0, start) + String(replacement) + source.slice(end);
  }

  function originPattern(apiBase) {
    const parsed = new URL(normalizeApiBase(apiBase));
    return `${parsed.protocol}//${parsed.host}/*`;
  }

  const GOLD_CAPABILITIES = Object.freeze({
    check: true, intelligence: true, rewrite: true, analytics: true, templates: true,
    documents: true, themes: true,
  });

  globalObject.DhadShared = Object.freeze({
    GOLD_CAPABILITIES,
    normalizeApiBase,
    nonOverlappingMatches,
    applyTextReplacement,
    originPattern,
  });
})(globalThis);
