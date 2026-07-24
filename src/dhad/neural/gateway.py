"""Confidence-gated hybrid orchestration over deterministic Arabic NLP."""

from __future__ import annotations

import math
from dataclasses import replace
from functools import lru_cache
from typing import Iterable, Sequence

from ..match import Match
from ..morphology import MorphologicalAnalysis, MorphologicalAnalyzer, default_analyzer
from ..syntax import DocumentParse, SentenceParse, SyntaxEngine, SyntaxToken, default_syntax_engine
from ..text import NormalizationMode, normalize
from .backend import NeuralBackend
from .statistical import default_statistical_backend
from .types import (
    CandidateScore,
    NeuralCandidate,
    NeuralDecision,
    NeuralReport,
    NeuralRequest,
    NeuralTask,
)


def _surface(value: str) -> str:
    return normalize(value, NormalizationMode.LOOKUP)


def _analysis_label(analysis: MorphologicalAnalysis) -> str:
    return f"{analysis.lemma}|{analysis.pos}|{analysis.root or '-'}"


def _probability_margin(scores: Sequence[CandidateScore]) -> tuple[float, float]:
    if not scores:
        return 0.0, 0.0
    first = scores[0].probability
    second = scores[1].probability if len(scores) > 1 else 0.0
    return first, max(0.0, first - second)


class HybridNeuralEngine:
    """Use contextual models only where deterministic confidence is insufficient.

    The engine cannot create or replace a high-confidence deterministic
    analysis. Word-sense decisions are constrained to morphology candidates
    already produced by Dhad. Contextual spelling is constrained to configured
    confusion sets and requires an extreme probability before it is surfaced.
    """

    def __init__(
        self,
        morphology: MorphologicalAnalyzer | None = None,
        syntax: SyntaxEngine | None = None,
        backend: NeuralBackend | None = None,
        *,
        ambiguity_confidence_threshold: float = 0.86,
        alternative_margin_threshold: float = 0.08,
        wsd_accept_threshold: float = 0.78,
        wsd_margin_threshold: float = 0.18,
        spelling_accept_threshold: float = 0.985,
        spelling_margin_threshold: float = 0.70,
    ):
        thresholds = (
            ambiguity_confidence_threshold,
            alternative_margin_threshold,
            wsd_accept_threshold,
            wsd_margin_threshold,
            spelling_accept_threshold,
            spelling_margin_threshold,
        )
        if any(not 0.0 <= value <= 1.0 for value in thresholds):
            raise ValueError("Neural confidence thresholds must be between 0 and 1")
        self.morphology = morphology or default_analyzer()
        self.syntax = syntax or default_syntax_engine()
        self.backend = backend or default_statistical_backend()
        self.ambiguity_confidence_threshold = ambiguity_confidence_threshold
        self.alternative_margin_threshold = alternative_margin_threshold
        self.wsd_accept_threshold = wsd_accept_threshold
        self.wsd_margin_threshold = wsd_margin_threshold
        self.spelling_accept_threshold = spelling_accept_threshold
        self.spelling_margin_threshold = spelling_margin_threshold

    @property
    def available(self) -> bool:
        return bool(self.backend.available)

    @staticmethod
    def _distinct_analyses(token: SyntaxToken) -> tuple[MorphologicalAnalysis, ...]:
        values = ((token.analysis,) if token.analysis is not None else ()) + token.alternatives
        unique: dict[str, MorphologicalAnalysis] = {}
        for analysis in values:
            label = _analysis_label(analysis)
            current = unique.get(label)
            if current is None or analysis.confidence > current.confidence:
                unique[label] = analysis
        return tuple(unique.values())

    def _ambiguous(self, token: SyntaxToken) -> bool:
        analyses = self._distinct_analyses(token)
        if len(analyses) < 2:
            return False
        ordered = sorted(analyses, key=lambda item: -item.confidence)
        margin = ordered[0].confidence - ordered[1].confidence
        return (
            token.confidence < self.ambiguity_confidence_threshold
            or margin <= self.alternative_margin_threshold
        )

    @staticmethod
    def _request(
        task: NeuralTask,
        sentence: SentenceParse,
        token_index: int,
        candidates: Sequence[NeuralCandidate],
    ) -> NeuralRequest:
        return NeuralRequest(
            task=task,
            sentence_text=sentence.text,
            sentence_start=sentence.start,
            token_index=token_index,
            tokens=tuple(token.text for token in sentence.tokens),
            parts_of_speech=tuple(token.pos for token in sentence.tokens),
            candidates=tuple(candidates),
            metadata=(("parse_confidence", f"{sentence.confidence:.6f}"),),
        )

    def _wsd_decision(
        self, sentence: SentenceParse, token_index: int
    ) -> tuple[MorphologicalAnalysis | None, NeuralDecision | None]:
        token = sentence.tokens[token_index]
        if not self._ambiguous(token):
            return None, None
        analyses = self._distinct_analyses(token)
        candidates = tuple(
            NeuralCandidate(
                label=_analysis_label(analysis),
                value=token.text,
                lemma=analysis.lemma,
                pos=analysis.pos,
                root=analysis.root,
                prior=math.log(max(analysis.confidence, 1e-6)) * 0.08,
            )
            for analysis in analyses
        )
        request = self._request(NeuralTask.WORD_SENSE, sentence, token_index, candidates)
        scores = self.backend.score(request)
        confidence, margin = _probability_margin(scores)
        if confidence < self.wsd_accept_threshold or margin < self.wsd_margin_threshold:
            return None, None
        selected = next(
            (analysis for analysis in analyses if _analysis_label(analysis) == scores[0].label),
            None,
        )
        if selected is None:
            return None, None
        changed = token.analysis is None or _analysis_label(selected) != _analysis_label(
            token.analysis
        )
        decision = NeuralDecision(
            task=NeuralTask.WORD_SENSE,
            token=token.text,
            offset=token.start,
            length=token.end - token.start,
            selected_label=scores[0].label,
            confidence=confidence,
            margin=margin,
            backend=self.backend.name,
            evidence=scores[0].evidence,
            changed=changed,
        )
        return selected, decision

    def refine_sentence(
        self, sentence: SentenceParse
    ) -> tuple[SentenceParse, tuple[NeuralDecision, ...], int, int]:
        """Re-rank only low-confidence deterministic morphology candidates."""

        if not self.available:
            return sentence, (), 0, 0
        tokens = list(sentence.tokens)
        decisions: list[NeuralDecision] = []
        triggered = skipped = 0
        for index, token in enumerate(sentence.tokens):
            if not self._ambiguous(token):
                skipped += int(token.analysis is not None and bool(token.alternatives))
                continue
            triggered += 1
            selected, decision = self._wsd_decision(sentence, index)
            if selected is None or decision is None:
                continue
            decisions.append(decision)
            if not decision.changed:
                continue
            alternatives = tuple(
                analysis
                for analysis in self._distinct_analyses(token)
                if _analysis_label(analysis) != _analysis_label(selected)
            )
            tokens[index] = replace(
                token,
                analysis=selected,
                alternatives=alternatives,
                confidence=min(0.949, max(token.confidence, decision.confidence * 0.94)),
            )
        if tuple(tokens) == sentence.tokens:
            return sentence, tuple(decisions), triggered, skipped
        return (
            self.syntax.rebuild_sentence(sentence, tuple(tokens)),
            tuple(decisions),
            triggered,
            skipped,
        )

    def refine_parse(
        self, parsed: DocumentParse
    ) -> tuple[DocumentParse, tuple[NeuralDecision, ...], int, int]:
        sentences: list[SentenceParse] = []
        decisions: list[NeuralDecision] = []
        triggered = skipped = 0
        for sentence in parsed.sentences:
            refined, sentence_decisions, sentence_triggered, sentence_skipped = (
                self.refine_sentence(sentence)
            )
            sentences.append(refined)
            decisions.extend(sentence_decisions)
            triggered += sentence_triggered
            skipped += sentence_skipped
        return DocumentParse(parsed.text, tuple(sentences)), tuple(decisions), triggered, skipped

    def _contextual_candidates(self, token: str) -> tuple[str, ...]:
        provider = getattr(self.backend, "candidate_labels", None)
        if provider is None:
            return ()
        return tuple(provider(NeuralTask.CONTEXTUAL_SPELLING, token))

    def _contextual_suggestion(
        self, sentence: SentenceParse, token_index: int
    ) -> tuple[Match | None, NeuralDecision | None]:
        token = sentence.tokens[token_index]
        labels = self._contextual_candidates(token.text)
        current = _surface(token.text)
        if len(labels) < 2 or current not in labels:
            return None, None
        low_confidence_context = (
            token.confidence < 0.80 or sentence.confidence < 0.65 or self._ambiguous(token)
        )
        if not low_confidence_context:
            return None, None
        candidates: list[NeuralCandidate] = []
        for value in labels:
            analysis = (
                token.analysis
                if value == current and token.analysis is not None
                else self.morphology.best(value, min_confidence=0.70)
            )
            if analysis is None:
                continue
            candidates.append(
                NeuralCandidate(
                    label=value,
                    value=value,
                    lemma=analysis.lemma,
                    pos=analysis.pos,
                    root=analysis.root,
                    prior=0.0,
                )
            )
        if len(candidates) < 2:
            return None, None
        request = self._request(NeuralTask.CONTEXTUAL_SPELLING, sentence, token_index, candidates)
        scores = self.backend.score(request)
        confidence, margin = _probability_margin(scores)
        if (
            not scores
            or scores[0].label == current
            or confidence < self.spelling_accept_threshold
            or margin < self.spelling_margin_threshold
        ):
            return None, None
        replacement = scores[0].label
        decision = NeuralDecision(
            task=NeuralTask.CONTEXTUAL_SPELLING,
            token=token.text,
            offset=token.start,
            length=token.end - token.start,
            selected_label=replacement,
            confidence=confidence,
            margin=margin,
            backend=self.backend.name,
            evidence=scores[0].evidence,
            changed=True,
        )
        match = Match(
            rule_id="NEURAL_CONTEXTUAL_SPELLING",
            category="neural_suggestion",
            message="قد تكون الكلمة صحيحة إملائيًا لكنها غير ملائمة لهذا السياق.",
            offset=token.start,
            length=token.end - token.start,
            replacements=[replacement],
            severity="warning",
            explanation=(
                "اقتراح احتمالي شديد التحفظ مبني على سياق الكلمات المجاورة. "
                "لا يطبق تلقائيًا ويحتاج موافقة صريحة."
            ),
            autofix=False,
            confidence=confidence,
            priority=36,
            tags=("neural", "contextual-spelling", self.backend.name),
            profiles=("default",),
        )
        return match, decision

    def report(self, text: str, *, parsed: DocumentParse | None = None) -> NeuralReport:
        """Return refined parsing plus opt-in probabilistic suggestions."""

        deterministic = parsed or self.syntax.parse(text)
        refined, decisions, triggered, skipped = self.refine_parse(deterministic)
        suggestions: list[Match] = []
        contextual_decisions: list[NeuralDecision] = []
        if self.available:
            for sentence in refined.sentences:
                for index in range(len(sentence.tokens)):
                    match, decision = self._contextual_suggestion(sentence, index)
                    if match is not None and decision is not None:
                        suggestions.append(match)
                        contextual_decisions.append(decision)
        return NeuralReport(
            refined_parse=refined,
            decisions=decisions + tuple(contextual_decisions),
            suggestions=tuple(suggestions),
            triggered_tokens=triggered,
            skipped_high_confidence=skipped,
            backend=self.backend.name,
        )

    def check_text(
        self,
        text: str,
        *,
        parsed: DocumentParse | None = None,
        blocked: Iterable[Match] = (),
    ) -> list[Match]:
        """Return non-overlapping probabilistic suggestions only."""

        from ..spans import filter_non_overlapping

        return filter_non_overlapping(
            self.report(text, parsed=parsed).suggestions, tuple(blocked)
        )


@lru_cache(maxsize=1)
def default_neural_engine() -> HybridNeuralEngine:
    """Return the shared default hybrid layer."""

    return HybridNeuralEngine(
        default_analyzer(), default_syntax_engine(), default_statistical_backend()
    )
