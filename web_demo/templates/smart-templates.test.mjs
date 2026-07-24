import assert from "node:assert/strict";
import test from "node:test";
import { SMART_TEMPLATES, generateFromTemplate } from "./smart-templates.js";

test("Gold templates cover core professional writing jobs", () => {
  assert.deepEqual(SMART_TEMPLATES.map((item) => item.id), ["professional_email", "academic_abstract", "cover_letter", "social_post", "meeting_summary", "executive_brief"]);
});

test("template generation never hides missing required facts", () => {
  const draft = generateFromTemplate("academic_abstract", { objective: "قياس الأثر" });
  assert.ok(draft.missingFields.includes("results"));
  assert.match(draft.text, /\[النتائج الفعلية\]/u);
  assert.equal(draft.offline, true);
});

test("template generation rejects undeclared fields and invalid tones", () => {
  assert.throws(() => generateFromTemplate("professional_email", { secret: "x" }), /unknown template field/u);
  assert.throws(() => generateFromTemplate("professional_email", {}, { tone: "academic" }), /unsupported template tone/u);
});
