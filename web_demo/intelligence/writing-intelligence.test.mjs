import assert from "node:assert/strict";
import test from "node:test";

import {
  analyzeWriting,
  applyLocalOverrides,
  buildExplanations,
  createDialectMatches,
  guidanceForTarget,
  normalizeArabic,
  parseLexiconInput,
} from "./writing-intelligence.js";

test("tone intelligence ranks academic and persuasive evidence transparently", () => {
  const report = analyzeWriting("تشير النتائج إلى تحسن واضح، لذلك نوصي بتطبيق الخطة.");
  assert.equal(report.tone.primary, "persuasive");
  assert.ok(report.tone.scores.academic > report.tone.scores.casual);
  assert.ok(report.tone.evidence.some((item) => item.text === "تشير النتائج"));
  assert.equal(report.suggestionChips.length, 4);
  assert.equal(guidanceForTarget(report, "persuasive").target, "persuasive");
});

test("dialect bridge preserves code-point offsets and creates review-only matches", () => {
  const text = "هسه شلون نكتب التقرير؟";
  const report = analyzeWriting(text);
  assert.equal(report.dialect.primary, "iraqi");
  assert.equal(report.dialect.convertedText, "الآن كيف نكتب التقرير؟");
  const [first, second] = report.dialect.conversions;
  assert.equal(Array.from(text).slice(first.offset, first.offset + first.length).join(""), "هسه");
  assert.equal(Array.from(text).slice(second.offset, second.offset + second.length).join(""), "شلون");
  const matches = createDialectMatches(report.dialect);
  assert.equal(matches.length, 2);
  assert.ok(matches.every((item) => item.autofix === false && item.category === "dialect"));
});

test("readability exposes clarity, richness, density, and complexity bounds", () => {
  const report = analyzeWriting(
    "توضح الدراسة النتائج. وتشرح المنهجية خطوات التحليل، وأسباب الاختيار، وحدود البيانات.",
  );
  const metrics = report.readability;
  assert.equal(metrics.sentences, 2);
  assert.ok(metrics.words >= metrics.uniqueWords);
  assert.ok(metrics.lexicalRichness > 0 && metrics.lexicalRichness <= 1);
  assert.ok(metrics.hapaxRatio >= 0 && metrics.hapaxRatio <= 1);
  assert.ok(metrics.averageClausesPerSentence >= 1);
  assert.ok(metrics.clarityScore >= 0 && metrics.clarityScore <= 100);
  assert.ok(metrics.complexityScore >= 0 && metrics.complexityScore <= 100);
});

test("custom lexicon parser normalizes duplicates and enforces hard bounds", () => {
  assert.deepEqual(parseLexiconInput("ضاد\nضَاد، مصطلح خاص"), ["ضاد", "مصطلح خاص"]);
  assert.equal(normalizeArabic("مُصْطَلَحـ"), "مصطلح");
  assert.throws(() => parseLexiconInput("أ\nب\nج", { limit: 2 }), /exceeds 2 entries/u);
  assert.throws(() => parseLexiconInput("كلمةطويلة", { wordLimit: 4 }), /exceeds 4 characters/u);
});

test("local lexicon and rule overrides filter diagnostics without mutating input", () => {
  const text = "ذهبت الى السوق";
  const matches = [
    { rule_id: "HAMZA_ILA", category: "spelling", offset: 5, length: 3, replacements: ["إلى"] },
    { rule_id: "OTHER", category: "style", offset: 0, length: 4, replacements: [] },
  ];
  const filtered = applyLocalOverrides(matches, text, {
    customWords: ["الى"],
    disabledRules: ["OTHER"],
  });
  assert.deepEqual(filtered, []);
  assert.equal(matches.length, 2);
});

test("interactive explanations provide fallback reasoning for every diagnostic", () => {
  const matches = [
    {
      rule_id: "GRAMMAR_X",
      category: "grammar",
      message: "راجع المطابقة.",
      explanation: "",
      offset: 0,
      length: 3,
      replacements: ["هذه"],
      confidence: 0.9,
      autofix: true,
    },
  ];
  const explanations = buildExplanations(matches, "هذا كتاب");
  assert.equal(explanations.length, 1);
  assert.equal(explanations[0].sourceText, "هذا");
  assert.equal(explanations[0].reasoning, "راجع المطابقة.");
  assert.match(explanations[0].whyItMatters, /النحوية/u);
  assert.equal(explanations[0].decision, "safe_autofix");
});
