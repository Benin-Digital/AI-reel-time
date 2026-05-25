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

    model_config = SettingsConfigDict(env_prefix="AI_REALTIME_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
