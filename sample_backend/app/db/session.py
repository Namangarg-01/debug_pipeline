"""
Database engine and session management for the sample backend.

This code is only indexed by the Debug Pipeline demo so the analyzer has real
source to reason about; it is never executed.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def init_db(base) -> None:
    """Create all tables for the given declarative base (used on first start-up)."""
    base.metadata.create_all(bind=engine)


def get_session():
    """Open a new database session from the connection pool for the current request."""
    # One session per call; callers use it for their queries.
    session = SessionLocal()
    return session
