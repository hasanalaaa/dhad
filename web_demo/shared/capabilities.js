export const GOLD_CAPABILITIES = Object.freeze({
  check: Object.freeze({ endpoint: "/api/v1/check", offline: true }),
  intelligence: Object.freeze({ endpoint: "/api/v1/intelligence", offline: true }),
  rewrite: Object.freeze({ endpoint: "/api/v1/rewrite", offline: true, modes: Object.freeze(["formal", "concise", "expand", "creative", "academic"]) }),
  analytics: Object.freeze({ endpoint: "/api/v1/analytics", offline: true }),
  templates: Object.freeze({ endpoint: "/api/v1/templates", offline: true }),
  documents: Object.freeze({ formats: Object.freeze(["txt", "md", "docx", "pdf"]) }),
  themes: Object.freeze({ values: Object.freeze(["system", "light", "dark", "contrast"]) }),
});

export function assertCapabilityParity(surface) {
  const required = Object.keys(GOLD_CAPABILITIES);
  const missing = required.filter((key) => !surface?.[key]);
  if (missing.length) throw new Error(`missing Gold capabilities: ${missing.join(", ")}`);
  return true;
}
