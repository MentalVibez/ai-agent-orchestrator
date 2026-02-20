"""Database connection and session management."""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import settings

# Database URL — defaults to /app/data/orchestrator.db so it lands on the
# Docker-managed named volume and survives container restarts.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////app/data/orchestrator.db")

# Create engine — configure connection pool for PostgreSQL, keep SQLite defaults otherwise
if "postgresql" in DATABASE_URL or "postgres" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        echo=settings.debug,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=settings.debug,
    )

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Get database session.

    Yields:
        Database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database (create tables)."""
    Base.metadata.create_all(bind=engine)
