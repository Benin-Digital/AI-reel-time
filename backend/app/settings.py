from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Real-Time API"
    app_version: str = "0.1.0"
    environment: str = "local"
    database_url: str = "postgresql+psycopg://airealtime:airealtime@localhost:5432/airealtime"
    database_auto_create: bool = True
    redis_url: str = "redis://localhost:6379/0"
    watch_cv_dir: str = "/srv/ai-realtime/storage/cv"
    watch_job_dir: str = "/srv/ai-realtime/storage/job"
    api_keys: str = ""
    require_api_key: bool = False
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
    scoring_skill_keywords: str = "python,sql,postgresql,fastapi,docker,kubernetes,aws,azure,linux,git"
    scoring_skill_weight: float = 1.5
    scoring_synonyms: str = "js=javascript,ts=typescript,nodejs=node,postgres=postgresql,py=python"
    scoring_stopwords_languages: str = "fr,en"
    scoring_stopwords: str = ""
    scoring_phrase_bonus: float = 0.05
    scoring_max_bonus: float = 0.25
    scoring_experience_bonus: float = 0.1
    scoring_experience_penalty: float = 0.05
    ocr_languages: str = "eng+fra"
    ocr_dpi: int = 300
    ocr_psm: int = 6
    ocr_oem: int = 3
    hybrid_scoring_enabled: bool = True
    hybrid_vector_weight: float = 0.7
    hybrid_lexical_weight: float = 0.3
    embedding_enabled: bool = True
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 16
    embedding_dim: int = 384
    embedding_top_k: int = 25
    queue_memory_max_size: int = 1000
    queue_memory_warn_threshold: int = 250
    queue_backend: str = "stream"
    queue_stream_name: str = "airealtime:watch_events"
    queue_consumer_group: str = "airealtime-workers"
    queue_consumer_name: str = ""
    queue_ack_on_failure: bool = True
    worker_retry_base_delay: float = 0.5
    worker_retry_max_delay: float = 10.0
    worker_max_retries: int = 3

    model_config = SettingsConfigDict(env_prefix="AI_REALTIME_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
