from collections.abc import Iterator
from typing import Annotated
from pathlib import Path

from fastapi import Depends
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATABASE_URL

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


# pool_pre_ping drops dead connections instead of failing a request.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def apply_migrations() -> None:
    """Run every .sql file in migrations/ in name order. The SQL is idempotent."""
    with engine.begin() as conn:
        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            conn.execute(text(sql_file.read_text()))


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


DB = Annotated[Session, Depends(get_session)]
