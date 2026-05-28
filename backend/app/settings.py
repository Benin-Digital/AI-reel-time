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
    rate_limit_max_requests: int = 120
    rate_limit_window_seconds: int = 60
    cors_allow_origins: str = ""
    cors_allow_methods: str = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    cors_allow_headers: str = "Authorization,Content-Type,X-API-Key"
    log_level: str = "INFO"
    log_json: bool = False
    retention_event_days: int = 30
    retention_extraction_days: int = 30
    retention_score_days: int = 60
    scoring_skill_keywords: str = (
        "python,sql,postgresql,fastapi,docker,kubernetes,aws,azure,linux,git," \
        "communication,management,project management,analysis,teamwork,leadership," \
        "customer service,sales,negotiation,reporting,training,logistics,operations," \
        "marketing,accounting,finance,quality,procurement,support,administration,hr,recruitment,education"
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
    ner_enabled: bool = True
    ner_model_name: str = "fr_core_news_sm"
    ner_max_chars: int = 20000
    ner_max_entities: int = 12
    ocr_min_text_length: int = 20
    ocr_dpi: int = 200
    ocr_languages: str = "fra+eng"
    ocr_psm: int = 6
    ocr_oem: int = 3

    model_config = SettingsConfigDict(env_prefix="AI_REALTIME_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
