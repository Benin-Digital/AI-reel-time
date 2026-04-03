from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Real-Time API"
    environment: str = "local"
    watch_cv_dir: str = "/srv/ai-realtime/storage/cv"
    watch_job_dir: str = "/srv/ai-realtime/storage/job"

    model_config = SettingsConfigDict(env_prefix="AI_REALTIME_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
