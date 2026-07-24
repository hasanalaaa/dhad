from __future__ import annotations

import json

import pytest

from dhad import Dhad
from dhad.cli import main as cli_main
from dhad.morphology import default_analyzer
from dhad.neural import (
    CandidateScore,
    HybridNeuralEngine,
    NeuralTask,
    StatisticalContextBackend,
    TransformerBackend,
)
from dhad.syntax import default_syntax_engine


def test_statistical_model_loads_and_is_available() -> None:
    backend = StatisticalContextBackend()
    assert backend.available is True
    assert backend.version == "1.0.0"
    assert backend.candidate_labels(NeuralTask.WORD_SENSE, "كتب") == (
        "كتب|verb|كتب",
        "كتاب|noun|كتب",
    )


def test_wsd_selects_verb_from_existing_morphology_candidates() -> None:
    checker = Dhad()
    deterministic = checker.parse("كتب الطالب الدرس", neural_refine=False)
    refined = checker.parse("كتب الطالب الدرس")
    assert deterministic.sentences[0].tokens[0].pos == "noun"
    token = refined.sentences[0].tokens[0]
    assert token.pos == "verb"
    assert token.analysis is not None and token.analysis.lemma == "كتب"
    assert token.text == "كتب" and token.start == 0 and token.end == 3


def test_wsd_selects_plural_noun_before_adjective() -> None:
    token = Dhad().parse("ثلاثة كتب مفيدة").sentences[0].tokens[1]
    assert token.pos == "noun"
    assert token.analysis is not None and token.analysis.lemma == "كتاب"


def test_report_is_auditable_and_records_confidence_margin() -> None:
    report = Dhad().neural_report("كتب الطالب الدرس")
    decision = next(item for item in report.decisions if item.task == NeuralTask.WORD_SENSE)
    assert decision.changed is True
    assert decision.confidence > 0.98
    assert decision.margin > 0.90
    assert decision.backend.startswith("statistical-ngram/")
    assert decision.evidence


def test_contextual_real_word_suggestion_is_never_safe_autofix() -> None:
    checker = Dhad(lexical_spellcheck=False)
    matches = checker.check("قابل علم الفيزياء")
    neural = [item for item in matches if item.category == "neural_suggestion"]
    assert len(neural) == 1
    assert neural[0].replacements == ["عالم"]
    assert neural[0].confidence > 0.99
    assert neural[0].autofix is False
    assert checker.correct("قابل علم الفيزياء") == "قابل علم الفيزياء"
    assert checker.correct("قابل علم الفيزياء", mode="all") == "قابل عالم الفيزياء"


def test_context_model_stays_silent_without_strong_context() -> None:
    checker = Dhad(lexical_spellcheck=False)
    for text in ("هذا علم نافع", "زار عالم الفيزياء", "رفع العلم فوق المبنى"):
        assert not [item for item in checker.check(text) if item.category == "neural_suggestion"]


class CountingBackend:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "counting-test"

    @property
    def available(self) -> bool:
        return True

    def score(self, request):
        self.calls += 1
        return tuple(
            CandidateScore(candidate.label, 1.0 if index == 0 else 0.0, 1.0 - index)
            for index, candidate in enumerate(request.candidates)
        )


def test_high_confidence_unambiguous_tokens_never_reach_backend() -> None:
    backend = CountingBackend()
    engine = HybridNeuralEngine(default_analyzer(), default_syntax_engine(), backend)
    parsed = default_syntax_engine().parse("الطالب مجتهد")
    report = engine.report("الطالب مجتهد", parsed=parsed)
    assert backend.calls == 0
    assert report.triggered_tokens == 0


def test_neural_layer_can_be_disabled_without_changing_public_api() -> None:
    checker = Dhad(neural_checks=False)
    assert checker.neural is None
    assert checker.parse("كتب الطالب الدرس").sentences[0].tokens[0].pos == "noun"
    assert not [
        item for item in checker.check("قابل علم الفيزياء") if item.category == "neural_suggestion"
    ]


def test_enabled_category_can_select_neural_suggestions_only() -> None:
    matches = Dhad(enabled_categories={"neural_suggestion"}, lexical_spellcheck=False).check(
        "قابل علم الفيزياء"
    )
    assert len(matches) == 1
    assert matches[0].category == "neural_suggestion"


def test_transformer_backend_is_lazy_and_validates_configuration() -> None:
    backend = TransformerBackend("local/model")
    assert backend.name == "transformer/local/model"
    with pytest.raises(ValueError):
        TransformerBackend("")
    with pytest.raises(ValueError):
        TransformerBackend("model", max_length=8)


def test_cli_neural_json_report(capsys) -> None:
    assert cli_main(["neural", "كتب الطالب الدرس", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backend"].startswith("statistical-ngram/")
    assert payload["decisions"][0]["task"] == "word_sense"
    assert payload["refined_sentences"][0]["tokens"][0]["pos"] == "verb"
