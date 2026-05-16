from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base
from .settings import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    if settings.database_auto_create:
        Base.metadata.create_all(bind=engine)
