"use strict";

importScripts("shared.js");

const DEFAULT_SETTINGS = Object.freeze({
  enabled: true,
  apiBase: "http://127.0.0.1:8010",
  debounceMs: 700,
  categories: ["spelling", "grammar", "punctuation", "style", "dialect", "neural_suggestion", "consistency", "semantics"],
  showStyle: true,
  showDialect: true,
  rewriteMode: "formal",
});

function storageGet(keys) {
  return new Promise((resolve, reject) => {
    chrome.storage.sync.get(keys, (value) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(value);
    });
  });
}

function storageSet(value) {
  return new Promise((resolve, reject) => {
    chrome.storage.sync.set(value, () => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve();
    });
  });
}

function permissionsContains(origin) {
  return new Promise((resolve) => chrome.permissions.contains({ origins: [origin] }, resolve));
}

async function getSettings() {
  const stored = await storageGet(Object.keys(DEFAULT_SETTINGS));
  return { ...DEFAULT_SETTINGS, ...stored, apiBase: DhadShared.normalizeApiBase(stored.apiBase || DEFAULT_SETTINGS.apiBase) };
}

async function saveSettings(candidate) {
  const current = await getSettings();
  const next = {
    ...current,
    ...candidate,
    apiBase: DhadShared.normalizeApiBase(candidate.apiBase || current.apiBase),
    enabled: candidate.enabled === undefined ? current.enabled : Boolean(candidate.enabled),
    showStyle: candidate.showStyle === undefined ? current.showStyle : Boolean(candidate.showStyle),
    showDialect: candidate.showDialect === undefined ? current.showDialect : Boolean(candidate.showDialect),
    rewriteMode: ["formal", "concise", "expand", "creative", "academic"].includes(candidate.rewriteMode) ? candidate.rewriteMode : current.rewriteMode,
    debounceMs: Math.max(250, Math.min(3000, Number(candidate.debounceMs || current.debounceMs))),
    categories: Array.isArray(candidate.categories) ? [...new Set(candidate.categories.map(String))] : current.categories,
  };
  await storageSet(next);
  return next;
}

async function apiRequest(endpoint, payload) {
  const settings = await getSettings();
  if (!settings.enabled) throw new Error("إضافة ضاد متوقفة من الإعدادات");
  const origin = DhadShared.originPattern(settings.apiBase);
  if (!(await permissionsContains(origin))) {
    throw new Error("لا تملك الإضافة إذن الوصول إلى خادم ضاد المحدد. افتح نافذة الإضافة واحفظ الإعدادات.");
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(`${settings.apiBase}${endpoint}`, {
      method: payload === undefined ? "GET" : "POST",
      headers: payload === undefined ? { Accept: "application/json" } : {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      cache: "no-store",
      credentials: "omit",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`خادم ضاد أعاد HTTP ${response.status}`);
    return await response.json();
  } catch (error) {
    if (error.name === "AbortError") throw new Error("انتهت مهلة الاتصال بخادم ضاد");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

const ENDPOINTS = Object.freeze({
  DHAD_CHECK: ["/api/v1/check", (payload) => ({
    text: String(payload.text || ""),
    profiles: ["default"],
    disabled_rules: [],
    disabled_categories: [],
  })],
  DHAD_STYLE: ["/api/v1/style", (payload) => ({ text: String(payload.text || ""), profile: payload.profile || "general" })],
  DHAD_DIALECT: ["/api/v1/dialect", (payload) => ({ text: String(payload.text || "") })],
  DHAD_DIACRITIZE: ["/api/v1/diacritize", (payload) => ({ text: String(payload.text || ""), mode: payload.mode || "full", neural_refine: true })],
  DHAD_INTELLIGENCE: ["/api/v1/intelligence", (payload) => ({ text: String(payload.text || ""), profile: payload.profile || "general", custom_words: [], disabled_rules: [] })],
  DHAD_REWRITE: ["/api/v1/rewrite", (payload) => ({ text: String(payload.text || ""), mode: payload.mode || "formal", alternatives: Math.max(1, Math.min(3, Number(payload.alternatives || 3))) })],
  DHAD_ANALYTICS: ["/api/v1/analytics", (payload) => ({ text: String(payload.text || "") })],
  DHAD_TEMPLATES: ["/api/v1/templates", () => undefined],
  DHAD_GENERATE_TEMPLATE: ["/api/v1/templates/generate", (payload) => ({ template_id: String(payload.templateId || "professional_email"), values: payload.values || {}, tone: payload.tone || null })],
  DHAD_HEALTH: ["/api/health", () => undefined],
});

chrome.runtime.onInstalled.addListener(() => {
  getSettings().then((settings) => storageSet(settings)).catch(() => undefined);
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (!message || typeof message.type !== "string") throw new Error("رسالة إضافة غير صالحة");
    if (message.type === "DHAD_GET_SETTINGS") return { ok: true, data: await getSettings() };
    if (message.type === "DHAD_SET_SETTINGS") return { ok: true, data: await saveSettings(message.payload || {}) };
    const route = ENDPOINTS[message.type];
    if (!route) throw new Error(`نوع رسالة غير مدعوم: ${message.type}`);
    const [endpoint, buildPayload] = route;
    return { ok: true, data: await apiRequest(endpoint, buildPayload(message.payload || {})) };
  })().then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
  return true;
});
