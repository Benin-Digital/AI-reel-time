import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .models import Base
from .settings import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
logger = logging.getLogger(__name__)


def init_db() -> None:
    if settings.database_auto_create:
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as exc:
            logger.warning("pgvector extension setup failed: %s", exc)
        Base.metadata.create_all(bind=engine)
