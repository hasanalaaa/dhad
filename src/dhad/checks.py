"""الفحوص المدمجة: قواعد تحتاج منطقًا برمجيًا لا يُعبَّر عنه بقاعدة YAML بسيطة.

Built-in programmatic checks:
  * العدد والمعدود (number–noun gender agreement, 3–10)
  * علامات الترقيم اللاتينية في نص عربي
  * المسافات حول علامات الترقيم
  * تكرار الكلمة مرتين
  * التطويل (الكشيدة)
  * الجمل الطويلة جدًا
"""

from __future__ import annotations

import re

from .match import Match
from .text import AR_EXT_LETTER, AR_LETTER, B_LEFT, B_RIGHT, sentences, tokenize

# ---------------------------------------------------------------- العدد والمعدود
# القاعدة: الأعداد 3–10 تُخالف المعدود في التذكير والتأنيث.
# masc numeral form (with ة) ↔ fem numeral form (without ة)
NUM_MASC_TO_FEM = {
    "ثلاثة": "ثلاث",
    "أربعة": "أربع",
    "خمسة": "خمس",
    "ستة": "ست",
    "سبعة": "سبع",
    "ثمانية": "ثماني",
    "تسعة": "تسع",
    "عشرة": "عشر",
}
NUM_FEM_TO_MASC = {v: k for k, v in NUM_MASC_TO_FEM.items()}

#: معدودات مؤنثة شائعة (جمعها) → تتطلب صيغة العدد بلا تاء: ثلاث سنوات
FEM_COUNTED = {
    "سنوات",
    "ساعات",
    "مرات",
    "دقائق",
    "ثوان",
    "ليال",
    "سيارات",
    "لغات",
    "شركات",
    "صفحات",
    "كلمات",
    "جامعات",
    "مدارس",
    "مدن",
    "دول",
    "غرف",
    "رسائل",
    "صور",
    "قصص",
    "جمل",
    "محاولات",
    "خطوات",
    "مراحل",
    "نقاط",
}
#: معدودات مذكرة شائعة (جمعها) → تتطلب صيغة العدد بالتاء: ثلاثة أيام
MASC_COUNTED = {
    "أيام",
    "أشهر",
    "شهور",
    "أسابيع",
    "رجال",
    "كتب",
    "بيوت",
    "دروس",
    "فصول",
    "أبواب",
    "أطفال",
    "أولاد",
    "أسئلة",
    "مواضيع",
    "أقسام",
    "أفلام",
    "برامج",
    "مشاريع",
    "أهداف",
    "أمثلة",
    "أخطاء",
    "أسطر",
}

_MASC_NUM_RE = re.compile(
    B_LEFT + "(" + "|".join(NUM_MASC_TO_FEM) + r")\s+(" + "|".join(FEM_COUNTED) + ")" + B_RIGHT
)
_FEM_NUM_RE = re.compile(
    B_LEFT + "(" + "|".join(NUM_FEM_TO_MASC) + r")\s+(" + "|".join(MASC_COUNTED) + ")" + B_RIGHT
)


def check_number_agreement(text: str) -> list[Match]:
    out = []
    for m in _MASC_NUM_RE.finditer(text):
        num, noun = m.group(1), m.group(2)
        out.append(
            Match(
                rule_id="AGREEMENT_NUM_FEM_NOUN",
                category="grammar",
                message=f"المعدود «{noun}» مؤنث، فالعدد يخالفه: «{NUM_MASC_TO_FEM[num]} {noun}»",
                offset=m.start(),
                length=m.end() - m.start(),
                replacements=[f"{NUM_MASC_TO_FEM[num]} {noun}"],
                explanation="الأعداد من 3 إلى 10 تخالف المعدود: مع المؤنث تُحذف التاء (ثلاث سنوات).",
                autofix=True,
            )
        )
    for m in _FEM_NUM_RE.finditer(text):
        num, noun = m.group(1), m.group(2)
        out.append(
            Match(
                rule_id="AGREEMENT_NUM_MASC_NOUN",
                category="grammar",
                message=f"المعدود «{noun}» مذكر، فالعدد يخالفه: «{NUM_FEM_TO_MASC[num]} {noun}»",
                offset=m.start(),
                length=m.end() - m.start(),
                replacements=[f"{NUM_FEM_TO_MASC[num]} {noun}"],
                explanation="الأعداد من 3 إلى 10 تخالف المعدود: مع المذكر تثبت التاء (ثلاثة أيام).",
                autofix=True,
            )
        )
    return out


# ---------------------------------------------------------------- الترقيم اللاتيني
_LATIN_COMMA_RE = re.compile(rf"(?<=[{AR_LETTER}]),")
_LATIN_QMARK_RE = re.compile(rf"(?<=[{AR_LETTER}])\s*\?")
_LATIN_SEMI_RE = re.compile(rf"(?<=[{AR_LETTER}])\s*;")


def check_latin_punctuation(text: str) -> list[Match]:
    out = []
    for regex, rid, repl, name in (
        (_LATIN_COMMA_RE, "PUNCT_LATIN_COMMA", "،", "الفاصلة العربية «،»"),
        (_LATIN_QMARK_RE, "PUNCT_LATIN_QMARK", "؟", "علامة الاستفهام العربية «؟»"),
        (_LATIN_SEMI_RE, "PUNCT_LATIN_SEMI", "؛", "الفاصلة المنقوطة العربية «؛»"),
    ):
        for m in regex.finditer(text):
            out.append(
                Match(
                    rule_id=rid,
                    category="punctuation",
                    message=f"استخدم {name} في النص العربي",
                    offset=m.start(),
                    length=m.end() - m.start(),
                    replacements=[repl],
                    severity="warning",
                    autofix=True,
                )
            )
    return out


# ---------------------------------------------------------------- مسافات الترقيم
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+([،؛؟!.,:])")


def check_punctuation_spacing(text: str) -> list[Match]:
    out = []
    for m in _SPACE_BEFORE_PUNCT_RE.finditer(text):
        out.append(
            Match(
                rule_id="PUNCT_SPACE_BEFORE",
                category="punctuation",
                message="لا تضع مسافة قبل علامة الترقيم",
                offset=m.start(),
                length=m.end() - m.start(),
                replacements=[m.group(1)],
                severity="warning",
                autofix=True,
            )
        )
    return out


# ---------------------------------------------------------------- تكرار الكلمات
def check_repeated_words(text: str) -> list[Match]:
    out = []
    toks = [t for t in tokenize(text) if t.is_arabic]
    for a, b in zip(toks, toks[1:]):
        between = text[a.end : b.start]
        if a.text == b.text and len(a.text) > 1 and between.strip() == "":
            out.append(
                Match(
                    rule_id="STYLE_REPEATED_WORD",
                    category="style",
                    message=f"الكلمة «{a.text}» مكررة",
                    offset=a.start,
                    length=b.end - a.start,
                    replacements=[a.text],
                    severity="warning",
                )
            )
    return out


# ---------------------------------------------------------------- التطويل
_TATWEEL_RE = re.compile("ـ{1,}")


def check_tatweel(text: str) -> list[Match]:
    out = []
    for m in _TATWEEL_RE.finditer(text):
        out.append(
            Match(
                rule_id="STYLE_TATWEEL",
                category="style",
                message="تجنّب التطويل (الكشيدة) في النصوص",
                offset=m.start(),
                length=m.end() - m.start(),
                replacements=[""],
                severity="hint",
            )
        )
    return out


# ---------------------------------------------------------------- الجمل الطويلة
LONG_SENTENCE_WORDS = 50


def check_long_sentences(text: str) -> list[Match]:
    out = []
    for sent, start, end in sentences(text):
        n = len([t for t in tokenize(sent) if t.is_arabic])
        if n > LONG_SENTENCE_WORDS:
            lead = len(sent) - len(sent.lstrip())
            out.append(
                Match(
                    rule_id="STYLE_LONG_SENTENCE",
                    category="style",
                    message=f"جملة طويلة ({n} كلمة) — قسّمها لتسهيل القراءة",
                    offset=start + lead,
                    length=min(40, end - start - lead),
                    severity="hint",
                )
            )
    return out


# ------------------------------------------------- أحرف اللهجات (چ گ پ ژ)
_DIALECT_LETTER_WORD_RE = re.compile(
    rf"[{AR_LETTER}]*[{AR_EXT_LETTER.replace('ڤ', '')}][{AR_LETTER}]*"
)


def check_dialect_letters(text: str) -> list[Match]:
    """كلمات تحوي أحرفًا غير فصيحة (چ، گ، پ، ژ) — علامة مميزة لكتابة اللهجات."""
    out = []
    for m in _DIALECT_LETTER_WORD_RE.finditer(text):
        out.append(
            Match(
                rule_id="DIALECT_LETTERS",
                category="dialect",
                message=f"«{m.group()}» تحوي حرفًا غير فصيح (چ/گ/پ/ژ) — شائع في كتابة اللهجات",
                offset=m.start(),
                length=m.end() - m.start(),
                severity="hint",
                explanation="هذه الأحرف مستعارة من الفارسية وتُستخدم لكتابة أصوات اللهجات (چ=تش، گ=گاف). في النص الفصيح تُستبدل بأقرب حرف عربي.",
            )
        )
    return out


ALL_CHECKS = (
    check_dialect_letters,
    check_number_agreement,
    check_latin_punctuation,
    check_punctuation_spacing,
    check_repeated_words,
    check_tatweel,
    check_long_sentences,
)


def run_builtin_checks(text: str) -> list[Match]:
    out: list[Match] = []
    for fn in ALL_CHECKS:
        out.extend(fn(text))
    return out
