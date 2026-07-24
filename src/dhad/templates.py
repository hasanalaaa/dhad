"""Offline-first Arabic writing templates with explicit, non-hallucinatory inputs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class TemplateId(str, Enum):
    PROFESSIONAL_EMAIL = "professional_email"
    ACADEMIC_ABSTRACT = "academic_abstract"
    COVER_LETTER = "cover_letter"
    SOCIAL_POST = "social_post"
    MEETING_SUMMARY = "meeting_summary"
    EXECUTIVE_BRIEF = "executive_brief"


@dataclass(frozen=True, slots=True)
class TemplateField:
    id: str
    label: str
    placeholder: str
    required: bool = True
    multiline: bool = False
    max_length: int = 2_000


@dataclass(frozen=True, slots=True)
class WritingTemplate:
    id: TemplateId
    title: str
    description: str
    fields: tuple[TemplateField, ...]
    supported_tones: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeneratedDocument:
    template_id: TemplateId
    title: str
    text: str
    missing_fields: tuple[str, ...]
    tone: str
    offline: bool = True


_TEMPLATES = {
    TemplateId.PROFESSIONAL_EMAIL: WritingTemplate(
        id=TemplateId.PROFESSIONAL_EMAIL,
        title="بريد مهني",
        description="رسالة واضحة تتضمن السياق والطلب والخطوة التالية.",
        fields=(
            TemplateField("recipient", "اسم المستلم", "الأستاذ/ة …"),
            TemplateField("subject", "موضوع الرسالة", "موضوع مختصر"),
            TemplateField("context", "السياق", "سبب التواصل وما حدث", multiline=True),
            TemplateField("request", "الطلب", "الإجراء المطلوب", multiline=True),
            TemplateField("deadline", "الموعد", "التاريخ أو المدة", required=False),
            TemplateField("sender", "اسم المرسل", "اسمك"),
        ),
        supported_tones=("formal", "friendly", "concise"),
    ),
    TemplateId.ACADEMIC_ABSTRACT: WritingTemplate(
        id=TemplateId.ACADEMIC_ABSTRACT,
        title="ملخص أكاديمي",
        description="بنية بحثية: خلفية، هدف، منهج، نتائج، ودلالة.",
        fields=(
            TemplateField("background", "الخلفية", "المشكلة أو الفجوة البحثية", multiline=True),
            TemplateField("objective", "الهدف", "ما الذي اختبرته الدراسة؟", multiline=True),
            TemplateField("method", "المنهج", "العينة والمنهج والتحليل", multiline=True),
            TemplateField("results", "النتائج", "النتائج الفعلية فقط", multiline=True),
            TemplateField("conclusion", "الخلاصة", "الدلالة والحدود", multiline=True),
        ),
        supported_tones=("academic", "concise"),
    ),
    TemplateId.COVER_LETTER: WritingTemplate(
        id=TemplateId.COVER_LETTER,
        title="خطاب تقديم",
        description="خطاب مخصص يربط الخبرة بالدور من دون ادعاءات غير مدخلة.",
        fields=(
            TemplateField("role", "المسمى", "المسمى الوظيفي"),
            TemplateField("organization", "الجهة", "اسم الجهة"),
            TemplateField("experience", "الخبرة ذات الصلة", "خبرات وإنجازات قابلة للتحقق", multiline=True),
            TemplateField("motivation", "الدافع", "لماذا هذا الدور وهذه الجهة؟", multiline=True),
            TemplateField("contact", "بيانات التواصل", "البريد أو الهاتف", required=False),
            TemplateField("sender", "الاسم", "اسم المتقدم"),
        ),
        supported_tones=("formal", "persuasive", "concise"),
    ),
    TemplateId.SOCIAL_POST: WritingTemplate(
        id=TemplateId.SOCIAL_POST,
        title="منشور اجتماعي",
        description="افتتاحية، قيمة واضحة، ودعوة واحدة للتفاعل.",
        fields=(
            TemplateField("topic", "الموضوع", "الفكرة الأساسية"),
            TemplateField("value", "القيمة", "ما الذي سيستفيده القارئ؟", multiline=True),
            TemplateField("proof", "الدليل أو المثال", "مثال حقيقي أو رقم موثوق", required=False, multiline=True),
            TemplateField("call_to_action", "الدعوة", "السؤال أو الإجراء المطلوب"),
            TemplateField("hashtags", "الوسوم", "#وسم", required=False),
        ),
        supported_tones=("friendly", "persuasive", "creative"),
    ),
    TemplateId.MEETING_SUMMARY: WritingTemplate(
        id=TemplateId.MEETING_SUMMARY,
        title="ملخص اجتماع",
        description="قرارات وإجراءات ومسؤوليات ومواعيد واضحة.",
        fields=(
            TemplateField("title", "عنوان الاجتماع", "العنوان"),
            TemplateField("date", "التاريخ", "التاريخ"),
            TemplateField("attendees", "الحضور", "الأسماء أو الفرق", required=False),
            TemplateField("decisions", "القرارات", "قرار في كل سطر", multiline=True),
            TemplateField("actions", "الإجراءات", "الإجراء — المسؤول — الموعد", multiline=True),
            TemplateField("risks", "المخاطر", "المخاطر أو العوائق", required=False, multiline=True),
        ),
        supported_tones=("formal", "concise"),
    ),
    TemplateId.EXECUTIVE_BRIEF: WritingTemplate(
        id=TemplateId.EXECUTIVE_BRIEF,
        title="موجز تنفيذي",
        description="قرار مطلوب، سياق، أدلة، خيارات، وتوصية.",
        fields=(
            TemplateField("decision", "القرار المطلوب", "ما الذي يجب اعتماده؟"),
            TemplateField("context", "السياق", "لماذا الآن؟", multiline=True),
            TemplateField("evidence", "الأدلة", "حقائق وأرقام موثقة", multiline=True),
            TemplateField("options", "الخيارات", "الخيار ومزاياه ومخاطره", multiline=True),
            TemplateField("recommendation", "التوصية", "التوصية والسبب", multiline=True),
            TemplateField("next_step", "الخطوة التالية", "المالك والموعد"),
        ),
        supported_tones=("formal", "academic", "persuasive"),
    ),
}

TEMPLATES: Mapping[TemplateId, WritingTemplate] = MappingProxyType(_TEMPLATES)


def list_templates() -> tuple[WritingTemplate, ...]:
    return tuple(TEMPLATES.values())


def _value(values: Mapping[str, str], key: str) -> str:
    return str(values.get(key, "")).strip()


def _placeholder(field: TemplateField) -> str:
    return f"[{field.label}]"


def _render(template_id: TemplateId, values: Mapping[str, str]) -> str:
    v = lambda key: _value(values, key)  # noqa: E731
    if template_id is TemplateId.PROFESSIONAL_EMAIL:
        deadline = f" وأرجو إتمام ذلك بحلول {v('deadline')}" if v("deadline") else ""
        return (
            f"مرحبًا {v('recipient') or '[اسم المستلم]'}،\n\n"
            f"الموضوع: {v('subject') or '[موضوع الرسالة]'}\n\n"
            f"{v('context') or '[السياق]'}\n\n"
            f"أرجو {v('request') or '[الإجراء المطلوب]'}{deadline}.\n\n"
            "شكرًا لوقتكم، وأتطلع إلى ردكم.\n\n"
            f"مع التقدير،\n{v('sender') or '[اسم المرسل]'}"
        )
    if template_id is TemplateId.ACADEMIC_ABSTRACT:
        return " ".join(
            (
                f"الخلفية: {v('background') or '[الخلفية]'}.",
                f"الهدف: {v('objective') or '[الهدف]'}.",
                f"المنهج: {v('method') or '[المنهج]'}.",
                f"النتائج: {v('results') or '[النتائج الفعلية]'}.",
                f"الخلاصة: {v('conclusion') or '[الخلاصة والحدود]'}.",
            )
        )
    if template_id is TemplateId.COVER_LETTER:
        contact = f"\nبيانات التواصل: {v('contact')}" if v("contact") else ""
        return (
            f"السادة في {v('organization') or '[اسم الجهة]'} المحترمون،\n\n"
            f"أتقدم لشغل منصب {v('role') or '[المسمى الوظيفي]'}. "
            f"ترتبط خبرتي بالدور من خلال: {v('experience') or '[الخبرة ذات الصلة]'}.\n\n"
            f"ويحفزني للانضمام إليكم {v('motivation') or '[الدافع]'}. "
            "يسعدني مناقشة كيفية توظيف هذه الخبرة لتحقيق أهداف الدور.\n\n"
            f"مع التقدير،\n{v('sender') or '[الاسم]'}{contact}"
        )
    if template_id is TemplateId.SOCIAL_POST:
        proof = f"\n\nمثال: {v('proof')}" if v("proof") else ""
        tags = f"\n\n{v('hashtags')}" if v("hashtags") else ""
        return (
            f"{v('topic') or '[افتتاحية الموضوع]'}\n\n"
            f"{v('value') or '[القيمة التي سيحصل عليها القارئ]'}"
            f"{proof}\n\n{v('call_to_action') or '[دعوة واضحة للتفاعل]'}{tags}"
        )
    if template_id is TemplateId.MEETING_SUMMARY:
        attendees = f"\nالحضور: {v('attendees')}" if v("attendees") else ""
        risks = f"\n\nالمخاطر والعوائق:\n{v('risks')}" if v("risks") else ""
        return (
            f"# {v('title') or '[عنوان الاجتماع]'}\n"
            f"التاريخ: {v('date') or '[التاريخ]'}{attendees}\n\n"
            f"## القرارات\n{v('decisions') or '[القرارات]'}\n\n"
            f"## الإجراءات\n{v('actions') or '[الإجراء — المسؤول — الموعد]'}{risks}"
        )
    return (
        f"# القرار المطلوب\n{v('decision') or '[القرار المطلوب]'}\n\n"
        f"## السياق\n{v('context') or '[السياق]'}\n\n"
        f"## الأدلة\n{v('evidence') or '[الأدلة الموثقة]'}\n\n"
        f"## الخيارات\n{v('options') or '[الخيارات والمفاضلات]'}\n\n"
        f"## التوصية\n{v('recommendation') or '[التوصية والسبب]'}\n\n"
        f"## الخطوة التالية\n{v('next_step') or '[المالك والموعد]'}"
    )


def generate_document(
    template_id: TemplateId | str,
    values: Mapping[str, str],
    *,
    tone: str = "formal",
) -> GeneratedDocument:
    selected = TemplateId(template_id)
    template = TEMPLATES[selected]
    if tone not in template.supported_tones:
        raise ValueError(f"Unsupported tone for {selected.value}: {tone}")
    allowed = {field.id: field for field in template.fields}
    unknown = set(values) - set(allowed)
    if unknown:
        raise ValueError(f"Unknown template fields: {', '.join(sorted(unknown))}")
    for key, value in values.items():
        if len(str(value)) > allowed[key].max_length:
            raise ValueError(f"Template field exceeds its limit: {key}")
    missing = tuple(
        field.id for field in template.fields if field.required and not _value(values, field.id)
    )
    return GeneratedDocument(
        template_id=selected,
        title=template.title,
        text=_render(selected, values),
        missing_fields=missing,
        tone=tone,
    )
