const ARABIC_WORD = /[\u0600-\u06FF]+/gu;
const SENTENCE = /[^.!؟!؛…]+[.!؟!؛…]?/gu;

function clamp(value, min = 0, max = 100) { return Math.min(max, Math.max(min, value)); }
function words(text) { return text.match(ARABIC_WORD) ?? []; }
function heat(complexity) { return complexity < 28 ? "cool" : complexity < 52 ? "balanced" : complexity < 72 ? "warm" : "hot"; }

export function sentenceHeatmap(text, sentenceTones = []) {
  if (typeof text !== "string") throw new TypeError("text must be a string");
  const insights = [];
  const pattern = new RegExp(SENTENCE.source, SENTENCE.flags);
  let match;
  let index = 0;
  while ((match = pattern.exec(text)) !== null) {
    const sentence = match[0];
    if (!sentence.trim()) continue;
    const tokens = words(sentence);
    const punctuation = [...sentence].filter((char) => "،؛:(".includes(char)).length;
    const longWords = tokens.filter((token) => token.length >= 8).length;
    const complexity = clamp(Math.max(0, tokens.length - 12) * 2.8 + punctuation * 7 + longWords * 1.8);
    const tone = sentenceTones[index] ?? null;
    insights.push(Object.freeze({
      index,
      text: sentence.trim(),
      start: match.index,
      end: match.index + sentence.length,
      words: tokens.length,
      clarityScore: clamp(100 - complexity * 0.72),
      complexityScore: complexity,
      tone: tone?.primary ?? "neutral",
      toneConfidence: tone?.confidence ?? 0,
      heat: heat(complexity),
    }));
    index += 1;
  }
  return Object.freeze(insights);
}

export function advancedAnalytics(text, intelligence = null) {
  if (typeof text !== "string") throw new TypeError("text must be a string");
  const tokenList = words(text);
  const unique = new Set(tokenList.map((item) => item.normalize("NFKC")));
  const sentenceTones = intelligence?.sentenceTones ?? [];
  const heatmap = sentenceHeatmap(text, sentenceTones);
  const clarity = Number.isFinite(intelligence?.readability?.clarityScore) ? intelligence.readability.clarityScore : (heatmap.length ? heatmap.reduce((sum, item) => sum + item.clarityScore, 0) / heatmap.length : 100);
  const complexity = Number.isFinite(intelligence?.vocabulary?.complexityScore) ? intelligence.vocabulary.complexityScore : clamp(100 - clarity);
  const questions = (text.match(/[؟?]/gu) ?? []).length;
  const directMarkers = (text.match(/(?:لذلك|لأن|مثال|النتيجة)/gu) ?? []).length;
  const mean = heatmap.length ? heatmap.reduce((sum, item) => sum + item.words, 0) / heatmap.length : 0;
  const variety = heatmap.length > 1 && mean ? Math.min(1, heatmap.reduce((sum, item) => sum + Math.abs(item.words - mean), 0) / (heatmap.length * mean)) : 0;
  const engagement = clamp(clarity * 0.52 + Math.min(15, questions * 3) + Math.min(12, directMarkers * 2) + variety * 14 + Math.min(7, (unique.size / Math.max(tokenList.length, 1)) * 10));
  const toneScores = intelligence?.tone?.scores ?? {};
  const values = Object.values(toneScores).filter((value) => Number.isFinite(value) && value > 0);
  let entropy = 0;
  if (values.length > 1) entropy = -values.reduce((sum, value) => sum + value * Math.log2(value), 0) / Math.log2(values.length);
  return Object.freeze({
    words: tokenList.length,
    characters: text.length,
    sentences: heatmap.length,
    paragraphs: text.trim() ? text.split(/\n\s*\n/gu).filter((part) => part.trim()).length : 0,
    estimatedReadingSeconds: tokenList.length ? Math.ceil((tokenList.length / 180) * 60) : 0,
    estimatedSpeakingSeconds: tokenList.length ? Math.ceil((tokenList.length / 130) * 60) : 0,
    engagementScore: engagement,
    clarityScore: clamp(clarity),
    complexityScore: clamp(complexity),
    vocabularyRichness: tokenList.length ? (unique.size / tokenList.length) * 100 : 0,
    toneBalance: Object.freeze({ scores: Object.freeze({ ...toneScores }), dominant: intelligence?.tone?.primary ?? "neutral", balanceScore: clamp(entropy * 100) }),
    sentenceHeatmap: heatmap,
  });
}

export function analyticsTrend(history, current) {
  if (!Array.isArray(history)) throw new TypeError("history must be an array");
  const previous = [...history].reverse().find((item) => item && typeof item === "object") ?? null;
  const delta = (key) => previous && Number.isFinite(previous[key]) ? current[key] - previous[key] : 0;
  return Object.freeze({
    clarityDelta: delta("clarityScore"),
    engagementDelta: delta("engagementScore"),
    richnessDelta: delta("vocabularyRichness"),
    complexityDelta: delta("complexityScore"),
    hasBaseline: Boolean(previous),
  });
}
