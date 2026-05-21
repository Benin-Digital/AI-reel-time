from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


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
    filename: str
    content: str = "sample content"


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
    created_at: datetime
    updated_at: datetime


class JobDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    path: str
    content_hash: str | None
    status: str
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class MatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cv_id: int
    job_id: int
    score: float
    common_keywords: list[str]
    created_at: datetime
    updated_at: datetime


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


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: str
    password: str
    role: Literal["admin", "member"] = "member"


class UserUpdate(BaseModel):
    role: Literal["admin", "member"] | None = None
    is_active: bool | None = None


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
