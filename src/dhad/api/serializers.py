"""Lossless conversion from Dhad domain objects to versioned API contracts."""

from __future__ import annotations

from dhad.diacritics import DiacritizationResult
from dhad.dialects import DialectReport
from dhad.analytics import WritingAnalytics
from dhad.intelligence import WritingIntelligenceReport
from dhad.rewriting import RewriteReport
from dhad.templates import GeneratedDocument, WritingTemplate
from dhad.match import Match
from dhad.morphology import AffixSegment, MorphologicalAnalysis
from dhad.style import StyleReport, ToneAnalysis
from dhad.syntax import DocumentParse

from .models import (
    AffixModel,
    CheckResponse,
    DiacritizeResponse,
    DiacritizedTokenModel,
    DialectConversionModel,
    DialectEvidenceModel,
    DialectResponse,
    IntelligenceResponse,
    LinguisticExplanationModel,
    IrabModel,
    MatchModel,
    MorphologyModel,
    ParseResponse,
    ReadabilityModel,
    RelationModel,
    SentenceParseModel,
    StyleResponse,
    SyntaxTokenModel,
    SuggestionChipModel,
    ToneEvidenceModel,
    ToneModel,
    VocabularyMetricsModel,
    AnalyticsResponse,
    RewriteCandidateModel,
    RewriteChangeModel,
    RewriteResponse,
    SentenceInsightModel,
    TemplateFieldModel,
    TemplateGenerateResponse,
    TemplateListResponse,
    TemplateModel,
    ToneBalanceModel,
)


def match_model(item: Match) -> MatchModel:
    return MatchModel(
        rule_id=item.rule_id,
        category=item.category,
        message=item.message,
        offset=item.offset,
        length=item.length,
        replacements=list(item.replacements),
        severity=item.severity,
        explanation=item.explanation,
        autofix=item.autofix,
        confidence=item.confidence,
        priority=item.priority,
        tags=list(item.tags),
        references=list(item.references),
        profiles=list(item.profiles),
    )


def affix_model(item: AffixSegment) -> AffixModel:
    return AffixModel(
        kind=item.kind,
        surface=item.surface,
        start=item.start,
        end=item.end,
        feature=item.feature,
    )


def morphology_model(item: MorphologicalAnalysis) -> MorphologyModel:
    return MorphologyModel(
        token=item.token,
        normalized=item.normalized,
        stem=item.stem,
        lemma=item.lemma,
        root=item.root,
        pattern=item.pattern,
        pos=item.pos,
        prefixes=[affix_model(part) for part in item.prefixes],
        suffixes=[affix_model(part) for part in item.suffixes],
        infixes=[affix_model(part) for part in item.infixes],
        features=dict(item.features),
        confidence=item.confidence,
        source=item.source,
        frequency=item.frequency,
    )


def check_response(version: str, matches: list[Match]) -> CheckResponse:
    return CheckResponse(version=version, matches=[match_model(item) for item in matches])


def parse_response(version: str, parsed: DocumentParse) -> ParseResponse:
    sentences: list[SentenceParseModel] = []
    for sentence in parsed.sentences:
        sentences.append(
            SentenceParseModel(
                text=sentence.text,
                start=sentence.start,
                end=sentence.end,
                tokens=[
                    SyntaxTokenModel(
                        text=token.text,
                        start=token.start,
                        end=token.end,
                        analysis=(morphology_model(token.analysis) if token.analysis else None),
                        alternatives=[morphology_model(item) for item in token.alternatives],
                        confidence=token.confidence,
                        break_before=token.break_before,
                    )
                    for token in sentence.tokens
                ],
                relations=[
                    RelationModel(
                        relation=relation.relation.value,
                        head_index=relation.head_index,
                        dependent_index=relation.dependent_index,
                        confidence=relation.confidence,
                        governor=relation.governor,
                        explanation=relation.explanation,
                    )
                    for relation in sentence.relations
                ],
                irab=[
                    IrabModel(
                        token_index=item.token_index,
                        role=item.role,
                        case_or_mood=item.case_or_mood,
                        marker=item.marker,
                        governor_index=item.governor_index,
                        governor=item.governor,
                        confidence=item.confidence,
                        explanation=item.explanation,
                    )
                    for item in sentence.irab
                ],
                confidence=sentence.confidence,
            )
        )
    return ParseResponse(version=version, text=parsed.text, sentences=sentences)


def diacritize_response(version: str, result: DiacritizationResult) -> DiacritizeResponse:
    return DiacritizeResponse(
        version=version,
        source_text=result.source_text,
        text=result.text,
        mode=result.mode.value,
        tokens=[
            DiacritizedTokenModel(
                source=item.source,
                output=item.output,
                start=item.start,
                end=item.end,
                mode=item.mode.value,
                confidence=item.confidence,
                core_confidence=item.core_confidence,
                ending_confidence=item.ending_confidence,
                lemma=item.lemma,
                role=item.role,
                case_or_mood=item.case_or_mood,
                provenance=list(item.provenance),
            )
            for item in result.tokens
        ],
        confidence=result.confidence,
    )


def tone_model(tone: ToneAnalysis) -> ToneModel:
    return ToneModel(
        primary=tone.primary.value,
        confidence=tone.confidence,
        scores={label.value: score for label, score in tone.scores},
        evidence=[
            ToneEvidenceModel(
                tone=item.tone.value,
                text=item.text,
                offset=item.offset,
                length=item.length,
                weight=item.weight,
                reason=item.reason,
            )
            for item in tone.evidence
        ],
    )


def style_response(version: str, report: StyleReport) -> StyleResponse:
    metrics = report.readability
    return StyleResponse(
        version=version,
        profile=report.profile.value,
        matches=[match_model(item) for item in report.matches],
        tone=tone_model(report.tone),
        sentence_tones=[tone_model(item) for item in report.sentence_tones],
        readability=ReadabilityModel(
            words=metrics.words,
            sentences=metrics.sentences,
            average_words_per_sentence=metrics.average_words_per_sentence,
            average_characters_per_word=metrics.average_characters_per_word,
            long_word_ratio=metrics.long_word_ratio,
            lexical_density=metrics.lexical_density,
            nominalization_ratio=metrics.nominalization_ratio,
            repeated_word_ratio=metrics.repeated_word_ratio,
            clarity_score=metrics.clarity_score,
            band=metrics.band,
        ),
    )


def dialect_response(version: str, report: DialectReport) -> DialectResponse:
    identification = report.identification
    return DialectResponse(
        version=version,
        text=report.text,
        primary=identification.primary.value,
        confidence=identification.confidence,
        scores={label.value: score for label, score in identification.scores},
        evidence=[
            DialectEvidenceModel(
                dialects=[label.value for label in item.dialects],
                text=item.text,
                offset=item.offset,
                length=item.length,
                weight=item.weight,
                rule_id=item.rule_id,
            )
            for item in identification.evidence
        ],
        conversions=[
            DialectConversionModel(
                rule_id=item.rule_id,
                dialects=[label.value for label in item.dialects],
                source=item.source,
                replacement=item.replacement,
                offset=item.offset,
                length=item.length,
                confidence=item.confidence,
                explanation=item.explanation,
                contextual=item.contextual,
                morphology_validated=item.morphology_validated,
                syntax_validated=item.syntax_validated,
            )
            for item in report.conversions
        ],
        converted_text=report.converted_text,
    )

def intelligence_response(
    version: str, report: WritingIntelligenceReport
) -> IntelligenceResponse:
    """Serialize the unified Apex writing-intelligence report."""

    metrics = report.vocabulary
    return IntelligenceResponse(
        version=version,
        text=report.text,
        matches=[match_model(item) for item in report.matches],
        style=style_response(version, report.style),
        dialect=dialect_response(version, report.dialect),
        vocabulary=VocabularyMetricsModel(
            words=metrics.words,
            unique_words=metrics.unique_words,
            unique_lemmas=metrics.unique_lemmas,
            unique_roots=metrics.unique_roots,
            type_token_ratio=metrics.type_token_ratio,
            lemma_diversity=metrics.lemma_diversity,
            root_diversity=metrics.root_diversity,
            hapax_ratio=metrics.hapax_ratio,
            average_word_length=metrics.average_word_length,
            longest_sentence_words=metrics.longest_sentence_words,
            average_clauses_per_sentence=metrics.average_clauses_per_sentence,
            complexity_score=metrics.complexity_score,
            band=metrics.band,
        ),
        suggestion_chips=[
            SuggestionChipModel(
                id=item.id,
                target=item.target.value,
                label=item.label,
                rationale=item.rationale,
                actions=list(item.actions),
                relevance=item.relevance,
            )
            for item in report.suggestion_chips
        ],
        explanations=[
            LinguisticExplanationModel(
                rule_id=item.rule_id,
                category=item.category,
                title=item.title,
                reasoning=item.reasoning,
                why_it_matters=item.why_it_matters,
                source_text=item.source_text,
                offset=item.offset,
                length=item.length,
                replacements=list(item.replacements),
                severity=item.severity,
                confidence=item.confidence,
                decision=item.decision,
                references=list(item.references),
            )
            for item in report.explanations
        ],
    )



def rewrite_response(version: str, report: RewriteReport) -> RewriteResponse:
    return RewriteResponse(
        version=version,
        source_text=report.source_text,
        mode=report.mode.value,
        candidates=[
            RewriteCandidateModel(
                id=item.id,
                mode=item.mode.value,
                text=item.text,
                label=item.label,
                explanation=item.explanation,
                changes=[
                    RewriteChangeModel(
                        kind=change.kind,
                        source=change.source,
                        replacement=change.replacement,
                        offset=change.offset,
                        length=change.length,
                        explanation=change.explanation,
                    )
                    for change in item.changes
                ],
                confidence=item.confidence,
                meaning_preservation=item.meaning_preservation,
                brevity_delta=item.brevity_delta,
            )
            for item in report.candidates
        ],
        offline=report.offline,
        safety_notice=report.safety_notice,
    )


def analytics_response(version: str, report: WritingAnalytics) -> AnalyticsResponse:
    return AnalyticsResponse(
        version=version,
        words=report.words,
        characters=report.characters,
        sentences=report.sentences,
        paragraphs=report.paragraphs,
        estimated_reading_seconds=report.estimated_reading_seconds,
        estimated_speaking_seconds=report.estimated_speaking_seconds,
        engagement_score=report.engagement_score,
        clarity_score=report.clarity_score,
        complexity_score=report.complexity_score,
        vocabulary_richness=report.vocabulary_richness,
        tone_balance=ToneBalanceModel(
            scores=dict(report.tone_balance.scores),
            dominant=report.tone_balance.dominant,
            balance_score=report.tone_balance.balance_score,
        ),
        sentence_heatmap=[
            SentenceInsightModel(
                index=item.index,
                text=item.text,
                start=item.start,
                end=item.end,
                words=item.words,
                clarity_score=item.clarity_score,
                complexity_score=item.complexity_score,
                tone=item.tone,
                tone_confidence=item.tone_confidence,
                heat=item.heat,
            )
            for item in report.sentence_heatmap
        ],
    )


def template_model(template: WritingTemplate) -> TemplateModel:
    return TemplateModel(
        id=template.id.value,
        title=template.title,
        description=template.description,
        fields=[
            TemplateFieldModel(
                id=field.id,
                label=field.label,
                placeholder=field.placeholder,
                required=field.required,
                multiline=field.multiline,
                max_length=field.max_length,
            )
            for field in template.fields
        ],
        supported_tones=list(template.supported_tones),
    )


def template_list_response(version: str, templates: tuple[WritingTemplate, ...]) -> TemplateListResponse:
    return TemplateListResponse(version=version, templates=[template_model(item) for item in templates])


def template_generate_response(version: str, document: GeneratedDocument) -> TemplateGenerateResponse:
    return TemplateGenerateResponse(
        version=version,
        template_id=document.template_id.value,
        title=document.title,
        text=document.text,
        missing_fields=list(document.missing_fields),
        tone=document.tone,
        offline=document.offline,
    )
