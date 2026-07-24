import assert from "node:assert/strict";
import test from "node:test";
import { advancedAnalytics, analyticsTrend, sentenceHeatmap } from "./writing-analytics.js";

test("analytics produces bounded document metrics and sentence heatmap offsets", () => {
  const text = "هذه جملة واضحة. وهذه جملة أطول، تحتوي على تفاصيل متعددة، وتحتاج إلى مراجعة؟";
  const metrics = advancedAnalytics(text);
  assert.equal(metrics.sentences, 2);
  assert.ok(metrics.estimatedReadingSeconds > 0);
  for (const key of ["clarityScore", "complexityScore", "engagementScore", "vocabularyRichness"]) assert.ok(metrics[key] >= 0 && metrics[key] <= 100);
  for (const item of sentenceHeatmap(text)) assert.equal(text.slice(item.start, item.end).trim(), item.text);
});

test("analytics trend compares with the most recent baseline", () => {
  const trend = analyticsTrend([{ clarityScore: 70, engagementScore: 40, vocabularyRichness: 50, complexityScore: 30 }], { clarityScore: 80, engagementScore: 45, vocabularyRichness: 48, complexityScore: 25 });
  assert.equal(trend.clarityDelta, 10);
  assert.equal(trend.complexityDelta, -5);
  assert.equal(trend.hasBaseline, true);
});
