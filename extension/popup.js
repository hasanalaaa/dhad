"use strict";

const $ = (id) => document.getElementById(id);

function sendMessage(type, payload = {}) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ type, payload }, (response) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      if (!response?.ok) return reject(new Error(response?.error || "فشل الطلب"));
      resolve(response.data);
    });
  });
}

function requestOrigin(origin) {
  return new Promise((resolve) => chrome.permissions.request({ origins: [origin] }, resolve));
}

function setStatus(message, state = "idle") {
  $("status").textContent = message;
  $("status").dataset.state = state;
}

async function save() {
  try {
    const apiBase = DhadShared.normalizeApiBase($("apiBase").value);
    const origin = DhadShared.originPattern(apiBase);
    const granted = await requestOrigin(origin);
    if (!granted) throw new Error("لم تمنح المتصفح إذن الاتصال بهذا الخادم");
    await sendMessage("DHAD_SET_SETTINGS", {
      enabled: $("enabled").checked,
      apiBase,
      showStyle: $("showStyle").checked,
      showDialect: $("showDialect").checked,
      rewriteMode: $("rewriteMode").value,
      debounceMs: Number($("debounceMs").value),
    });
    setStatus("حُفظت الإعدادات.", "ok");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function testConnection() {
  try {
    await save();
    const health = await sendMessage("DHAD_HEALTH");
    setStatus(`متصل بضاد v${health.version} — ${health.rules} قاعدة`, "ok");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function initialize() {
  try {
    const settings = await sendMessage("DHAD_GET_SETTINGS");
    $("enabled").checked = settings.enabled;
    $("apiBase").value = settings.apiBase;
    $("showStyle").checked = settings.showStyle;
    $("showDialect").checked = settings.showDialect;
    $("rewriteMode").value = settings.rewriteMode || "formal";
    $("debounceMs").value = String(settings.debounceMs);
  } catch (error) {
    setStatus(error.message, "error");
  }
  $("saveButton").addEventListener("click", save);
  $("testButton").addEventListener("click", testConnection);
}

document.addEventListener("DOMContentLoaded", initialize);
