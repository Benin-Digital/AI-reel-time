from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Real-Time API"
    app_version: str = "0.1.0"
    environment: str = "local"
    database_url: str = "postgresql+psycopg://airealtime:airealtime@localhost:5432/airealtime"
    database_auto_create: bool = True
    redis_url: str = "redis://localhost:6379/0"
    queue_backend: str = "stream"
    queue_stream_name: str = "airealtime:events"
    queue_consumer_group: str = "airealtime-workers"
    queue_consumer_name: str = ""
    queue_memory_max_size: int = 1000
    queue_memory_warn_threshold: int = 250
    queue_ack_on_failure: bool = True
    worker_max_retries: int = 3
    worker_retry_base_delay: float = 0.5
    worker_retry_max_delay: float = 10.0
    # Number of event-worker threads processing the ingestion queue
    # concurrently. 1 keeps the historical single-threaded behavior.
    worker_concurrency: int = 1
    watch_cv_dir: str = "/srv/ai-realtime/storage/cv"
    watch_job_dir: str = "/srv/ai-realtime/storage/job"
    api_keys: str = ""
    require_api_key: bool = False
    auth_enabled: bool = True
    bootstrap_superadmin_email: str = "admin@entreprise.com"
    bootstrap_superadmin_password: str = "admin1234"
    bootstrap_superadmin_role: str = "superadmin"
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_minutes: int = 720
    rate_limit_enabled: bool = True
    rate_limit_max_requests: int = 300
    rate_limit_window_seconds: int = 60
    cors_allow_origins: str = "*"
    cors_allow_methods: str = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    cors_allow_headers: str = "Authorization,Content-Type,X-API-Key"
    log_level: str = "INFO"
    log_json: bool = False
    retention_event_days: int = 30
    retention_extraction_days: int = 30
    retention_score_days: int = 60
    scoring_skill_keywords: str = (
        "python,sql,postgresql,fastapi,docker,kubernetes,aws,azure,linux,git,"
        "communication,project management,teamwork,leadership,"
        "customer service,sales,negotiation,reporting,"
        "marketing,accounting"
    )
    scoring_skill_weight: float = 1.5
    scoring_synonyms: str = "js=javascript,ts=typescript,nodejs=node,postgres=postgresql,py=python"
    scoring_stopwords_languages: str = "fr,en"
    scoring_stopwords: str = ""
    scoring_phrase_bonus: float = 0.05
    scoring_max_bonus: float = 0.25
    scoring_experience_bonus: float = 0.1
    scoring_experience_penalty: float = 0.05
    upload_max_mb: int = 20
    embedding_enabled: bool = True
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    embedding_dim: int = 384
    embedding_top_k: int = 10
    embedding_batch_size: int = 16
    # Hybrid skill scoring (F6): when a required skill isn't found literally in
    # the CV, award partial credit based on max embedding cosine similarity to
    # the CV's skills. Disabled -> pure lexical (previous behaviour).
    skill_embedding_enabled: bool = True
    skill_embedding_threshold: float = 0.6   # min cosine sim to grant any credit
    skill_embedding_max_credit: float = 0.8  # cap: a semantic match never beats exact (1.0)
    structured_lexical_weight: float = 0.18
    structured_skill_weight: float = 0.28
    structured_must_have_weight: float = 0.22
    structured_experience_weight: float = 0.12
    structured_language_weight: float = 0.06
    structured_contract_weight: float = 0.05
    structured_summary_weight: float = 0.04
    structured_education_weight: float = 0.05
    structured_missing_required_penalty: float = 0.20
    structured_missing_experience_penalty: float = 0.10
    # NER is optional: enable by default as requested
    ner_enabled: bool = True
    ner_model_name: str = "fr_core_news_sm"
    # Mapping from language code to spaCy model name, e.g. "fr:fr_core_news_sm,en:en_core_web_sm"
    ner_model_map: str = "fr:fr_core_news_sm,en:en_core_web_sm"
    ner_max_chars: int = 20000
    ner_max_entities: int = 12
    # Controls whether the system auto-creates a JobOffer from a parsed job document
    # Set to False in production to avoid unexpected side-effects during ingestion.
    auto_create_job_offer: bool = False
    ocr_min_text_length: int = 20
    ocr_dpi: int = 200
    ocr_languages: str = "fra+eng"
    ocr_psm: int = 6
    ocr_oem: int = 3
    # Safety net for scanned/misdetected PDFs: without these, a long or
    # pathological document can pin the CPU running OCR for several minutes,
    # starving the whole process (nginx 502s) since this runs synchronously
    # in the single event worker thread.
    ocr_max_pages: int = 20
    ocr_page_timeout_seconds: int = 25
    # Hybrid scoring: combine vector (bi-encoder) score with structured score
    hybrid_scoring_enabled: bool = True
    hybrid_vector_weight: float = 0.3
    hybrid_lexical_weight: float = 0.7
    # Cross-encoder model for semantic matching (matcher.py)
    crossencoder_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    crossencoder_enabled: bool = True
    # v2 architecture (non-LLM) — all layers ON by default. Each layer falls
    # back gracefully (Docling→PyMuPDF, CamemBERT→spaCy, ESCO→noop, GBM→null)
    # so the API stays up even if a model is missing.
    # Layer 1: Docling structured PDF conversion.
    conversion_use_docling: bool = True
    # Layer 2: CamemBERT NER (Transformers). Override path via CAMEMBERT_NER_MODEL
    # once the fine-tuned checkpoint is rsync'd into the models volume.
    ner_backend: str = "camembert"
    camembert_ner_model: str = "Jean-Baptiste/camembert-ner"
    # Layer 3: ESCO taxonomy. Default points to the Docker volume mount.
    esco_dir: str = "/srv/ai-realtime/esco"
    esco_model_name: str = "intfloat/multilingual-e5-base"
    # When true, build_document_profile populates StructuredDocument.esco_skill_uris
    # by mapping each extracted skill term to its ESCO concept (top-1, score >= 0.55).
    esco_enrich_skills: bool = True
    esco_enrich_max_uris: int = 30
    # Layer 4: scoring_v2 GBM aggregator. Path points at the models volume so the
    # trained pickle survives container rebuilds.
    scoring_v2_model_path: str = "/srv/ai-realtime/models/scoring_v2_gbm.pkl"

    model_config = SettingsConfigDict(env_prefix="AI_REALTIME_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
