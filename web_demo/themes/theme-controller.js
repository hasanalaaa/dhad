export const THEMES = Object.freeze({
  system: Object.freeze({ label: "تلقائي", scheme: "system" }),
  light: Object.freeze({ label: "فاتح", scheme: "light" }),
  dark: Object.freeze({ label: "داكن", scheme: "dark" }),
  contrast: Object.freeze({ label: "تباين عالٍ", scheme: "dark" }),
});

export function resolveTheme(preference = "system", prefersDark = false) {
  if (!(preference in THEMES)) throw new RangeError("unsupported theme");
  return preference === "system" ? (prefersDark ? "dark" : "light") : preference;
}

export function applyTheme(root, preference = "system", prefersDark = false) {
  if (!root?.dataset || typeof root.setAttribute !== "function") throw new TypeError("root must be an Element-like object");
  const resolved = resolveTheme(preference, prefersDark);
  root.dataset.theme = resolved;
  root.setAttribute("data-theme-preference", preference);
  root.style?.setProperty?.("color-scheme", resolved === "light" ? "light" : "dark");
  return resolved;
}

export class ThemeController {
  constructor({ root = document.documentElement, matchMedia = globalThis.matchMedia?.bind(globalThis), storage = null } = {}) {
    this.root = root;
    this.media = matchMedia?.("(prefers-color-scheme: dark)") ?? null;
    this.storage = storage;
    this.preference = "system";
    this.onSystemChange = () => this.apply();
  }
  async initialize(preference = null) {
    const stored = preference ?? await this.storage?.getSetting?.("theme") ?? "system";
    this.setPreference(stored, { persist: false });
    this.media?.addEventListener?.("change", this.onSystemChange);
    return this.preference;
  }
  apply() { return applyTheme(this.root, this.preference, Boolean(this.media?.matches)); }
  setPreference(preference, { persist = true } = {}) {
    if (!(preference in THEMES)) throw new RangeError("unsupported theme");
    this.preference = preference;
    this.apply();
    if (persist) void this.storage?.setSetting?.("theme", preference);
    return preference;
  }
  dispose() { this.media?.removeEventListener?.("change", this.onSystemChange); }
}
