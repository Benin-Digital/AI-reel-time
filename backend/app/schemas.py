from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EventCreate(BaseModel):
    source: str = "manual"
    event_type: str
    path: str
    fingerprint: str | None = None
    observed_at: float


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    event_type: str
    path: str
    fingerprint: str | None
    observed_at: float
    created_at: datetime


class WatcherSimulateRequest(BaseModel):
    folder: Literal["cv", "job"] = "cv"
    filename: str | None = None
    content: str = "sample content"
    path: str | None = None
    event_type: str = "created"


class IngestDeleteRequest(BaseModel):
    folder: Literal["cv", "job"] = "cv"
    filename: str


class IngestDeleteBatchRequest(BaseModel):
    folder: Literal["cv", "job"] = "cv"
    filenames: list[str]


class ExtractedTextCreate(BaseModel):
    file_path: str
    content_hash: str | None = None
    extracted_text: str | None = None
    extraction_method: str = "unknown"
    extraction_success: bool = False
    error_message: str | None = None


class ExtractedTextRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_path: str
    content_hash: str | None
    extracted_text: str | None
    extraction_method: str
    extraction_success: bool
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ScoreRequest(BaseModel):
    cv_path: str
    job_path: str


class ScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cv_path: str
    job_path: str
    score: float
    common_keywords: list[str]
    created_at: datetime


class CvDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    path: str
    content_hash: str | None
    status: str
    last_error: str | None
    session_id: int | None = None
    structuring_status: str | None = None
    structuring_error: str | None = None
    created_at: datetime
    updated_at: datetime


class JobDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    path: str
    content_hash: str | None
    status: str
    last_error: str | None
    session_id: int | None = None
    structuring_status: str | None = None
    structuring_error: str | None = None
    created_at: datetime
    updated_at: datetime


class AnalysisSessionCreate(BaseModel):
    name: str
    description: str | None = None
    status: Literal["open", "closed"] = "open"


class AnalysisSessionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: Literal["open", "closed"] | None = None


class SessionAssignRequest(BaseModel):
    cv_ids: list[int] = Field(default_factory=list)
    job_ids: list[int] = Field(default_factory=list)


class AnalysisSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    status: str
    closed_at: datetime | None
    cv_count: int | None = None
    job_count: int | None = None
    match_count: int | None = None
    created_at: datetime
    updated_at: datetime


class AnalysisSessionDetailRead(AnalysisSessionRead):
    cv_documents: list[CvDocumentRead] = Field(default_factory=list)
    job_documents: list[JobDocumentRead] = Field(default_factory=list)


class JobOfferCreate(BaseModel):
    title: str
    meta_keywords: list[str] = Field(default_factory=list)
    contract_type: str
    company: str | None = None
    category: str
    job_type: str | None = None
    salary_max: int | None = None
    languages: list[str] = Field(default_factory=list)
    description: str
    visual_code: str | None = None
    paragraph: str | None = None
    skills: list[str] = Field(default_factory=list)
    strong_constraints: list[str] = Field(default_factory=list)
    status: Literal["draft", "published"] = "published"


class JobOfferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    meta_keywords: list[str]
    contract_type: str
    company: str
    category: str
    job_type: str | None
    salary_max: int | None
    languages: list[str]
    description: str
    visual_code: str | None
    paragraph: str | None
    skills: list[str]
    strong_constraints: list[str]
    status: str
    rendered_text: str
    rendered_html: str | None
    published_document_path: str | None
    created_at: datetime
    updated_at: datetime


class CvProfileCreate(BaseModel):
    full_name: str
    headline: str
    summary: str
    experience: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    contract_type: str | None = None
    location: str | None = None
    status: Literal["draft", "published"] = "published"


class CvProfileRead(BaseModel):
    full_name: str
    headline: str
    summary: str
    experience: list[str]
    education: list[str]
    certifications: list[str]
    skills: list[str]
    languages: list[str]
    contract_type: str | None
    location: str | None
    status: str
    rendered_text: str
    rendered_html: str | None
    published_document_path: str | None


class MatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cv_id: int
    job_id: int
    cv_label: str | None = None
    job_label: str | None = None
    score: float
    common_keywords: list[str]
    score_semantic: float | None = None
    score_skills: float | None = None
    score_experience: float | None = None
    score_education: float | None = None
    score_languages: float | None = None
    score_contract: float | None = None
    match_domain: str | None = None
    created_at: datetime
    updated_at: datetime


class MatchFeedbackCreate(BaseModel):
    decision: Literal["accept", "reject", "review"]
    rating: int | None = None
    comment: str | None = None


class MatchFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    match_id: int
    decision: Literal["accept", "reject", "review"]
    rating: int | None
    comment: str | None
    created_at: datetime
    updated_at: datetime


class MatchFeedbackExportRead(BaseModel):
    """Full feedback record for periodic manual review, including the
    CV/job text and score breakdown as they were at feedback time — see
    MatchFeedback.cv_text_snapshot/job_text_snapshot/scores_snapshot."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    match_id: int
    decision: Literal["accept", "reject", "review"]
    rating: int | None
    comment: str | None
    cv_text_snapshot: str | None
    job_text_snapshot: str | None
    scores_snapshot: dict | None
    created_at: datetime


class SearchRequest(BaseModel):
    kind: Literal["cv", "job"] = "cv"
    query: str
    top_k: int = 10
    min_score: float | None = None
    status: Literal["ready", "failed", "pending"] | None = None
    vector_weight: float | None = None
    lexical_weight: float | None = None


class SearchHit(BaseModel):
    id: int
    path: str
    status: str
    score: float
    updated_at: datetime


class DocumentDetailBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    path: str
    content_hash: str | None
    status: str
    last_error: str | None
    structuring_status: str | None = None
    structuring_error: str | None = None
    created_at: datetime
    updated_at: datetime
    match_count: int
    average_score: float | None
    top_keywords: list[str]
    extraction: ExtractedTextRead | None
    top_matches: list[MatchRead]
    


class CvDocumentDetailRead(DocumentDetailBase):
    pass


class JobDocumentDetailRead(DocumentDetailBase):
    pass


class ParserCorrection(BaseModel):
    original: str
    assigned_section: str
    comment: str | None = None


class ParserFeedbackCreate(BaseModel):
    corrections: list[ParserCorrection]


class ParserFeedbackRead(BaseModel):
    id: int
    kind: str
    doc_id: int
    corrections: list[ParserCorrection]
    user_id: int | None = None
    created_at: datetime


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    first_name: str | None = None
    last_name: str | None = None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: str
    password: str
    first_name: str | None = None
    last_name: str | None = None
    role: Literal["admin", "member"] = "member"


class UserUpdate(BaseModel):
    role: Literal["admin", "member"] | None = None
    is_active: bool | None = None


class UserSelfUpdate(BaseModel):
    current_password: str
    new_email: str | None = None
    new_password: str | None = Field(default=None, min_length=8)


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class AuthRegisterRequest(BaseModel):
    email: str
    password: str


class AuthLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class MatchExplainRead(BaseModel):
    match_id: int
    score: float
    summary: str
    why_match: list[str]
    vigilance: list[str]
    evidence: list[str]
    keyword_hits: list[str]
    score_semantic: float | None = None
    score_skills: float | None = None
    score_experience: float | None = None
    score_education: float | None = None
    score_languages: float | None = None
    score_contract: float | None = None
    match_domain: str | None = None


class AnalyzeRequest(BaseModel):
    cv_text: str | None = ""
    job_text: str | None = ""


class ScoringWeightsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    structured_lexical_weight: float
    structured_skill_weight: float
    structured_must_have_weight: float
    structured_experience_weight: float
    structured_language_weight: float
    structured_contract_weight: float
    structured_summary_weight: float
    structured_education_weight: float
    structured_missing_required_penalty: float
    structured_missing_experience_penalty: float
    scoring_skill_weight: float
    scoring_phrase_bonus: float
    scoring_max_bonus: float


class FeedbackDecisionStats(BaseModel):
    count: int
    pct: float
    avg_rating: float | None = None


class FeedbackComponentScores(BaseModel):
    score_skills: float | None = None
    score_semantic: float | None = None
    score_experience: float | None = None
    score_education: float | None = None
    score_languages: float | None = None
    score_contract: float | None = None
    score_global: float | None = None


class FeedbackDomainRow(BaseModel):
    domain: str
    total: int
    accept: int = 0
    reject: int = 0
    review: int = 0
    avg_score: float | None = None


class FeedbackWeightHint(BaseModel):
    component: str
    label: str
    delta: float


class FeedbackStatsRead(BaseModel):
    total: int
    by_decision: dict[str, FeedbackDecisionStats]
    avg_scores_by_decision: dict[str, FeedbackComponentScores]
    by_domain: list[FeedbackDomainRow]
    weight_hints: list[FeedbackWeightHint]


class LearnedWeightsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    w_semantic: float
    w_skills: float
    w_experience: float
    w_education: float
    w_languages: float
    w_contract: float
    sample_count: int
    accuracy: float | None = None
    is_active: bool
    created_at: datetime


class WeightComputeResult(BaseModel):
    weights: dict[str, float]
    sample_count: int
    accuracy: float
    current_weights: dict[str, float]


class ScoringV2TrainResult(BaseModel):
    sample_count: int
    auc: float
    feature_importance: dict[str, float]
    saved_to: str | None = None


class ScoringV2ScoreRequest(BaseModel):
    cv_path: str
    job_path: str


class ScoringV2ScoreResult(BaseModel):
    probability: float | None = None
    signals: dict[str, float]
    model_available: bool


class ScoringV2Status(BaseModel):
    model_available: bool
    model_path: str | None = None
    sample_count: int | None = None
    auc: float | None = None
    feature_importance: dict[str, float] | None = None


class EscoLookupRequest(BaseModel):
    text: str
    top_k: int = 5


class EscoMatch(BaseModel):
    uri: str
    preferred_label: str
    score: float


class EscoLookupResult(BaseModel):
    matches: list[EscoMatch]
    available: bool
