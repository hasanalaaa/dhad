"""Strict Pydantic contracts for Dhad's public REST API and Python SDK."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    """Base contract: reject unknown fields and validate assignments strictly."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class MatchModel(APIModel):
    rule_id: str
    category: str
    message: str
    offset: int = Field(ge=0)
    length: int = Field(gt=0)
    replacements: list[str] = Field(default_factory=list)
    severity: Literal["error", "warning", "hint"]
    explanation: str = ""
    autofix: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    priority: int = 0
    tags: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    profiles: list[str] = Field(default_factory=list)


class CheckRequest(APIModel):
    text: str = Field(min_length=0, max_length=1_000_000)
    profiles: list[str] = Field(
        default_factory=lambda: ["default"], min_length=1, max_length=32
    )
    disabled_rules: list[str] = Field(default_factory=list, max_length=2_000)
    disabled_categories: list[str] = Field(default_factory=list, max_length=64)
    custom_words: list[str] = Field(default_factory=list, max_length=5_000)
    diacritics_mode: Literal["full", "endings", "core"] | None = None


class CheckResponse(APIModel):
    version: str
    matches: list[MatchModel]


class AffixModel(APIModel):
    kind: str
    surface: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    feature: str


class MorphologyModel(APIModel):
    token: str
    normalized: str
    stem: str
    lemma: str
    root: str | None
    pattern: str | None
    pos: str
    prefixes: list[AffixModel]
    suffixes: list[AffixModel]
    infixes: list[AffixModel]
    features: dict[str, str]
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    frequency: int = Field(ge=1)


class SyntaxTokenModel(APIModel):
    text: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    analysis: MorphologyModel | None
    alternatives: list[MorphologyModel]
    confidence: float = Field(ge=0.0, le=1.0)
    break_before: bool


class RelationModel(APIModel):
    relation: str
    head_index: int | None
    dependent_index: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    governor: str
    explanation: str


class IrabModel(APIModel):
    token_index: int = Field(ge=0)
    role: str
    case_or_mood: str
    marker: str
    governor_index: int | None
    governor: str
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str


class SentenceParseModel(APIModel):
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    tokens: list[SyntaxTokenModel]
    relations: list[RelationModel]
    irab: list[IrabModel]
    confidence: float = Field(ge=0.0, le=1.0)


class ParseRequest(APIModel):
    text: str = Field(min_length=0, max_length=1_000_000)
    dialect_to_msa: bool = False
    neural_refine: bool = True


class ParseResponse(APIModel):
    version: str
    text: str
    sentences: list[SentenceParseModel]


class DiacritizedTokenModel(APIModel):
    source: str
    output: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    mode: str
    confidence: float = Field(ge=0.0, le=1.0)
    core_confidence: float = Field(ge=0.0, le=1.0)
    ending_confidence: float = Field(ge=0.0, le=1.0)
    lemma: str | None
    role: str
    case_or_mood: str
    provenance: list[str]


class DiacritizeRequest(APIModel):
    text: str = Field(min_length=0, max_length=1_000_000)
    mode: Literal["full", "endings", "core"] = "full"
    neural_refine: bool = True


class DiacritizeResponse(APIModel):
    version: str
    source_text: str
    text: str
    mode: str
    tokens: list[DiacritizedTokenModel]
    confidence: float = Field(ge=0.0, le=1.0)


class ToneEvidenceModel(APIModel):
    tone: str
    text: str
    offset: int = Field(ge=0)
    length: int = Field(gt=0)
    weight: float = Field(gt=0)
    reason: str


class ToneModel(APIModel):
    primary: str
    confidence: float = Field(ge=0.0, le=1.0)
    scores: dict[str, float]
    evidence: list[ToneEvidenceModel]


class ReadabilityModel(APIModel):
    words: int = Field(ge=0)
    sentences: int = Field(ge=0)
    average_words_per_sentence: float = Field(ge=0.0)
    average_characters_per_word: float = Field(ge=0.0)
    long_word_ratio: float = Field(ge=0.0, le=1.0)
    lexical_density: float = Field(ge=0.0, le=1.0)
    nominalization_ratio: float = Field(ge=0.0, le=1.0)
    repeated_word_ratio: float = Field(ge=0.0, le=1.0)
    clarity_score: float = Field(ge=0.0, le=100.0)
    band: str


class StyleRequest(APIModel):
    text: str = Field(min_length=0, max_length=1_000_000)
    profile: Literal[
        "general",
        "academic",
        "administrative",
        "journalistic",
        "educational",
        "friendly",
        "literary",
    ] = "general"


class StyleResponse(APIModel):
    version: str
    profile: str
    matches: list[MatchModel]
    tone: ToneModel
    sentence_tones: list[ToneModel]
    readability: ReadabilityModel


class DialectEvidenceModel(APIModel):
    dialects: list[str]
    text: str
    offset: int = Field(ge=0)
    length: int = Field(gt=0)
    weight: float = Field(gt=0)
    rule_id: str


class DialectConversionModel(APIModel):
    rule_id: str
    dialects: list[str]
    source: str
    replacement: str
    offset: int = Field(ge=0)
    length: int = Field(gt=0)
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    contextual: bool
    morphology_validated: bool
    syntax_validated: bool


class DialectRequest(APIModel):
    text: str = Field(min_length=0, max_length=1_000_000)


class DialectResponse(APIModel):
    version: str
    text: str
    primary: str
    confidence: float = Field(ge=0.0, le=1.0)
    scores: dict[str, float]
    evidence: list[DialectEvidenceModel]
    conversions: list[DialectConversionModel]
    converted_text: str


class VocabularyMetricsModel(APIModel):
    words: int = Field(ge=0)
    unique_words: int = Field(ge=0)
    unique_lemmas: int = Field(ge=0)
    unique_roots: int = Field(ge=0)
    type_token_ratio: float = Field(ge=0.0, le=1.0)
    lemma_diversity: float = Field(ge=0.0, le=1.0)
    root_diversity: float = Field(ge=0.0, le=1.0)
    hapax_ratio: float = Field(ge=0.0, le=1.0)
    average_word_length: float = Field(ge=0.0)
    longest_sentence_words: int = Field(ge=0)
    average_clauses_per_sentence: float = Field(ge=0.0)
    complexity_score: float = Field(ge=0.0, le=100.0)
    band: str


class SuggestionChipModel(APIModel):
    id: str
    target: Literal["academic", "formal", "casual", "persuasive"]
    label: str
    rationale: str
    actions: list[str] = Field(min_length=1)
    relevance: float = Field(ge=0.0, le=1.0)


class LinguisticExplanationModel(APIModel):
    rule_id: str
    category: str
    title: str
    reasoning: str
    why_it_matters: str
    source_text: str
    offset: int = Field(ge=0)
    length: int = Field(gt=0)
    replacements: list[str]
    severity: Literal["error", "warning", "hint"]
    confidence: float = Field(ge=0.0, le=1.0)
    decision: Literal["safe_autofix", "review_required"]
    references: list[str]


class IntelligenceRequest(APIModel):
    text: str = Field(min_length=0, max_length=1_000_000)
    profile: Literal[
        "general",
        "academic",
        "administrative",
        "journalistic",
        "educational",
        "friendly",
        "literary",
    ] = "general"
    custom_words: list[str] = Field(default_factory=list, max_length=5_000)
    disabled_rules: list[str] = Field(default_factory=list, max_length=2_000)


class IntelligenceResponse(APIModel):
    version: str
    text: str
    matches: list[MatchModel]
    style: StyleResponse
    dialect: DialectResponse
    vocabulary: VocabularyMetricsModel
    suggestion_chips: list[SuggestionChipModel]
    explanations: list[LinguisticExplanationModel]


class HealthResponse(APIModel):
    status: Literal["ok"]
    version: str
    rules: int = Field(ge=0)
    lexicon_lemmas: int = Field(ge=0)
    lexicon_forms: int = Field(ge=0)
    syntax_engine: str
    candidate_irab: bool
    categories: dict[str, str]


class RewriteRequest(APIModel):
    text: str = Field(min_length=0, max_length=1_000_000)
    mode: Literal["formal", "concise", "expand", "creative", "academic"] = "formal"
    alternatives: int = Field(default=3, ge=1, le=3)


class RewriteChangeModel(APIModel):
    kind: str
    source: str
    replacement: str
    offset: int = Field(ge=0)
    length: int = Field(ge=0)
    explanation: str


class RewriteCandidateModel(APIModel):
    id: str
    mode: Literal["formal", "concise", "expand", "creative", "academic"]
    text: str
    label: str
    explanation: str
    changes: list[RewriteChangeModel]
    confidence: float = Field(ge=0.0, le=1.0)
    meaning_preservation: float = Field(ge=0.0, le=1.0)
    brevity_delta: float = Field(ge=-1.0, le=1.0)


class RewriteResponse(APIModel):
    version: str
    source_text: str
    mode: Literal["formal", "concise", "expand", "creative", "academic"]
    candidates: list[RewriteCandidateModel]
    offline: bool
    safety_notice: str


class AnalyticsRequest(APIModel):
    text: str = Field(min_length=0, max_length=1_000_000)
    profile: Literal[
        "general",
        "academic",
        "administrative",
        "journalistic",
        "educational",
        "friendly",
        "literary",
    ] = "general"


class SentenceInsightModel(APIModel):
    index: int = Field(ge=0)
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    words: int = Field(ge=0)
    clarity_score: float = Field(ge=0.0, le=100.0)
    complexity_score: float = Field(ge=0.0, le=100.0)
    tone: str
    tone_confidence: float = Field(ge=0.0, le=1.0)
    heat: Literal["cool", "balanced", "warm", "hot"]


class ToneBalanceModel(APIModel):
    scores: dict[str, float]
    dominant: str
    balance_score: float = Field(ge=0.0, le=100.0)


class AnalyticsResponse(APIModel):
    version: str
    words: int = Field(ge=0)
    characters: int = Field(ge=0)
    sentences: int = Field(ge=0)
    paragraphs: int = Field(ge=0)
    estimated_reading_seconds: int = Field(ge=0)
    estimated_speaking_seconds: int = Field(ge=0)
    engagement_score: float = Field(ge=0.0, le=100.0)
    clarity_score: float = Field(ge=0.0, le=100.0)
    complexity_score: float = Field(ge=0.0, le=100.0)
    vocabulary_richness: float = Field(ge=0.0, le=100.0)
    tone_balance: ToneBalanceModel
    sentence_heatmap: list[SentenceInsightModel]


class TemplateFieldModel(APIModel):
    id: str
    label: str
    placeholder: str
    required: bool
    multiline: bool
    max_length: int = Field(gt=0)


class TemplateModel(APIModel):
    id: Literal[
        "professional_email",
        "academic_abstract",
        "cover_letter",
        "social_post",
        "meeting_summary",
        "executive_brief",
    ]
    title: str
    description: str
    fields: list[TemplateFieldModel]
    supported_tones: list[str]


class TemplateListResponse(APIModel):
    version: str
    templates: list[TemplateModel]


class TemplateGenerateRequest(APIModel):
    template_id: Literal[
        "professional_email",
        "academic_abstract",
        "cover_letter",
        "social_post",
        "meeting_summary",
        "executive_brief",
    ]
    values: dict[str, str] = Field(default_factory=dict, max_length=32)
    tone: str = Field(default="formal", min_length=1, max_length=32)


class TemplateGenerateResponse(APIModel):
    version: str
    template_id: str
    title: str
    text: str
    missing_fields: list[str]
    tone: str
    offline: bool
