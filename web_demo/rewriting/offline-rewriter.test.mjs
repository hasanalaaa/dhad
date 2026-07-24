import assert from "node:assert/strict";
import test from "node:test";
import { REWRITE_MODES, rewriteText } from "./offline-rewriter.js";

test("rewriter exposes all five Gold modes and deterministic bounded alternatives", () => {
  assert.deepEqual(Object.keys(REWRITE_MODES), ["formal", "concise", "expand", "creative", "academic"]);
  for (const mode of Object.keys(REWRITE_MODES)) {
    const first = rewriteText("في واقع الأمر، أعتقد أن هذا شيء مهم. لذلك نراجع الخطة.", mode);
    const second = rewriteText("في واقع الأمر، أعتقد أن هذا شيء مهم. لذلك نراجع الخطة.", mode);
    assert.deepEqual(first, second);
    assert.ok(first.candidates.length >= 1 && first.candidates.length <= 3);
    assert.ok(first.candidates.every((candidate) => candidate.meaningPreservation >= 0.72));
  }
});

test("formal rewriting consumes reviewed dialect offsets without inventing content", () => {
  const source = "هسه شلون نكتب التقرير؟";
  const report = rewriteText(source, "formal", { dialectConversions: [
    { source: "هسه", replacement: "الآن", offset: 0, length: 3 },
    { source: "شلون", replacement: "كيف", offset: 4, length: 4 },
  ] });
  assert.match(report.candidates[0].text, /الآن كيف/u);
  assert.ok(report.candidates[0].changes.every((change) => source.includes(change.source) || change.source === ""));
});

test("rewriter validates mode, text and alternative bounds", () => {
  assert.throws(() => rewriteText(42), /text must be a string/u);
  assert.throws(() => rewriteText("نص", "unknown"), /unsupported rewrite mode/u);
  assert.throws(() => rewriteText("نص", "formal", { alternatives: 4 }), /between one and three/u);
});
