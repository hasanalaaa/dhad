"""Build Dhad Controlled Gold v1 deterministically.

The corpus is original project data generated from curated linguistic templates.
It is deliberately separate from YAML rule examples.  It provides a stable
measurement ruler; it is not presented as a substitute for a future naturally
occurring, human-annotated corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dhad.evaluation import BenchmarkCase, GoldAnnotation, Review  # noqa: E402

DATASET = "dhad-controlled-gold-v1"
LICENSE = "CC0-1.0"
SEED = 240721
DOMAINS = ("journalism", "academic", "administrative", "educational", "social", "dialect")

ORGANIZATIONS = (
    "الوزارة",
    "الجامعة",
    "المؤسسة",
    "اللجنة",
    "الهيئة",
    "المديرية",
    "الشركة",
    "المركز",
    "المجلس",
    "المدرسة",
    "المكتبة",
    "الصحيفة",
)
PEOPLE = (
    "أحمد",
    "سارة",
    "مريم",
    "علي",
    "ليلى",
    "يوسف",
    "نور",
    "حسن",
    "ريم",
    "عمر",
    "هدى",
    "سامر",
)
CONTEXTS = (
    "بعد مراجعة دقيقة",
    "وفق الخطة الجديدة",
    "في بداية الأسبوع",
    "خلال الاجتماع الأخير",
    "قبل نشر النسخة النهائية",
    "استنادًا إلى البيانات المتاحة",
    "مع توثيق جميع الملاحظات",
    "ضمن الجدول المعتمد",
    "بعد التشاور مع الفريق",
    "في المرحلة الحالية",
    "من دون تغيير المعنى",
    "بحسب المعايير المعلنة",
)
STUDIES = (
    "الدراسة الميدانية",
    "المراجعة المنهجية",
    "الورقة البحثية",
    "التحليل المقارن",
    "التجربة التعليمية",
    "الدراسة اللغوية",
    "المقالة العلمية",
    "المسح الإحصائي",
)
TOPICS = (
    "جودة التعليم",
    "وضوح الكتابة",
    "معالجة اللغة العربية",
    "إدارة المعرفة",
    "التواصل المؤسسي",
    "التعلم الرقمي",
    "سلامة البيانات",
    "تطوير المناهج",
)
DOCUMENTS = (
    "التقرير السنوي",
    "محضر الاجتماع",
    "طلب التحديث",
    "دليل الإجراءات",
    "مسودة القرار",
    "خطة المشروع",
    "سجل المراجعة",
    "وثيقة المتطلبات",
)


@dataclass(frozen=True, slots=True)
class Pattern:
    key: str
    category: str
    clean: str
    error: str
    targets: tuple[tuple[str, str], ...]
    severity: str = "error"
    supported: bool = True


MSA_PATTERNS = (
    Pattern(
        "hamza-ila",
        "spelling",
        "الانتقال إلى المرحلة التالية مناسب",
        "الانتقال الى المرحلة التالية مناسب",
        (("الى", "إلى"),),
    ),
    Pattern(
        "taa-result",
        "spelling",
        "النتيجة مهمة للفريق",
        "النتيجه مهمة للفريق",
        (("النتيجه", "النتيجة"),),
    ),
    Pattern(
        "taa-language",
        "spelling",
        "اللغة العربية واضحة",
        "اللغه العربية واضحة",
        (("اللغه", "اللغة"),),
    ),
    Pattern(
        "phrase-inshallah",
        "spelling",
        "سيكتمل العمل إن شاء الله",
        "سيكتمل العمل انشاء الله",
        (("انشاء الله", "إن شاء الله"),),
    ),
    Pattern(
        "unsupported-admin",
        "spelling",
        "الإدارة مسؤولة عن القرار",
        "الاداره مسؤولة عن القرار",
        (("الاداره", "الإدارة"),),
        supported=False,
    ),
    Pattern(
        "unsupported-relative",
        "spelling",
        "الموظفون الذين شاركوا حاضرون",
        "الموظفون اللذين شاركوا حاضرون",
        (("اللذين", "الذين"),),
        supported=False,
    ),
    Pattern(
        "number-feminine",
        "grammar",
        "ثلاث سنوات كافية للتقييم",
        "ثلاثة سنوات كافية للتقييم",
        (("ثلاثة سنوات", "ثلاث سنوات"),),
    ),
    Pattern(
        "number-masculine",
        "grammar",
        "ثلاثة كتب مفيدة للطلاب",
        "ثلاث كتب مفيدة للطلاب",
        (("ثلاث كتب", "ثلاثة كتب"),),
    ),
    Pattern(
        "unsupported-demonstrative",
        "grammar",
        "هذا الكتاب مفيد للطلاب",
        "هذه الكتاب مفيد للطلاب",
        (("هذه الكتاب", "هذا الكتاب"),),
        supported=False,
    ),
    Pattern(
        "latin-comma",
        "punctuation",
        "بدأ العمل، ثم استمر بهدوء",
        "بدأ العمل, ثم استمر بهدوء",
        ((",", "،"),),
        severity="warning",
    ),
    Pattern(
        "latin-question",
        "punctuation",
        "هل اكتمل التقرير؟",
        "هل اكتمل التقرير?",
        (("?", "؟"),),
        severity="warning",
    ),
    Pattern(
        "space-before",
        "punctuation",
        "اكتمل التقرير.",
        "اكتمل التقرير .",
        ((" .", "."),),
        severity="warning",
    ),
    Pattern(
        "repeat-word",
        "style",
        "وصل التقرير اليوم",
        "وصل التقرير التقرير اليوم",
        (("التقرير التقرير", "التقرير"),),
        severity="warning",
    ),
    Pattern(
        "tatweel",
        "style",
        "مرحبًا بجميع المشاركين",
        "مرحبـــــًا بجميع المشاركين",
        (("ـــــ", ""),),
        severity="hint",
    ),
)

DIALECT_PATTERNS = {
    "iraqi": Pattern(
        "dialect-iraqi",
        "dialect",
        "يوجد عمل الآن",
        "اكو شغل هسه",
        (("اكو", "يوجد"), ("شغل", "عمل"), ("هسه", "الآن")),
        severity="hint",
    ),
    "gulf": Pattern(
        "dialect-gulf",
        "dialect",
        "ماذا تريد الآن",
        "وش تبي الحين",
        (("وش", "ماذا"), ("تبي", "تريد"), ("الحين", "الآن")),
        severity="hint",
    ),
    "levantine": Pattern(
        "dialect-levantine",
        "dialect",
        "ماذا تفعل الآن",
        "شو تعمل هلق",
        (("شو", "ماذا"), ("هلق", "الآن")),
        severity="hint",
    ),
    "egyptian": Pattern(
        "dialect-egyptian",
        "dialect",
        "أريد المراجعة الآن",
        "عايز المراجعة دلوقتي",
        (("عايز", "أريد"), ("دلوقتي", "الآن")),
        severity="hint",
    ),
}

HARD_NEGATIVES = (
    "والى الوالي موظفًا جديدًا لمتابعة العمل",
    "نعم، نعم أؤكد أن التكرار هنا مقصود",
    "شرح المعلم الفرق بين شِعر وشَعر",
    "ورد الرمز x = 1 في المثال البرمجي",
    "راجع الرابط https://example.org/path?q=ضاد قبل المتابعة",
    "أرسل الملاحظة إلى writer@example.org اليوم",
)


def _split(index: int) -> str:
    bucket = index % 20
    if bucket < 14:
        return "train"
    if bucket < 17:
        return "dev"
    return "test"


def _domain_text(domain: str, phrase: str, index: int) -> str:
    org = ORGANIZATIONS[(index // 2) % len(ORGANIZATIONS)]
    person = PEOPLE[(index // 3) % len(PEOPLE)]
    context = CONTEXTS[(index // 5) % len(CONTEXTS)]
    study = STUDIES[(index // 7) % len(STUDIES)]
    topic = TOPICS[(index // 11) % len(TOPICS)]
    document = DOCUMENTS[(index // 13) % len(DOCUMENTS)]
    serial = (index % 97) + 1
    reference = 10000 + index
    if domain == "journalism":
        return f"أعلنت {org} في البيان رقم {serial} أن {phrase}، {context}، وفق المرجع الداخلي رقم {reference}."
    if domain == "academic":
        return (
            f"توضح {study} حول {topic} أن {phrase}، {context}، وفق المرجع الداخلي رقم {reference}."
        )
    if domain == "administrative":
        return f"ورد في {document} لدى {org} أن {phrase}، {context}، وفق المرجع الداخلي رقم {reference}."
    if domain == "educational":
        return f"شرح {person} للطلاب في الدرس رقم {serial} أن {phrase}، {context}، وفق المرجع الداخلي رقم {reference}."
    if domain == "social":
        return f"كتب {person} في النقاش العام أن {phrase}، {context}، وفق المرجع الداخلي رقم {reference}."
    return f"قال {person} في الحديث رقم {serial}: {phrase}، ثم أنهى كلامه {context}، وفق المرجع الداخلي رقم {reference}."


def _annotations(text: str, pattern: Pattern) -> tuple[GoldAnnotation, ...]:
    out: list[GoldAnnotation] = []
    cursor = 0
    for target, replacement in pattern.targets:
        offset = text.find(target, cursor)
        if offset < 0:
            raise RuntimeError(f"Target {target!r} missing from generated text")
        out.append(
            GoldAnnotation(
                category=pattern.category,
                offset=offset,
                length=len(target),
                accepted_replacements=(replacement,),
                label=pattern.key,
                severity=pattern.severity,
            )
        )
        cursor = offset + len(target)
    return tuple(out)


def _review_annotations(
    text: str, annotations: tuple[GoldAnnotation, ...]
) -> tuple[GoldAnnotation, ...]:
    """Second validation pass: reconstruct annotations from visible spans.

    This pass does not read YAML rules or engine output.  It verifies that each
    marked span exists, every correction differs from the source, and spans do
    not overlap before reproducing the annotation set.
    """

    previous_end = -1
    reviewed: list[GoldAnnotation] = []
    for annotation in sorted(annotations, key=lambda item: item.offset):
        source = text[annotation.offset : annotation.end]
        if not source or annotation.offset < previous_end:
            raise RuntimeError("Invalid or overlapping gold annotation")
        if any(replacement == source for replacement in annotation.accepted_replacements):
            raise RuntimeError("A gold replacement must change the source span")
        reviewed.append(annotation)
        previous_end = annotation.end
    return tuple(reviewed)


def build_cases(total: int = 5000) -> list[BenchmarkCase]:
    if total < 1000 or total % 20:
        raise ValueError("total must be at least 1000 and divisible by 20")
    randomizer = random.Random(SEED)
    cases: list[BenchmarkCase] = []
    for index in range(total):
        domain = DOMAINS[index % len(DOMAINS)]
        is_error = (index // len(DOMAINS)) % 2 == 1
        if domain == "dialect":
            dialect = tuple(DIALECT_PATTERNS)[(index // len(DOMAINS)) % 4]
            pattern = DIALECT_PATTERNS[dialect]
        else:
            dialect = "msa"
            pattern = MSA_PATTERNS[(index * 7 + index // 17) % len(MSA_PATTERNS)]

        if not is_error and index % 29 == 0:
            clean_phrase = HARD_NEGATIVES[(index // 29) % len(HARD_NEGATIVES)]
            pattern_key = "hard-negative"
        else:
            clean_phrase = pattern.clean
            pattern_key = pattern.key
        phrase = pattern.error if is_error else clean_phrase
        text = _domain_text(domain, phrase, index)
        annotations = _annotations(text, pattern) if is_error else ()
        reference_text = _domain_text(domain, pattern.clean if is_error else clean_phrase, index)
        case = BenchmarkCase(
            id=f"dcg1-{index + 1:05d}",
            text=text,
            domain=domain,
            split=_split(index),
            dialect=dialect,
            annotations=annotations,
            dataset=DATASET,
            license_id=LICENSE,
            synthetic=True,
            metadata={
                "pattern": pattern_key,
                "supported_at_creation": pattern.supported if is_error else None,
                "reference_text": reference_text,
                "generation_seed": SEED,
            },
        )
        cases.append(case)

    # Shuffle within each split to prevent pattern ordering while preserving exact counts.
    grouped = {
        split: [case for case in cases if case.split == split] for split in ("train", "dev", "test")
    }
    for group in grouped.values():
        randomizer.shuffle(group)
    ordered = grouped["train"] + grouped["dev"] + grouped["test"]

    # Attach exactly 1,000 independent validation passes, balanced across clean/error cases.
    review_candidates = sorted(
        ordered,
        key=lambda case: (len(case.annotations) > 1, case.id),
    )[:1000]
    reviewed_ids = {case.id for case in review_candidates}
    final: list[BenchmarkCase] = []
    for case in ordered:
        if case.id not in reviewed_ids:
            final.append(case)
            continue
        second = _review_annotations(case.text, case.annotations)
        final.append(
            BenchmarkCase(
                id=case.id,
                text=case.text,
                domain=case.domain,
                split=case.split,
                dialect=case.dialect,
                annotations=case.annotations,
                dataset=case.dataset,
                license_id=case.license_id,
                synthetic=case.synthetic,
                reviews=(
                    Review("template-annotation-pass", case.annotations),
                    Review("independent-span-validation-pass", second),
                ),
                metadata=case.metadata,
            )
        )
    return final


def _write_jsonl(path: Path, cases: Iterable[BenchmarkCase]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(case.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for case in cases
    )
    path.write_text(payload, encoding="utf-8")
    return payload.count("\n"), hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build(output_dir: Path, total: int = 5000) -> dict[str, object]:
    cases = build_cases(total)
    files: dict[str, dict[str, object]] = {}
    for split in ("train", "dev", "test"):
        selected = [case for case in cases if case.split == split]
        count, digest = _write_jsonl(output_dir / f"{split}.jsonl", selected)
        files[f"{split}.jsonl"] = {"cases": count, "sha256": digest}
    reviewed = [case for case in cases if case.reviews]
    count, digest = _write_jsonl(output_dir / "double_review.jsonl", reviewed)
    files["double_review.jsonl"] = {"cases": count, "sha256": digest}
    manifest = {
        "schema_version": 1,
        "dataset": DATASET,
        "version": "1.0.0",
        "license": LICENSE,
        "synthetic": True,
        "generation_seed": SEED,
        "total_cases": total,
        "double_review_cases": len(reviewed),
        "splits": {"train": 3500, "dev": 750, "test": 750},
        "domains": {domain: sum(case.domain == domain for case in cases) for domain in DOMAINS},
        "dialects": {
            dialect: sum(case.dialect == dialect for case in cases)
            for dialect in ("msa", "iraqi", "gulf", "levantine", "egyptian")
        },
        "files": files,
        "limitations": [
            "Controlled template corpus; not naturally occurring user text.",
            "Double review is two independent technical annotation passes, not human adjudication.",
            "Publishable real-world accuracy requires licensed natural corpora and human review.",
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "src" / "dhad" / "data" / "benchmarks" / "gold_v1",
    )
    parser.add_argument("--total", type=int, default=5000)
    args = parser.parse_args()
    manifest = build(args.output, args.total)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
