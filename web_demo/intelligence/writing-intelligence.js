const ARABIC_WORD = /[\p{Script=Arabic}][\p{Script=Arabic}\p{M}ـ]*/gu;
const SENTENCE = /[^.!؟!؛…]+[.!؟!؛…]?/gu;
const DIACRITICS = /[\u064B-\u065F\u0670\u06D6-\u06ED]/gu;
const TATWEEL = /ـ/gu;

const TONE_SIGNALS = Object.freeze({
  academic: Object.freeze([
    ["تشير الدراسة", 2.2, "إحالة مباشرة إلى دراسة أو بحث"],
    ["تشير النتائج", 2.2, "ربط الاستنتاج بنتائج قابلة للفحص"],
    ["وفقًا للبيانات", 2.0, "إسناد الفكرة إلى بيانات"],
    ["المنهجية", 1.6, "مفردة بحثية منهجية"],
    ["الفرضية", 1.6, "مفردة بحثية تحليلية"],
    ["التحليل", 1.2, "مفردة أكاديمية تفسيرية"],
  ]),
  formal: Object.freeze([
    ["يرجى", 2.1, "صيغة طلب رسمية"],
    ["نفيدكم", 2.2, "صيغة مراسلات إدارية"],
    ["بموجب", 1.7, "رابط قانوني أو إداري"],
    ["حضرتكم", 1.5, "مخاطبة رسمية"],
    ["مع التقدير", 1.4, "خاتمة مهنية"],
  ]),
  casual: Object.freeze([
    ["يا جماعة", 2.2, "نداء محادثي مباشر"],
    ["بصراحة", 1.7, "تمهيد شخصي محادثي"],
    ["برأيي", 1.6, "إبداء رأي شخصي مباشر"],
    ["خلينا", 2.0, "صيغة محادثية"],
    ["شلون", 2.0, "لفظ لهجي محادثي"],
    ["هواي", 1.8, "لفظ لهجي محادثي"],
  ]),
  persuasive: Object.freeze([
    ["ندعو", 2.1, "دعوة صريحة إلى فعل"],
    ["من الضروري", 2.0, "توكيد الحاجة إلى الإجراء"],
    ["لذلك", 1.4, "ربط السبب بالنتيجة"],
    ["نوصي", 2.0, "توصية عملية"],
    ["يجب", 1.5, "إلزام أو حث مباشر"],
    ["لأن", 1.1, "تقديم سبب داعم"],
  ]),
});

const DIALECT_TERMS = new Map(
  [
    ["شلون", ["iraqi", "كيف", "أداة استفهام عراقية وخليجية شائعة."]],
    ["شنو", ["iraqi", "ماذا", "أداة استفهام عراقية."]],
    ["هواي", ["iraqi", "كثيرًا", "ظرف مقدار عراقي."]],
    ["هسه", ["iraqi", "الآن", "ظرف زمان عراقي."]],
    ["اكو", ["iraqi", "يوجد", "فعل وجود في اللهجة العراقية."]],
    ["أكو", ["iraqi", "يوجد", "فعل وجود في اللهجة العراقية."]],
    ["ماكو", ["iraqi", "لا يوجد", "نفي الوجود في اللهجة العراقية."]],
    ["كلش", ["iraqi", "جدًا", "أداة تقوية عراقية."]],
    ["باچر", ["iraqi", "غدًا", "ظرف زمان عراقي."]],
    ["رح", ["shared", "سوف", "أداة استقبال لهجية."]],
    ["عايز", ["egyptian", "أريد", "فعل رغبة مصري."]],
    ["عايزة", ["egyptian", "أريد", "فعل رغبة مصري مؤنث."]],
    ["دلوقتي", ["egyptian", "الآن", "ظرف زمان مصري."]],
    ["ازاي", ["egyptian", "كيف", "أداة استفهام مصرية."]],
    ["كده", ["egyptian", "هكذا", "اسم إشارة إلى الهيئة في المصرية."]],
    ["اوي", ["egyptian", "جدًا", "أداة تقوية مصرية."]],
    ["شو", ["levantine", "ماذا", "أداة استفهام شامية."]],
    ["هلّق", ["levantine", "الآن", "ظرف زمان شامي."]],
    ["هلق", ["levantine", "الآن", "ظرف زمان شامي."]],
    ["كتير", ["levantine", "كثيرًا", "ظرف مقدار شامي."]],
    ["ليش", ["shared", "لماذا", "أداة استفهام لهجية."]],
    ["وايد", ["gulf", "كثيرًا", "ظرف مقدار خليجي."]],
    ["الحين", ["gulf", "الآن", "ظرف زمان خليجي."]],
    ["مب", ["gulf", "ليس", "أداة نفي خليجية."]],
    ["وش", ["gulf", "ماذا", "أداة استفهام خليجية."]],
    ["مو", ["shared", "ليس", "أداة نفي لهجية مشتركة."]],
    ["مش", ["shared", "ليس", "أداة نفي لهجية مشتركة."]],
  ].map(([source, value]) => [normalizeArabic(source), Object.freeze(value)]),
);

const CHIP_LIBRARY = Object.freeze({
  academic: Object.freeze({
    id: "tone:academic",
    target: "academic",
    label: "أكاديمي",
    rationale: "اربط الادعاءات بالأدلة واجعل المصطلحات أكثر تحديدًا.",
    actions: Object.freeze([
      "ابدأ الاستنتاج بعبارة مثل «تشير النتائج إلى…».",
      "عرّف المصطلح عند أول ظهور.",
      "استبدل الرأي الشخصي بوصف قابل للتحقق.",
    ]),
  }),
  formal: Object.freeze({
    id: "tone:formal",
    target: "formal",
    label: "رسمي",
    rationale: "وحّد السجل المهني واستبدل الألفاظ المحادثية بمقابلات فصيحة.",
    actions: Object.freeze([
      "استخدم صيغة طلب واضحة ومهذبة.",
      "احذف النداءات الشخصية غير الضرورية.",
      "استخدم أفعالًا مباشرة بدل التراكيب المطولة.",
    ]),
  }),
  casual: Object.freeze({
    id: "tone:casual",
    target: "casual",
    label: "ودّي",
    rationale: "بسّط الجمل مع إبقاء الإملاء والمعنى سليمين.",
    actions: Object.freeze([
      "قصّر الجملة الطويلة إلى فكرتين.",
      "استخدم مفردات يومية مألوفة.",
      "خاطب القارئ مباشرة عندما يناسب السياق.",
    ]),
  }),
  persuasive: Object.freeze({
    id: "tone:persuasive",
    target: "persuasive",
    label: "إقناعي",
    rationale: "حوّل الفكرة إلى حجة مدعومة تنتهي بخطوة عملية.",
    actions: Object.freeze([
      "اربط التوصية بسبب محدد.",
      "اذكر النتيجة المتوقعة للقارئ.",
      "اختم بطلب واضح قابل للتنفيذ.",
    ]),
  }),
});

const CATEGORY_REASON = Object.freeze({
  spelling: "يحافظ الرسم الإملائي المعياري على وضوح الكلمة وإمكان البحث عنها.",
  grammar: "يضبط هذا الاقتراح العلاقة النحوية ويقلل التباس المعنى.",
  punctuation: "يساعد الترقيم القارئ على تقسيم الفكرة وإيقاع الجملة.",
  style: "ملاحظة اختيارية لتحسين الإيجاز والوضوح واتساق النبرة.",
  dialect: "مقابل فصيح مقترح؛ يبقى القرار النهائي للكاتب.",
  tashkeel: "تشكيل مقترح لتقليل اللبس في القراءة.",
  neural_suggestion: "اقتراح سياقي احتمالي لا يُطبّق تلقائيًا.",
});

export function normalizeArabic(value) {
  if (typeof value !== "string") throw new TypeError("Arabic text must be a string");
  return value.normalize("NFC").replace(DIACRITICS, "").replace(TATWEEL, "").trim();
}

function utf16ToCodePointMap(text) {
  const map = new Uint32Array(text.length + 1);
  let codePoints = 0;
  for (let index = 0; index < text.length;) {
    const width = text.codePointAt(index) > 0xffff ? 2 : 1;
    map[index] = codePoints;
    if (width === 2) map[index + 1] = codePoints;
    index += width;
    codePoints += 1;
  }
  map[text.length] = codePoints;
  return map;
}

function arabicTokens(text) {
  const offsetMap = utf16ToCodePointMap(text);
  return [...text.matchAll(ARABIC_WORD)].map((match) => Object.freeze({
    text: match[0],
    normalized: normalizeArabic(match[0]),
    utf16Start: match.index,
    utf16End: match.index + match[0].length,
    offset: offsetMap[match.index],
    length: offsetMap[match.index + match[0].length] - offsetMap[match.index],
  }));
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function classifyTone(text) {
  const rawScores = { academic: 0.45, formal: 0.45, casual: 0.45, persuasive: 0.45 };
  const evidence = [];
  const offsetMap = utf16ToCodePointMap(text);
  for (const [tone, signals] of Object.entries(TONE_SIGNALS)) {
    for (const [phrase, weight, reason] of signals) {
      let cursor = 0;
      while (cursor < text.length) {
        const index = text.indexOf(phrase, cursor);
        if (index < 0) break;
        rawScores[tone] += weight;
        evidence.push(Object.freeze({
          tone,
          text: phrase,
          offset: offsetMap[index],
          length: offsetMap[index + phrase.length] - offsetMap[index],
          weight,
          reason,
        }));
        cursor = index + phrase.length;
      }
    }
  }
  const total = Object.values(rawScores).reduce((sum, value) => sum + value, 0);
  const scores = Object.fromEntries(
    Object.entries(rawScores).map(([tone, value]) => [tone, value / total]),
  );
  const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const [primary, top] = ranked[0];
  const second = ranked[1]?.[1] ?? 0;
  return Object.freeze({
    primary,
    confidence: clamp(0.35 + (top - second) * 2.4 + Math.min(evidence.length, 5) * 0.04, 0, 1),
    scores: Object.freeze(scores),
    evidence: Object.freeze(evidence),
  });
}

function readability(text, tokens) {
  const sentences = [...text.matchAll(SENTENCE)]
    .map((match) => match[0].trim())
    .filter(Boolean);
  const normalized = tokens.map((token) => token.normalized).filter(Boolean);
  const words = normalized.length;
  const uniqueWords = new Set(normalized).size;
  const frequencies = new Map();
  for (const word of normalized) frequencies.set(word, (frequencies.get(word) ?? 0) + 1);
  const averageWordsPerSentence = words / Math.max(1, sentences.length);
  const averageCharactersPerWord = words
    ? normalized.reduce((sum, word) => sum + Array.from(word).length, 0) / words
    : 0;
  const longWordRatio = words
    ? normalized.filter((word) => Array.from(word).length >= 8).length / words
    : 0;
  const repeatedWordRatio = words > 1
    ? normalized.slice(1).filter((word, index) => word === normalized[index]).length / (words - 1)
    : 0;
  const lexicalRichness = words ? uniqueWords / words : 0;
  const hapaxRatio = uniqueWords
    ? [...frequencies.values()].filter((count) => count === 1).length / uniqueWords
    : 0;
  const clauseCounts = sentences.map(
    (sentence) => 1 + [...sentence].filter((character) => "،؛:".includes(character)).length,
  );
  const averageClausesPerSentence = clauseCounts.length
    ? clauseCounts.reduce((sum, value) => sum + value, 0) / clauseCounts.length
    : 0;
  const sentenceDensity = averageWordsPerSentence * Math.max(1, averageClausesPerSentence);
  const penalty =
    Math.max(0, averageWordsPerSentence - 14) * 1.35 +
    Math.max(0, averageCharactersPerWord - 5.5) * 4 +
    longWordRatio * 22 +
    repeatedWordRatio * 35 +
    Math.max(0, averageClausesPerSentence - 1) * 5;
  const clarityScore = clamp(100 - penalty, 0, 100);
  const complexityScore = clamp(
    (100 - clarityScore) * 0.68 + Math.max(0, sentenceDensity - 14) * 1.1,
    0,
    100,
  );
  const band = clarityScore >= 82
    ? "clear"
    : clarityScore >= 65
      ? "moderate"
      : clarityScore >= 45
        ? "dense"
        : "very_dense";
  return Object.freeze({
    words,
    sentences: sentences.length,
    uniqueWords,
    averageWordsPerSentence,
    averageCharactersPerWord,
    longWordRatio,
    repeatedWordRatio,
    lexicalRichness,
    hapaxRatio,
    averageClausesPerSentence,
    sentenceDensity,
    clarityScore,
    complexityScore,
    band,
  });
}

function detectDialect(text, tokens) {
  const conversions = [];
  const counts = new Map();
  for (const token of tokens) {
    const entry = DIALECT_TERMS.get(token.normalized);
    if (!entry) continue;
    const [dialect, replacement, explanation] = entry;
    counts.set(dialect, (counts.get(dialect) ?? 0) + 1);
    conversions.push(Object.freeze({
      rule_id: `APEX_DIALECT_${dialect.toUpperCase()}_${token.normalized}`,
      dialect,
      source: token.text,
      replacement,
      offset: token.offset,
      length: token.length,
      confidence: dialect === "shared" ? 0.82 : 0.92,
      explanation,
    }));
  }
  const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const primary = ranked[0]?.[0] ?? "msa";
  const total = conversions.length;
  const confidence = total ? clamp(0.58 + (ranked[0][1] / total) * 0.36, 0, 0.98) : 1;
  let convertedText = text;
  const codePoints = Array.from(text);
  for (const conversion of [...conversions].sort((a, b) => b.offset - a.offset)) {
    codePoints.splice(conversion.offset, conversion.length, ...Array.from(conversion.replacement));
  }
  convertedText = codePoints.join("");
  return Object.freeze({
    primary,
    confidence,
    conversions: Object.freeze(conversions),
    convertedText,
  });
}

export function createDialectMatches(dialectReport) {
  if (!dialectReport || !Array.isArray(dialectReport.conversions)) {
    throw new TypeError("A dialect report is required");
  }
  return Object.freeze(dialectReport.conversions.map((item) => Object.freeze({
    rule_id: item.rule_id,
    category: "dialect",
    message: `تعبير لهجي؛ بالفصحى: «${item.replacement}».`,
    offset: item.offset,
    length: item.length,
    replacements: Object.freeze([item.replacement]),
    severity: "hint",
    explanation: item.explanation,
    autofix: false,
    confidence: item.confidence,
    priority: 42,
    tags: Object.freeze(["dialect-to-msa", "requires-approval", `dialect:${item.dialect}`]),
    references: Object.freeze([]),
    profiles: Object.freeze([]),
  })));
}

export function parseLexiconInput(value, { limit = 500, wordLimit = 128 } = {}) {
  if (typeof value !== "string") throw new TypeError("Lexicon input must be a string");
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 10_000) {
    throw new RangeError("Lexicon limit must be between 1 and 10000");
  }
  if (!Number.isSafeInteger(wordLimit) || wordLimit < 1 || wordLimit > 512) {
    throw new RangeError("Lexicon word limit must be between 1 and 512");
  }
  const unique = new Map();
  for (const raw of value.split(/[\n،,؛;]+/u)) {
    const word = raw.trim();
    if (!word) continue;
    if (Array.from(word).length > wordLimit) throw new RangeError(`Lexicon word exceeds ${wordLimit} characters`);
    const normalized = normalizeArabic(word);
    if (!normalized) continue;
    if (!unique.has(normalized)) unique.set(normalized, word);
    if (unique.size > limit) throw new RangeError(`Lexicon exceeds ${limit} entries`);
  }
  return Object.freeze([...unique.values()]);
}

export function applyLocalOverrides(matches, text, { customWords = [], disabledRules = [] } = {}) {
  if (!Array.isArray(matches) || typeof text !== "string") {
    throw new TypeError("matches and text are required");
  }
  const disabled = new Set(disabledRules);
  const lexicon = new Set(customWords.map(normalizeArabic).filter(Boolean));
  const codePoints = Array.from(text);
  return Object.freeze(matches.filter((match) => {
    if (disabled.has(match.rule_id)) return false;
    const source = normalizeArabic(codePoints.slice(match.offset, match.offset + match.length).join(""));
    return !lexicon.has(source);
  }));
}

export function buildExplanations(matches, text) {
  if (!Array.isArray(matches) || typeof text !== "string") {
    throw new TypeError("matches and text are required");
  }
  const codePoints = Array.from(text);
  return Object.freeze(matches.map((match) => Object.freeze({
    ruleId: match.rule_id,
    category: match.category,
    title: match.message,
    reasoning: match.explanation?.trim() || match.message,
    whyItMatters: CATEGORY_REASON[match.category] ?? "يوضح سبب الاقتراح ويبقي القرار للكاتب.",
    sourceText: codePoints.slice(match.offset, match.offset + match.length).join(""),
    offset: match.offset,
    length: match.length,
    severity: match.severity ?? "hint",
    replacements: Object.freeze([...(match.replacements ?? [])]),
    confidence: Number.isFinite(match.confidence) ? match.confidence : 0.5,
    decision: match.autofix ? "safe_autofix" : "review_required",
    references: Object.freeze([...(match.references ?? [])]),
  })));
}

function createSuggestionChips(tone, dialect) {
  const relevance = {
    academic: tone.primary === "casual" ? 0.96 : 0.76,
    formal: dialect.conversions.length ? 0.98 : tone.primary === "casual" ? 0.92 : 0.72,
    casual: ["academic", "formal"].includes(tone.primary) ? 0.88 : 0.62,
    persuasive: tone.primary === "persuasive" ? 0.56 : 0.84,
  };
  return Object.freeze(Object.values(CHIP_LIBRARY)
    .map((chip) => Object.freeze({ ...chip, relevance: relevance[chip.target] }))
    .sort((a, b) => b.relevance - a.relevance || a.target.localeCompare(b.target)));
}

export function analyzeWriting(text, { matches = [] } = {}) {
  if (typeof text !== "string") throw new TypeError("text must be a string");
  if (!Array.isArray(matches)) throw new TypeError("matches must be an array");
  const tokens = arabicTokens(text);
  const tone = classifyTone(text);
  const dialect = detectDialect(text, tokens);
  const metrics = readability(text, tokens);
  return Object.freeze({
    tone,
    readability: metrics,
    dialect,
    suggestionChips: createSuggestionChips(tone, dialect),
    explanations: buildExplanations(matches, text),
  });
}

export function guidanceForTarget(report, target) {
  if (!report || !Array.isArray(report.suggestionChips)) throw new TypeError("Writing report is required");
  const chip = report.suggestionChips.find((item) => item.target === target);
  if (!chip) throw new RangeError("Unknown writing target");
  return chip;
}
