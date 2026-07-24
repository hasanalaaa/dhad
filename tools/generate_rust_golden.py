"""Generate the cross-language golden corpus for dhad-core-rs.

Python is the reference implementation; this script serializes its exact
behavior for ``normalize``, ``tokenize`` and ``sentence_spans`` over a corpus
of adversarial inputs. ``rust/dhad-core-rs/tests/golden.rs`` replays the file
and fails on any divergence. Regenerate after any intentional change to
``dhad/text.py`` and commit both sides together::

    python tools/generate_rust_golden.py
"""

from __future__ import annotations

import json
from pathlib import Path

from dhad.text import NormalizationMode, normalize, sentence_spans, tokenize

OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "rust"
    / "dhad-core-rs"
    / "tests"
    / "data"
    / "text_golden.jsonl"
)

CASES: list[str] = [
    "",
    "   ",
    "ذهبت الى المدرسه صباحا.",
    "ذَهَبَ الوَلَدُ إِلى المَدْرَسَةِ مُسْرِعًا!",
    "الســــلام عليكم ورحمة الله.",
    "أإآٱ ىئؤة — حروف تُطبَّع في وضع البحث.",
    "قرأت 3.14 صفحة ثم توقفت.",
    "قرأ ٣٫١٤ ثم ١٢٬٣٤٥ من الكتب.",
    "1. البند الأول\n2. البند الثاني\n٣. البند الثالث.",
    "أ. مقدمة\nب. خاتمة",
    "زار د. أحمد المستشفى. ثم غادر.",
    "حدث ذلك في ق.م. القديمة. نهاية.",
    "التقيت بـ Prof. Smith أمس. كان لطيفا.",
    "e.g. مثال أول، i.e. أي بعبارة أخرى.",
    "هل جئت؟ نعم! رائع… إذن نبدأ؛ الآن.",
    "قال: «اذهب.» ثم صمت.",
    'انتهى ("تقريبا".) صحيح.',
    "زر https://example.com/ar/page?x=1 الآن.",
    "زر www.example.org، ثم عد.",
    "راسلني على test.user+tag@example-mail.com اليوم.",
    "الوسم #ضاد و@مستخدم مذكوران.",
    "الرمز `x = 1` داخل سطر.",
    "```\ncode block\nمتعدد الأسطر\n```\nنص بعده.",
    "أرقام هاتف 07701 234 567 وسنة 2026 و٪٥٠.",
    "كلمة\nعلى\nأسطر\nمتعددة",
    "Latin words mixed مع العربية and l'élève naïve.",
    "علامات!!! متتالية??? كثيرة...",
    "ﻻ توجد نهاية",
    "نقطة في النهاية.",
    "تشكيلٌ كاملٌ: الحَمْدُ لِلَّهِ رَبِّ العالَمِينَ.",
    "underscore_word و co-op و it’s هنا.",
    "أقواس [مربعة] و{معقوفة} و(هلالية).",
    "سطر ينتهي بنقطتين: ثم يكمل. وينتهي.",
    "ة في آخر الكلمة والتاء المربوطه شائعه.",
    "‏نص مع علامة اتجاه.‎",
    "10.5% و ٥٠٪ و -3.2 و +7.",
]


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        for case in CASES:
            record = {
                "input": case,
                "normalize": {
                    mode.value: normalize(case, mode) for mode in NormalizationMode
                },
                "sentences": [
                    [item.text, item.start, item.end, item.terminator]
                    for item in sentence_spans(case)
                ],
                "tokens": [
                    [token.text, token.start, token.end, token.kind.value]
                    for token in tokenize(case, include_non_words=True)
                ],
                "content_tokens": [
                    [token.text, token.start, token.end, token.kind.value]
                    for token in tokenize(case)
                ],
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"wrote {len(CASES)} cases to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
