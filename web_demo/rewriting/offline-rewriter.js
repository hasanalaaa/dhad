export const REWRITE_MODES = Object.freeze({
  formal: Object.freeze({ label: "رسمي", description: "رفع السجل واستبدال الألفاظ المحادثية." }),
  concise: Object.freeze({ label: "موجز", description: "حذف الحشو والتكرار من دون إسقاط المعلومات." }),
  expand: Object.freeze({ label: "موسّع", description: "إظهار الروابط بين الأفكار من دون اختلاق حقائق." }),
  creative: Object.freeze({ label: "إبداعي", description: "تنويع الروابط والمفردات مع حفظ المعنى." }),
  academic: Object.freeze({ label: "أكاديمي", description: "تقليل الذاتية ورفع دقة السجل البحثي." }),
});

const FORMAL = Object.freeze([
  ["بس", "لكن", "استبدال رابط محادثي برابط فصيح."],
  ["عشان", "لكي", "استبدال تعليل محادثي بصياغة فصيحة."],
  ["ليش", "لماذا", "استبدال أداة استفهام عامية بأداة فصيحة."],
  ["شلون", "كيف", "استبدال أداة استفهام عامية بأداة فصيحة."],
  ["هسه", "الآن", "استبدال ظرف عامي بظرف فصيح."],
  ["ماكو", "لا يوجد", "استبدال تركيب عامي بتركيب فصيح."],
  ["أريد", "أرغب في", "رفع درجة الرسمية من دون تغيير المقصود."],
]);
const ACADEMIC = Object.freeze([
  ["أنا أعتقد أن", "يمكن القول إن", "تقليل الحضور الشخصي في الصياغة الأكاديمية."],
  ["أعتقد أن", "تشير المعطيات إلى أن", "تحويل الرأي المباشر إلى صياغة تحليلية."],
  ["من الواضح أن", "تشير النتائج إلى أن", "تجنب القطع غير المدعوم."],
  ["أكيد", "على الأرجح", "استبدال الجزم بتقدير احتمالي أكثر دقة."],
  ["شيء", "عنصر", "استخدام مفردة أكثر تحديدًا."],
  ["أشياء", "عناصر", "استخدام جمع أكثر تحديدًا."],
]);
const CREATIVE = Object.freeze([
  ["بالإضافة إلى ذلك", "وفوق ذلك", "تنويع الرابط الإضافي."],
  ["ولكن", "ومع ذلك", "تنويع رابط الاستدراك."],
  ["لذلك", "ومن هنا", "تنويع رابط النتيجة."],
  ["في النهاية", "وفي المحصلة", "تنويع خاتمة الفكرة."],
  ["مهم", "محوري", "اختيار مفردة أكثر حيوية."],
]);
const CONCISE = Object.freeze([
  [/\bفي واقع الأمر\b[،,]?\s*/gu, "", "حذف عبارة تمهيدية لا تضيف معنى."],
  [/\bفي الحقيقة\b[،,]?\s*/gu, "", "حذف عبارة تمهيدية لا تضيف معنى."],
  [/\bمن الجدير بالذكر أن\s*/gu, "", "الوصول مباشرة إلى الفكرة."],
  [/\bلا بد من الإشارة إلى أن\s*/gu, "", "الوصول مباشرة إلى الفكرة."],
  [/\bفي الوقت الحالي\b/gu, "حاليًا", "اختصار تركيب زمني طويل."],
  [/\bبسبب حقيقة أن\b/gu, "لأن", "اختصار تركيب سببي طويل."],
  [/\bمن أجل أن\b/gu, "لكي", "اختصار تركيب غائي طويل."],
]);

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function replaceLiteral(text, entries, limit) {
  let output = text;
  const changes = [];
  for (const [source, replacement, explanation] of entries) {
    const pattern = new RegExp(`(^|[^\\p{L}\\p{N}_])(${escapeRegex(source)})(?=$|[^\\p{L}\\p{N}_])`, "u");
    while (changes.length < limit) {
      const match = pattern.exec(output);
      if (!match) break;
      const offset = match.index + match[1].length;
      output = `${output.slice(0, offset)}${replacement}${output.slice(offset + source.length)}`;
      changes.push(Object.freeze({ kind: "lexical", source, replacement, offset, length: source.length, explanation }));
    }
    if (changes.length >= limit) break;
  }
  return { output, changes };
}

function replacePatterns(text, entries, limit) {
  let output = text;
  const changes = [];
  for (const [pattern, replacement, explanation] of entries) {
    pattern.lastIndex = 0;
    while (changes.length < limit) {
      pattern.lastIndex = 0;
      const match = pattern.exec(output);
      if (!match) break;
      output = `${output.slice(0, match.index)}${replacement}${output.slice(match.index + match[0].length)}`;
      changes.push(Object.freeze({ kind: "structural", source: match[0], replacement, offset: match.index, length: match[0].length, explanation }));
    }
    if (changes.length >= limit) break;
  }
  return { output, changes };
}

function removeDuplicateWords(text, limit) {
  let output = text;
  const changes = [];
  const pattern = /(^|[^\p{L}\p{N}_])([\u0600-\u06FF]{2,})\s+\2(?=$|[^\p{L}\p{N}_])/u;
  while (changes.length < limit) {
    const match = pattern.exec(output);
    if (!match) break;
    const offset = match.index + match[1].length;
    const source = match[0].slice(match[1].length);
    output = `${output.slice(0, offset)}${match[2]}${output.slice(offset + source.length)}`;
    changes.push(Object.freeze({ kind: "structural", source, replacement: match[2], offset, length: source.length, explanation: "حذف تكرار متجاور لا يضيف معنى." }));
  }
  return { output, changes };
}

function applyDialectConversions(text, conversions, limit) {
  let output = text;
  const changes = [];
  const ordered = [...(conversions || [])]
    .filter((item) => Number.isInteger(item.offset) && Number.isInteger(item.length))
    .sort((a, b) => b.offset - a.offset);
  for (const item of ordered) {
    if (changes.length >= limit) break;
    const source = output.slice(item.offset, item.offset + item.length);
    if (source !== item.source || typeof item.replacement !== "string") continue;
    output = `${output.slice(0, item.offset)}${item.replacement}${output.slice(item.offset + item.length)}`;
    changes.push(Object.freeze({
      kind: "dialect",
      source,
      replacement: item.replacement,
      offset: item.offset,
      length: item.length,
      explanation: item.explanation || "استبدال لفظ لهجي بمقابله الفصيح.",
    }));
  }
  return { output, changes: changes.reverse() };
}

function sentences(text) {
  return text.match(/[^.!؟!؛…]+[.!؟!؛…]?/gu)?.filter((item) => item.trim()) ?? [];
}

function expandStructure(text, intensity) {
  const parts = sentences(text);
  if (parts.length < 2) {
    if (intensity < 2 || !text.trim()) return { output: text, changes: [] };
    return {
      output: `بعبارة أوضح، ${text.trim()}`,
      changes: [Object.freeze({ kind: "discourse", source: "", replacement: "بعبارة أوضح، ", offset: 0, length: 0, explanation: "إضافة تمهيد يوضح أن الصياغة التالية تفصيل للفكرة نفسها." })],
    };
  }
  const connectors = ["إضافة إلى ذلك، ", "وفي هذا السياق، ", "وبناءً على ذلك، "];
  const changes = [];
  const output = parts.map((part, index) => {
    if (!index || index > intensity + 1 || /^\s*(?:و|ف|ثم|لكن|لذلك|إضافة|في هذا|بناء)/u.test(part)) return part.trim();
    const connector = connectors[(index - 1) % connectors.length];
    const offset = parts.slice(0, index).join("").length;
    changes.push(Object.freeze({ kind: "discourse", source: "", replacement: connector, offset, length: 0, explanation: "إظهار العلاقة الخطابية بين الجمل من دون إضافة ادعاء جديد." }));
    return `${connector}${part.trim()}`;
  }).join(" ");
  return { output, changes };
}

function normalizeSpacing(text) {
  return text.replace(/[ \t]{2,}/gu, " ").replace(/\s+([،؛:,.!?؟])/gu, "$1").replace(/([،؛:])(?=[^\s\n])/gu, "$1 ").trim();
}

function buildCandidate(source, mode, variant, output, changes) {
  const text = normalizeSpacing(output);
  const changedRatio = source ? Math.min(1, Math.abs(source.length - text.length) / source.length) : 0;
  const labels = {
    formal: ["رسمي محافظ", "رسمي متوازن", "رسمي مصقول"],
    concise: ["إيجاز آمن", "إيجاز متوازن", "إيجاز مكثف"],
    expand: ["توسيع خفيف", "توسيع مترابط", "توسيع منظم"],
    creative: ["تنويع خفيف", "تنويع متوازن", "تنويع تعبيري"],
    academic: ["أكاديمي محافظ", "أكاديمي متوازن", "أكاديمي محكم"],
  };
  return Object.freeze({
    id: `${mode}:${variant}`,
    mode,
    text,
    label: labels[mode][variant - 1],
    explanation: REWRITE_MODES[mode].description,
    changes: Object.freeze(changes),
    confidence: Math.max(0.62, Math.min(0.97, 0.9 - changedRatio * 0.15 + Math.min(changes.length, 8) * 0.005)),
    meaningPreservation: Math.max(0.72, 0.99 - changedRatio * 0.34 - changes.length * 0.006),
    brevityDelta: source ? Math.max(-1, Math.min(1, (source.length - text.length) / source.length)) : 0,
  });
}

export function rewriteText(text, mode = "formal", { alternatives = 3, dialectConversions = [] } = {}) {
  if (typeof text !== "string") throw new TypeError("text must be a string");
  if (!(mode in REWRITE_MODES)) throw new RangeError("unsupported rewrite mode");
  if (!Number.isInteger(alternatives) || alternatives < 1 || alternatives > 3) throw new RangeError("alternatives must be between one and three");
  const source = text.trim();
  if (!source) return Object.freeze({ sourceText: text, mode, candidates: Object.freeze([]), offline: true });
  const candidates = [];
  const seen = new Set();
  for (let variant = 1; variant <= alternatives; variant += 1) {
    const limit = variant * 3;
    let output = source;
    const changes = [];
    if (mode === "formal" || mode === "academic") {
      const dialect = applyDialectConversions(output, dialectConversions, limit);
      output = dialect.output; changes.push(...dialect.changes);
      const formal = replaceLiteral(output, FORMAL, limit);
      output = formal.output; changes.push(...formal.changes);
    }
    if (mode === "concise") {
      const concise = replacePatterns(output, CONCISE, limit);
      output = concise.output; changes.push(...concise.changes);
      const duplicates = removeDuplicateWords(output, limit);
      output = duplicates.output; changes.push(...duplicates.changes);
    } else if (mode === "expand") {
      const expanded = expandStructure(output, variant);
      output = expanded.output; changes.push(...expanded.changes);
    } else if (mode === "creative") {
      const creative = replaceLiteral(output, CREATIVE, limit);
      output = creative.output; changes.push(...creative.changes);
      if (variant > 1) {
        const expanded = expandStructure(output, variant - 1);
        output = expanded.output; changes.push(...expanded.changes);
      }
    } else if (mode === "academic") {
      const academic = replaceLiteral(output, ACADEMIC, limit);
      output = academic.output; changes.push(...academic.changes);
      const concise = replacePatterns(output, CONCISE, variant);
      output = concise.output; changes.push(...concise.changes);
    }
    const normalized = normalizeSpacing(output);
    if (seen.has(normalized)) continue;
    seen.add(normalized);
    candidates.push(buildCandidate(source, mode, variant, normalized, changes));
  }
  if (!candidates.length) candidates.push(buildCandidate(source, mode, 1, source, []));
  return Object.freeze({
    sourceText: text,
    mode,
    candidates: Object.freeze(candidates),
    offline: true,
    safetyNotice: "أُنشئت البدائل محليًا من النص الأصلي فقط؛ راجع الأسماء والأرقام والمصطلحات قبل الاعتماد.",
  });
}
