"""
EVR Trading Bot — Veritabani Baglantisi
=========================================
SQLAlchemy engine ve session yonetimi.
SQLite ve PostgreSQL uyumlu.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from evr_bot.config import DATABASE_URL
from evr_bot.migrations import run_migrations
from evr_bot.models import Base

# SQLite icin ozel ayar
_connect_args = {}
_pool_kwargs = {}

if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
else:
    # PostgreSQL pool ayarlari — multi-worker ortamda connection tukenmesini onler
    _pool_kwargs = {
        "pool_size": 3,
        "max_overflow": 2,
    }

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args=_connect_args,
    pool_pre_ping=True,
    **_pool_kwargs,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    """Tablolari olustur ve bekleyen migration'lari uygula."""
    run_migrations(engine)


def get_db() -> Session:
    """FastAPI dependency olarak kullanilacak session olusturucu."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
