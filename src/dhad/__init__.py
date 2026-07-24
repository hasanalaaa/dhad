"""ضاد — المساعد الكتابي العربي مفتوح المصدر."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Literal

from .analysis import AnalysisContext
from .checks import run_builtin_checks
from .diacritics import (
    DiacriticsEngine,
    DiacritizationMode,
    DiacritizationResult,
    DiacritizedToken,
    default_diacritics_engine,
)
from .dialects import (
    DialectConversion,
    DialectEngine,
    DialectIdentification,
    DialectLabel,
    DialectReport,
    default_dialect_engine,
)
from .match import CATEGORIES, Match, dedupe
from .morphology import (
    MorphologicalAnalysis,
    MorphologicalAnalyzer,
    MorphologyBackend,
    default_analyzer,
)
from .spellcheck import SpellChecker, default_spellchecker
from .neural import (
    HybridNeuralEngine,
    NeuralBackend,
    NeuralDecision,
    NeuralReport,
    NeuralTask,
    OnnxBackend,
    StatisticalContextBackend,
    TransformerBackend,
    default_neural_engine,
    onnx_backend_from_env,
)
from .style import (
    ReadabilityMetrics,
    StyleEngine,
    StyleProfile,
    StyleReport,
    ToneAnalysis,
    ToneClassifier,
    ToneEvidence,
    ToneLabel,
    default_style_engine,
)
from .syntax import (
    DocumentParse,
    IrabCandidate,
    RelationType,
    SentenceParse,
    SyntacticRelation,
    SyntaxEngine,
    SyntaxToken,
    default_syntax_engine,
)
from .semantics import (
    ConsistencyChoice,
    DocumentConsistencyTracker,
    SemanticEngine,
    SemanticReport,
    SemanticResource,
    default_semantic_engine,
)
if TYPE_CHECKING:
    from .crdt import CrdtDocument
from .incremental import DOCUMENT_CATEGORIES, IncrementalSession, UpdateStats
from .intelligence import (
    LinguisticExplanation,
    SuggestionChip,
    VocabularyMetrics,
    WritingIntelligenceReport,
    WritingTarget,
    build_writing_intelligence_report,
    vocabulary_metrics,
)
from .analytics import SentenceInsight, ToneBalance, WritingAnalytics, build_analytics
from .rewriting import (
    RewriteCandidate,
    RewriteChange,
    RewriteMode,
    RewriteReport,
    rewrite_text,
)
from .templates import (
    GeneratedDocument,
    TemplateField,
    TemplateId,
    WritingTemplate,
    generate_document,
    list_templates,
)
from .privacy import MaskedText, PrivacyEngine
from .rules import RuleEngine
from .spans import filter_non_overlapping
from .stylometry import (
    FeatureDeviation,
    StyleFingerprint,
    VoiceDeviationReport,
    VoiceProfile,
    extract_fingerprint,
    personalize_matches,
)
from .suppression import Suppression, apply_suppression

__version__ = "1.0.0"


def __getattr__(name: str) -> Any:
    """Load optional heavy integration surfaces only when requested."""

    if name == "CrdtDocument":
        from .crdt import CrdtDocument

        globals()[name] = CrdtDocument
        return CrdtDocument
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Dhad",
    "AnalysisContext",
    "DialectEngine",
    "DialectLabel",
    "DialectIdentification",
    "DialectConversion",
    "DialectReport",
    "Match",
    "MorphologicalAnalysis",
    "MorphologicalAnalyzer",
    "MorphologyBackend",
    "SpellChecker",
    "HybridNeuralEngine",
    "NeuralBackend",
    "NeuralDecision",
    "NeuralReport",
    "NeuralTask",
    "StatisticalContextBackend",
    "TransformerBackend",
    "OnnxBackend",
    "onnx_backend_from_env",
    "SyntaxEngine",
    "SyntaxToken",
    "SyntacticRelation",
    "RelationType",
    "IrabCandidate",
    "SentenceParse",
    "DocumentParse",
    "StyleEngine",
    "StyleProfile",
    "StyleReport",
    "ReadabilityMetrics",
    "ToneClassifier",
    "ToneAnalysis",
    "ToneEvidence",
    "ToneLabel",
    "DiacriticsEngine",
    "DiacritizationMode",
    "DiacritizationResult",
    "DiacritizedToken",
    "SemanticEngine",
    "SemanticReport",
    "SemanticResource",
    "ConsistencyChoice",
    "DocumentConsistencyTracker",
    "PrivacyEngine",
    "MaskedText",
    "IncrementalSession",
    "UpdateStats",
    "WritingIntelligenceReport",
    "VocabularyMetrics",
    "SuggestionChip",
    "LinguisticExplanation",
    "WritingTarget",
    "RewriteMode",
    "RewriteChange",
    "RewriteCandidate",
    "RewriteReport",
    "WritingAnalytics",
    "SentenceInsight",
    "ToneBalance",
    "TemplateId",
    "TemplateField",
    "WritingTemplate",
    "GeneratedDocument",
    "generate_document",
    "list_templates",
    "CrdtDocument",
    "DOCUMENT_CATEGORIES",
    "StyleFingerprint",
    "FeatureDeviation",
    "VoiceDeviationReport",
    "VoiceProfile",
    "extract_fingerprint",
    "personalize_matches",
    "Suppression",
    "CATEGORIES",
    "__version__",
]


class Dhad:
    """Public API combining Rule Engine v2 and built-in deterministic checks."""

    def __init__(
        self,
        rules_dir=None,
        enabled_categories: set[str] | None = None,
        profiles: Iterable[str] = ("default",),
        *,
        morphology: MorphologicalAnalyzer | None = None,
        lexical_spellcheck: bool = True,
        syntax: SyntaxEngine | None = None,
        syntax_checks: bool = True,
        dialects: DialectEngine | None = None,
        dialect_checks: bool = True,
        style: StyleEngine | None = None,
        style_checks: bool = True,
        style_profile: StyleProfile | str = StyleProfile.GENERAL,
        neural: HybridNeuralEngine | None = None,
        neural_checks: bool = True,
        diacritics: DiacriticsEngine | None = None,
        semantics: SemanticEngine | None = None,
        semantic_checks: bool = True,
        privacy: PrivacyEngine | None = None,
        pii_masking: bool = True,
    ):
        self.engine = RuleEngine(rules_dir) if rules_dir else RuleEngine()
        self.morphology = morphology or default_analyzer()
        if not lexical_spellcheck:
            self.spellchecker = None
        elif morphology is None:
            self.spellchecker = default_spellchecker()
        else:
            self.spellchecker = SpellChecker(self.morphology)
        if not syntax_checks:
            self.syntax = None
        elif syntax is not None:
            self.syntax = syntax
        elif morphology is None:
            self.syntax = default_syntax_engine()
        else:
            self.syntax = SyntaxEngine(self.morphology)
        if not dialect_checks:
            self.dialects = None
        elif dialects is not None:
            self.dialects = dialects
        elif morphology is None and syntax is None:
            self.dialects = default_dialect_engine()
        else:
            dialect_syntax = self.syntax or syntax or SyntaxEngine(self.morphology)
            self.dialects = DialectEngine(self.morphology, dialect_syntax)
        if not style_checks:
            self.style = None
        elif style is not None:
            self.style = style
        elif morphology is None and syntax is None:
            self.style = default_style_engine(style_profile)
        else:
            style_syntax = self.syntax or syntax or SyntaxEngine(self.morphology)
            self.style = StyleEngine(
                self.morphology,
                style_syntax,
                profile=style_profile,
            )
        if not neural_checks:
            self.neural = None
        elif neural is not None:
            self.neural = neural
        elif morphology is None and syntax is None:
            self.neural = default_neural_engine()
        else:
            neural_syntax = self.syntax or syntax or SyntaxEngine(self.morphology)
            self.neural = HybridNeuralEngine(self.morphology, neural_syntax)
        shared_syntax = self.syntax or syntax or SyntaxEngine(self.morphology)
        if diacritics is not None:
            self.diacritics = diacritics
        elif morphology is None and syntax is None:
            self.diacritics = default_diacritics_engine()
        else:
            self.diacritics = DiacriticsEngine(self.morphology, shared_syntax)
        if not semantic_checks:
            self.semantics = None
        elif semantics is not None:
            self.semantics = semantics
        elif morphology is None and syntax is None:
            self.semantics = default_semantic_engine()
        else:
            self.semantics = SemanticEngine(shared_syntax)
        self.privacy = (privacy or PrivacyEngine()) if pii_masking else None
        self.dialect_checks_enabled = dialect_checks
        self.enabled_categories = enabled_categories
        self.profiles = frozenset(profiles)
        if not self.profiles:
            raise ValueError("At least one rule profile must be active")

    def _mask(self, text: str) -> MaskedText:
        """Return a same-length private processing view for one document."""

        if self.privacy is None:
            return MaskedText(text, text, ())
        return self.privacy.mask(text)

    def analysis_context(
        self,
        text: str,
        *,
        parsed: DocumentParse | None = None,
        neural_refine: bool = False,
    ) -> AnalysisContext:
        """Build reusable analysis state for one exact document revision.

        The deterministic syntax parse, token stream, normalized lookup forms,
        and sentence index are constructed once and can be passed to individual
        engines. Neural refinement is opt-in so callers control whether an
        external backend may participate.
        """

        if parsed is None:
            syntax_engine = self.syntax or SyntaxEngine(self.morphology)
            parsed = syntax_engine.parse(text)
        context = AnalysisContext.build(text, parsed=parsed)
        if neural_refine and self.neural is not None:
            refined = self.neural.report(text, parsed=parsed).refined_parse
            context = context.with_parse(refined)
        return context

    def _check_private(
        self,
        text: str,
        private: MaskedText,
        *,
        parsed: DocumentParse | None,
        context: AnalysisContext,
        suppression: Suppression | None,
        profiles: Iterable[str] | None,
        diacritics_mode: DiacritizationMode | str | None,
    ) -> list[Match]:
        """Run all diagnostic layers over one already-masked document revision."""

        working_text = private.masked_text
        active_profiles = self.profiles if profiles is None else frozenset(profiles)
        if not active_profiles:
            raise ValueError("At least one rule profile must be active")
        matches = self.engine.check(
            working_text,
            profiles=active_profiles,
            context=context,
        ) + run_builtin_checks(working_text)
        neural_suggestions: tuple[Match, ...] = ()
        if self.neural is not None and parsed is not None:
            neural_report = self.neural.report(working_text, parsed=parsed)
            parsed = neural_report.refined_parse
            context = context.with_parse(parsed)
            neural_suggestions = neural_report.suggestions
        if self.dialects is not None and (
            self.enabled_categories is None or "dialect" in self.enabled_categories
        ):
            matches.extend(
                self.dialects.check_text(working_text, parsed=parsed, context=context)
            )
        if self.semantics is not None and (
            self.enabled_categories is None
            or bool({"semantics", "consistency"} & self.enabled_categories)
        ):
            semantic_matches = self.semantics.check_text(
                working_text, parsed=parsed, context=context
            )
            semantic_matches = filter_non_overlapping(semantic_matches, matches)
            matches.extend(semantic_matches)
        if self.spellchecker is not None:
            lexical_matches = self.spellchecker.check_text(working_text, tokens=context.tokens)
            lexical_matches = filter_non_overlapping(lexical_matches, matches)
            matches.extend(lexical_matches)
        if self.syntax is not None and parsed is not None:
            syntax_matches = [
                candidate
                for sentence in parsed.sentences
                for candidate in self.syntax.check_parse(sentence)
            ]
            syntax_matches = filter_non_overlapping(syntax_matches, matches)
            matches.extend(syntax_matches)
        if self.style is not None and (
            self.enabled_categories is None or "style" in self.enabled_categories
        ):
            style_matches = self.style.check_text(
                working_text, parsed=parsed, context=context
            )
            style_matches = filter_non_overlapping(style_matches, matches)
            matches.extend(style_matches)
        if diacritics_mode is not None:
            diacritics_matches = self.diacritics.suggestions(
                working_text, mode=diacritics_mode, parsed=parsed
            )
            diacritics_matches = filter_non_overlapping(diacritics_matches, matches)
            matches.extend(diacritics_matches)
        if self.enabled_categories is None or "neural_suggestion" in self.enabled_categories:
            matches.extend(filter_non_overlapping(neural_suggestions, matches))
        matches = private.filter_matches(matches)
        if self.enabled_categories is not None:
            matches = [match for match in matches if match.category in self.enabled_categories]
        matches = apply_suppression(text, matches, suppression)
        return dedupe(matches)

    def check(
        self,
        text: str,
        *,
        suppression: Suppression | None = None,
        profiles: Iterable[str] | None = None,
        diacritics_mode: DiacritizationMode | str | None = None,
    ) -> list[Match]:
        """Check text after offset-preserving PII masking.

        E-mail addresses, telephone numbers, and URLs never reach morphology,
        syntax, neural, style, dialect, or semantic analyzers. The mask keeps
        source length stable, so returned offsets still index ``text``.
        """

        private = self._mask(text)
        working_text = private.masked_text
        parse_engine = self.syntax or (self.neural.syntax if self.neural is not None else None)
        parsed = parse_engine.parse(working_text) if parse_engine is not None else None
        context = AnalysisContext.build(working_text, parsed=parsed)
        return self._check_private(
            text,
            private,
            parsed=parsed,
            context=context,
            suppression=suppression,
            profiles=profiles,
            diacritics_mode=diacritics_mode,
        )

    def correct(
        self,
        text: str,
        *,
        mode: Literal["safe", "all", "dialects"] = "safe",
        suppression: Suppression | None = None,
        profiles: Iterable[str] | None = None,
    ) -> str:
        """Apply safe replacements, or all suggestions when explicitly requested."""

        if mode not in {"safe", "all", "dialects"}:
            raise ValueError("mode must be 'safe', 'all', or 'dialects'")
        out = text
        for match in reversed(self.check(text, suppression=suppression, profiles=profiles)):
            should_apply = (
                mode == "all"
                or (mode == "dialects" and match.category == "dialect")
                or (mode == "safe" and match.autofix)
            )
            if match.replacements and should_apply:
                out = out[: match.offset] + match.replacements[0] + out[match.end :]
        return out

    def analyze_word(
        self, token: str, *, min_confidence: float = 0.0
    ) -> tuple[MorphologicalAnalysis, ...]:
        """Return ranked morphological readings for one Arabic token."""

        return self.morphology.analyze(token, min_confidence=min_confidence)

    def parse(
        self,
        text: str,
        *,
        dialect_to_msa: bool = False,
        neural_refine: bool = True,
    ) -> DocumentParse:
        """Return candidate syntax while excluding PII from linguistic analysis."""

        source = self.convert_to_msa(text).converted_text if dialect_to_msa else text
        private = self._mask(source)
        engine = self.syntax or SyntaxEngine(self.morphology)
        parsed = engine.parse(private.masked_text)
        if neural_refine and self.neural is not None:
            parsed = self.neural.report(private.masked_text, parsed=parsed).refined_parse
        return private.restore_parse(parsed)

    def neural_report(self, text: str) -> NeuralReport:
        """Return auditable neural decisions without exposing PII to the backend."""

        private = self._mask(text)
        engine = self.neural or HybridNeuralEngine(
            self.morphology, self.syntax or SyntaxEngine(self.morphology)
        )
        parsed = (self.syntax or engine.syntax).parse(private.masked_text)
        report = engine.report(private.masked_text, parsed=parsed)
        return private.restore_neural_report(report)

    def _dialect_report_private(self, private: MaskedText) -> DialectReport:
        engine = self.dialects or DialectEngine(
            self.morphology,
            self.syntax or SyntaxEngine(self.morphology),
        )
        parsed = (self.syntax or SyntaxEngine(self.morphology)).parse(private.masked_text)
        report = engine.report(private.masked_text, parsed=parsed)
        return private.restore_dialect_report(report)

    def dialect_report(self, text: str) -> DialectReport:
        """Return explainable dialect identification without exposing PII."""

        return self._dialect_report_private(self._mask(text))

    def detect_dialect(self, text: str) -> DialectIdentification:
        """Identify the dominant Arabic dialect without rewriting the text."""

        return self.dialect_report(text).identification

    def convert_to_msa(self, text: str) -> DialectReport:
        """Return an explicit Modern Standard Arabic conversion preview."""

        return self.dialect_report(text)

    def style_report(self, text: str) -> StyleReport:
        """Return non-mutating style analysis with PII excluded."""

        private = self._mask(text)
        engine = self.style or StyleEngine(
            self.morphology,
            self.syntax or SyntaxEngine(self.morphology),
        )
        return private.restore_style_report(engine.analyze(private.masked_text))

    def analyze_tone(self, text: str) -> ToneAnalysis:
        """Return explainable document tone scores without rewriting text."""

        return self.style_report(text).tone

    def intelligence_report(
        self,
        text: str,
        *,
        style_profile: StyleProfile | str | None = None,
        suppression: Suppression | None = None,
    ) -> WritingIntelligenceReport:
        """Return one explainable writing-intelligence snapshot.

        Style and dialect analyses share one deterministic syntax parse.  The
        complete diagnostic list still passes through the standard privacy and
        suppression pipeline, so custom lexicons and rule overrides behave the
        same in the report as they do in :meth:`check`.
        """

        private = self._mask(text)
        working_text = private.masked_text
        syntax_engine = self.syntax or SyntaxEngine(self.morphology)
        parsed = syntax_engine.parse(working_text)
        profile = StyleProfile(style_profile) if style_profile is not None else None
        if profile is None and self.style is not None:
            style_engine = self.style
        else:
            style_engine = StyleEngine(
                self.morphology,
                syntax_engine,
                profile=profile or StyleProfile.GENERAL,
            )
        dialect_engine = self.dialects or DialectEngine(self.morphology, syntax_engine)
        style_report = private.restore_style_report(style_engine.analyze(working_text, parsed))
        dialect_report = private.restore_dialect_report(
            dialect_engine.report(working_text, parsed=parsed)
        )
        public_parse = private.restore_parse(parsed)
        context = AnalysisContext.build(working_text, parsed=parsed)
        matches = self._check_private(
            text,
            private,
            parsed=parsed,
            context=context,
            suppression=suppression,
            profiles=None,
            diacritics_mode=None,
        )
        return build_writing_intelligence_report(
            text=text,
            parsed=public_parse,
            style=style_report,
            dialect=dialect_report,
            matches=matches,
        )


    def rewrite(
        self,
        text: str,
        *,
        mode: RewriteMode | str = RewriteMode.FORMAL,
        alternatives: int = 3,
    ) -> RewriteReport:
        """Return conservative offline rewrite alternatives.

        Dialect replacements are sourced from the same validated dialect engine
        used by :meth:`convert_to_msa`; no facts, citations, names, or numbers
        are generated by this deterministic baseline.
        """

        dialect_report = self.dialect_report(text)
        return rewrite_text(
            text,
            mode,
            dialect_conversions=dialect_report.conversions,
            alternatives=alternatives,
        )

    def analytics_report(
        self,
        text: str,
        *,
        style_profile: StyleProfile | str | None = None,
    ) -> WritingAnalytics:
        """Return sentence heatmaps and deep document metrics in one parse."""

        private = self._mask(text)
        working_text = private.masked_text
        syntax_engine = self.syntax or SyntaxEngine(self.morphology)
        parsed = syntax_engine.parse(working_text)
        profile = StyleProfile(style_profile) if style_profile is not None else None
        style_engine = (
            self.style
            if profile is None and self.style is not None
            else StyleEngine(
                self.morphology,
                syntax_engine,
                profile=profile or StyleProfile.GENERAL,
            )
        )
        public_parse = private.restore_parse(parsed)
        public_style = private.restore_style_report(style_engine.analyze(working_text, parsed))
        vocabulary = vocabulary_metrics(text, public_parse, public_style)
        return build_analytics(
            text=text,
            parsed=public_parse,
            style=public_style,
            vocabulary=vocabulary,
        )

    def diacritize(
        self,
        text: str,
        *,
        mode: DiacritizationMode | str = DiacritizationMode.FULL,
        neural_refine: bool = True,
    ) -> DiacritizationResult:
        """Return a preview while restoring protected PII verbatim."""

        private = self._mask(text)
        syntax_engine = self.syntax or SyntaxEngine(self.morphology)
        parsed = syntax_engine.parse(private.masked_text)
        if neural_refine and self.neural is not None:
            parsed = self.neural.report(private.masked_text, parsed=parsed).refined_parse
        result = self.diacritics.diacritize(private.masked_text, mode=mode, parsed=parsed)
        return private.restore_diacritization(result)

    def semantic_report(self, text: str) -> SemanticReport:
        """Return consistency and semantics with PII excluded from analysis."""

        private = self._mask(text)
        syntax_engine = self.syntax or SyntaxEngine(self.morphology)
        parsed = syntax_engine.parse(private.masked_text)
        if self.neural is not None:
            parsed = self.neural.report(private.masked_text, parsed=parsed).refined_parse
        engine = self.semantics or SemanticEngine(syntax_engine)
        report = engine.analyze(private.masked_text, parsed=parsed)
        return private.restore_semantic_report(report)

    def session(self, text: str = "", *, context_sentences: int = 1) -> IncrementalSession:
        """Open an incremental editing session backed by this engine."""

        live = IncrementalSession(self, context_sentences=context_sentences)
        if text:
            live.load(text)
        return live

    def learn_voice(
        self,
        texts: Iterable[str],
        *,
        profile: VoiceProfile | None = None,
    ) -> VoiceProfile:
        """Fold writing samples into an authorial voice profile.

        Every sample passes through the same offset-preserving PII mask as
        ``check()`` before feature extraction, so e-mail addresses, phone
        numbers, and URLs never influence — or leak into — the profile.
        """

        current = profile or VoiceProfile()
        for text in texts:
            current = current.update(self._mask(text).masked_text)
        return current

    def voice_report(self, text: str, profile: VoiceProfile) -> VoiceDeviationReport:
        """Compare ``text`` against a learned voice, with PII excluded."""

        return profile.compare(self._mask(text).masked_text)

    @property
    def rule_count(self) -> int:
        return len(self.engine.rules)
