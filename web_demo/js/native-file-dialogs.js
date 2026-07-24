import { isTauriEnvironment } from "./desktop-adapter.js";

const DOCUMENT_FILTER = Object.freeze({
  name: "مستندات ضاد",
  extensions: ["txt", "md", "docx", "pdf"],
});

const FORMAT_FILTERS = Object.freeze({
  txt: Object.freeze({ name: "نص عادي", extensions: ["txt"] }),
  md: Object.freeze({ name: "Markdown", extensions: ["md"] }),
  docx: Object.freeze({ name: "Microsoft Word", extensions: ["docx"] }),
  pdf: Object.freeze({ name: "PDF", extensions: ["pdf"] }),
});

const MIME_TYPES = Object.freeze({
  txt: "text/plain;charset=utf-8",
  md: "text/markdown;charset=utf-8",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  pdf: "application/pdf",
});

function tauriRoot() {
  return globalThis.window?.__TAURI__ ?? globalThis.__TAURI__ ?? null;
}

function dialogApi() {
  return tauriRoot()?.dialog ?? null;
}

function invokeApi() {
  return tauriRoot()?.core?.invoke ?? null;
}

export function nativeDocumentDialogsAvailable() {
  const dialog = dialogApi();
  return isTauriEnvironment()
    && typeof dialog?.open === "function"
    && typeof dialog?.save === "function"
    && typeof invokeApi() === "function";
}

export async function pickNativeDocument() {
  if (!nativeDocumentDialogsAvailable()) return null;
  const selection = await dialogApi().open({
    multiple: false,
    directory: false,
    title: "استيراد مستند إلى ضاد",
    filters: [DOCUMENT_FILTER],
  });
  const path = Array.isArray(selection) ? selection[0] : selection;
  if (!path) return null;

  const payload = await invokeApi()("read_document_file", { request: { path } });
  const bytes = payload?.bytes instanceof Uint8Array
    ? payload.bytes
    : new Uint8Array(Array.isArray(payload?.bytes) ? payload.bytes : []);
  const extension = String(payload?.extension || "").toLowerCase();
  const file = new File([bytes], payload?.name || `document.${extension || "txt"}`, {
    type: MIME_TYPES[extension] || "application/octet-stream",
    lastModified: Date.now(),
  });
  return Object.freeze({ file, path: payload?.path || path, sizeBytes: payload?.sizeBytes ?? bytes.byteLength });
}

export async function saveNativeDocument(blob, filename, format) {
  if (!nativeDocumentDialogsAvailable()) return null;
  if (!(blob instanceof Blob)) throw new TypeError("blob must be a Blob");
  const normalizedFormat = String(format || "").toLowerCase();
  const filter = FORMAT_FILTERS[normalizedFormat];
  if (!filter) throw new RangeError("unsupported native export format");

  const path = await dialogApi().save({
    title: "تصدير مستند ضاد",
    defaultPath: filename,
    filters: [filter],
  });
  if (!path) return null;

  const bytes = Array.from(new Uint8Array(await blob.arrayBuffer()));
  return invokeApi()("write_document_file", {
    request: {
      path,
      format: normalizedFormat,
      bytes,
    },
  });
}
