"""V2 Phase 3 — Python ⇄ Rust core parity.

Runs whenever the ``dhad_core`` extension (built from ``rust/dhad-core-rs``
via ``maturin build --features python``) is importable, and skips cleanly on
machines without the Rust toolchain. Python remains the reference
implementation; every assertion is Python-output == Rust-output.
"""

import random
import json
from dataclasses import asdict

import pytest

dhad_core = pytest.importorskip("dhad_core")

from dhad.text import NormalizationMode, normalize, sentence_spans, tokenize  # noqa: E402
from dhad.morphology import MorphologicalAnalyzer  # noqa: E402
from dhad.syntax import SyntaxEngine  # noqa: E402

CORPUS = [
    "",
    "ذهبت الى المدرسه صباحا والتقيت بالمعلم الجديد.",
    "ذَهَبَ الوَلَدُ إِلى المَدْرَسَةِ مُسْرِعًا!",
    "قرأ ٣٫١٤ ثم ١٢٬٣٤٥ من الكتب.",
    "1. البند الأول\n2. البند الثاني\n٣. البند الثالث.",
    "زار د. أحمد المستشفى. ثم غادر e.g. مثال.",
    "زر https://example.com/ar?x=1، ثم راسل test@example.com.",
    "الوسم #ضاد و@مستخدم و`الرمز` هنا.",
    "هل جئت؟ نعم! رائع… إذن؛ الآن.",
    "الســــلام عليكم — أإآٱ ىئؤة!",
    "Latin مع l'élève naïve و co-op و 10.5% و ٥٠٪.",
    "قال: «اذهب.» ثم صمت.",
]

_WORD_POOL = "ذهبت الى المدرسه اليوم د. ٣٫١٤ https://a.b «قال» #وسم 12. hello ة ياء".split()


def _random_texts(count=60, seed=20260721):
    rng = random.Random(seed)
    for _ in range(count):
        yield " ".join(rng.choice(_WORD_POOL) for _ in range(rng.randrange(0, 25)))


def _all_inputs():
    yield from CORPUS
    yield from _random_texts()


class TestNormalizeParity:
    @pytest.mark.parametrize("mode", [m.value for m in NormalizationMode])
    def test_all_modes_all_inputs(self, mode):
        for text in _all_inputs():
            assert dhad_core.normalize(text, mode) == normalize(text, mode), (mode, text)

    def test_rejects_unknown_mode(self):
        with pytest.raises(ValueError):
            dhad_core.normalize("نص", "bogus")


class TestSentenceParity:
    def test_all_inputs(self):
        for text in _all_inputs():
            expected = [
                (item.text, item.start, item.end, item.terminator)
                for item in sentence_spans(text)
            ]
            assert dhad_core.sentence_spans(text) == expected, text


class TestTokenParity:
    def test_lossless_stream(self):
        for text in _all_inputs():
            expected = [
                (token.text, token.start, token.end, token.kind.value)
                for token in tokenize(text, include_non_words=True)
            ]
            assert dhad_core.tokenize(text, True) == expected, text

    def test_content_tokens(self):
        for text in _all_inputs():
            expected = [
                (token.text, token.start, token.end, token.kind.value)
                for token in tokenize(text)
            ]
            assert dhad_core.tokenize(text, False) == expected, text


def _analysis_payload(item):
    return {
        "token": item.token,
        "normalized": item.normalized,
        "stem": item.stem,
        "lemma": item.lemma,
        "root": item.root,
        "pattern": item.pattern,
        "pos": item.pos,
        "prefixes": [asdict(part) for part in item.prefixes],
        "suffixes": [asdict(part) for part in item.suffixes],
        "infixes": [asdict(part) for part in item.infixes],
        "features": dict(item.features),
        "confidence": item.confidence,
        "source": item.source,
        "frequency": item.frequency,
    }


def _parse_payload(parsed):
    return {
        "text": parsed.text,
        "sentences": [
            {
                "text": sentence.text,
                "start": sentence.start,
                "end": sentence.end,
                "tokens": [
                    {
                        "text": token.text,
                        "start": token.start,
                        "end": token.end,
                        "analysis": _analysis_payload(token.analysis) if token.analysis else None,
                        "alternatives": [_analysis_payload(item) for item in token.alternatives],
                        "confidence": token.confidence,
                        "break_before": token.break_before,
                    }
                    for token in sentence.tokens
                ],
                "relations": [
                    {
                        "relation": item.relation.value,
                        "head_index": item.head_index,
                        "dependent_index": item.dependent_index,
                        "confidence": item.confidence,
                        "governor": item.governor,
                        "explanation": item.explanation,
                    }
                    for item in sentence.relations
                ],
                "irab": [asdict(item) for item in sentence.irab],
                "confidence": sentence.confidence,
            }
            for sentence in parsed.sentences
        ],
    }


def _match_payload(item):
    payload = asdict(item)
    for field in ("tags", "references", "profiles"):
        payload[field] = list(payload[field])
    return payload


class TestMorphologyParity:
    @pytest.mark.parametrize(
        "token",
        [
            "كتابة",
            "وبالمدرسة",
            "للمدرسة",
            "مدرستها",
            "سيكتبون",
            "يقول",
            "المهندسين",
            "استعمال",
            "زمردة",
            "كِتَاب",
            "Dhad",
            "؟",
        ],
    )
    def test_full_ranked_analysis_payload(self, token):
        expected = [_analysis_payload(item) for item in MorphologicalAnalyzer().analyze(token)]
        assert json.loads(dhad_core.analyze_json(token)) == expected

    def test_confidence_filter_and_validation(self):
        expected = [_analysis_payload(item) for item in MorphologicalAnalyzer().analyze("استعمال", min_confidence=0.7)]
        assert json.loads(dhad_core.analyze_json("استعمال", 0.7)) == expected
        with pytest.raises(ValueError):
            dhad_core.analyze_json("كتاب", 1.1)


class TestSyntaxParity:
    @pytest.mark.parametrize(
        "text",
        [
            "هذا الكتاب مفيد. في المدرستين طالبان.",
            "هذه الكتاب",
            "المدينة المفيد",
            "وصل الطالبة",
            "الطالبة يكتب",
            "كتابٌ الطالب",
            "مهندسون الشركة",
            "بالمدرستان",
            "لن يكتبون",
            "هذه، الكتاب",
            "😀 هذه الكتاب. ثم في المدرستين.",
        ],
    )
    def test_full_parse_payload(self, text):
        assert json.loads(dhad_core.parse_json(text)) == _parse_payload(SyntaxEngine().parse(text))

    @pytest.mark.parametrize(
        "text",
        [
            "هذه الكتاب",
            "المدينة المفيد",
            "وصل الطالبة",
            "الطالبة يكتب",
            "كتابٌ الطالب",
            "في المدرستان",
            "لن يكتبون",
            "😀 هذه الكتاب",
        ],
    )
    def test_full_grammar_match_payload(self, text):
        expected = [_match_payload(item) for item in SyntaxEngine().check_text(text)]
        assert json.loads(dhad_core.syntax_check_json(text)) == expected
