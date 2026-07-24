export const SMART_TEMPLATES = Object.freeze([
  Object.freeze({ id: "professional_email", title: "بريد مهني", description: "سياق وطلب وخطوة تالية واضحة.", tones: ["formal", "friendly", "concise"], fields: [
    ["recipient", "اسم المستلم", true, false], ["subject", "الموضوع", true, false], ["context", "السياق", true, true], ["request", "الطلب", true, true], ["deadline", "الموعد", false, false], ["sender", "اسم المرسل", true, false],
  ] }),
  Object.freeze({ id: "academic_abstract", title: "ملخص أكاديمي", description: "خلفية وهدف ومنهج ونتائج وخلاصة.", tones: ["academic", "concise"], fields: [
    ["background", "الخلفية", true, true], ["objective", "الهدف", true, true], ["method", "المنهج", true, true], ["results", "النتائج", true, true], ["conclusion", "الخلاصة", true, true],
  ] }),
  Object.freeze({ id: "cover_letter", title: "خطاب تقديم", description: "ربط الخبرة بالدور دون ادعاءات غير مدخلة.", tones: ["formal", "persuasive", "concise"], fields: [
    ["role", "المسمى", true, false], ["organization", "الجهة", true, false], ["experience", "الخبرة ذات الصلة", true, true], ["motivation", "الدافع", true, true], ["contact", "التواصل", false, false], ["sender", "الاسم", true, false],
  ] }),
  Object.freeze({ id: "social_post", title: "منشور اجتماعي", description: "افتتاحية وقيمة ودعوة واحدة للتفاعل.", tones: ["friendly", "persuasive", "creative"], fields: [
    ["topic", "الموضوع", true, false], ["value", "القيمة", true, true], ["proof", "الدليل أو المثال", false, true], ["call_to_action", "الدعوة", true, false], ["hashtags", "الوسوم", false, false],
  ] }),
  Object.freeze({ id: "meeting_summary", title: "ملخص اجتماع", description: "قرارات وإجراءات ومسؤوليات ومواعيد.", tones: ["formal", "concise"], fields: [
    ["title", "العنوان", true, false], ["date", "التاريخ", true, false], ["attendees", "الحضور", false, false], ["decisions", "القرارات", true, true], ["actions", "الإجراءات", true, true], ["risks", "المخاطر", false, true],
  ] }),
  Object.freeze({ id: "executive_brief", title: "موجز تنفيذي", description: "قرار وسياق وأدلة وخيارات وتوصية.", tones: ["formal", "academic", "persuasive"], fields: [
    ["decision", "القرار المطلوب", true, false], ["context", "السياق", true, true], ["evidence", "الأدلة", true, true], ["options", "الخيارات", true, true], ["recommendation", "التوصية", true, true], ["next_step", "الخطوة التالية", true, false],
  ] }),
].map((template) => Object.freeze({ ...template, fields: Object.freeze(template.fields.map(([id, label, required, multiline]) => Object.freeze({ id, label, required, multiline, maxLength: 2000 }))) })));

export function templateById(id) { return SMART_TEMPLATES.find((item) => item.id === id) ?? null; }
function value(values, key) { return String(values?.[key] ?? "").trim(); }

export function generateFromTemplate(templateId, values = {}, { tone } = {}) {
  const template = templateById(templateId);
  if (!template) throw new RangeError("unknown template");
  const selectedTone = tone ?? template.tones[0];
  if (!template.tones.includes(selectedTone)) throw new RangeError("unsupported template tone");
  const allowed = new Set(template.fields.map((field) => field.id));
  for (const [key, item] of Object.entries(values)) {
    if (!allowed.has(key)) throw new RangeError(`unknown template field: ${key}`);
    if (String(item).length > 2000) throw new RangeError(`template field too long: ${key}`);
  }
  const v = (key, fallback) => value(values, key) || `[${fallback}]`;
  const missingFields = template.fields.filter((field) => field.required && !value(values, field.id)).map((field) => field.id);
  let text;
  if (templateId === "professional_email") {
    const deadline = value(values, "deadline") ? ` وأرجو إتمام ذلك بحلول ${value(values, "deadline")}` : "";
    text = `مرحبًا ${v("recipient", "اسم المستلم")}،\n\nالموضوع: ${v("subject", "موضوع الرسالة")}\n\n${v("context", "السياق")}\n\nأرجو ${v("request", "الإجراء المطلوب")}${deadline}.\n\nشكرًا لوقتكم، وأتطلع إلى ردكم.\n\nمع التقدير،\n${v("sender", "اسم المرسل")}`;
  } else if (templateId === "academic_abstract") {
    text = `الخلفية: ${v("background", "الخلفية")}. الهدف: ${v("objective", "الهدف")}. المنهج: ${v("method", "المنهج")}. النتائج: ${v("results", "النتائج الفعلية")}. الخلاصة: ${v("conclusion", "الخلاصة والحدود")}.`;
  } else if (templateId === "cover_letter") {
    const contact = value(values, "contact") ? `\nبيانات التواصل: ${value(values, "contact")}` : "";
    text = `السادة في ${v("organization", "اسم الجهة")} المحترمون،\n\nأتقدم لشغل منصب ${v("role", "المسمى الوظيفي")}. ترتبط خبرتي بالدور من خلال: ${v("experience", "الخبرة ذات الصلة")}.\n\nويحفزني للانضمام إليكم ${v("motivation", "الدافع")}. يسعدني مناقشة كيفية توظيف هذه الخبرة لتحقيق أهداف الدور.\n\nمع التقدير،\n${v("sender", "الاسم")}${contact}`;
  } else if (templateId === "social_post") {
    const proof = value(values, "proof") ? `\n\nمثال: ${value(values, "proof")}` : "";
    const tags = value(values, "hashtags") ? `\n\n${value(values, "hashtags")}` : "";
    text = `${v("topic", "افتتاحية الموضوع")}\n\n${v("value", "القيمة التي سيحصل عليها القارئ")}${proof}\n\n${v("call_to_action", "دعوة واضحة للتفاعل")}${tags}`;
  } else if (templateId === "meeting_summary") {
    const attendees = value(values, "attendees") ? `\nالحضور: ${value(values, "attendees")}` : "";
    const risks = value(values, "risks") ? `\n\nالمخاطر والعوائق:\n${value(values, "risks")}` : "";
    text = `# ${v("title", "عنوان الاجتماع")}\nالتاريخ: ${v("date", "التاريخ")}${attendees}\n\n## القرارات\n${v("decisions", "القرارات")}\n\n## الإجراءات\n${v("actions", "الإجراء — المسؤول — الموعد")}${risks}`;
  } else {
    text = `# القرار المطلوب\n${v("decision", "القرار المطلوب")}\n\n## السياق\n${v("context", "السياق")}\n\n## الأدلة\n${v("evidence", "الأدلة الموثقة")}\n\n## الخيارات\n${v("options", "الخيارات والمفاضلات")}\n\n## التوصية\n${v("recommendation", "التوصية والسبب")}\n\n## الخطوة التالية\n${v("next_step", "المالك والموعد")}`;
  }
  return Object.freeze({ templateId, title: template.title, text, missingFields: Object.freeze(missingFields), tone: selectedTone, offline: true });
}
