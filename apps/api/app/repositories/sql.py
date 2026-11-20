"""Named, parameterised SQL from ``database/queries``."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import TextClause, text
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT

QUERY_DIR = REPO_ROOT / "database" / "queries"


@lru_cache
def query(name: str) -> TextClause:
    path = (QUERY_DIR / f"{name}.sql").resolve()
    if not path.is_relative_to(QUERY_DIR.resolve()):
        raise ValueError("invalid query name")
    return text(path.read_text())


def rows(db: Session, name: str, **params) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(query(name), params)]
