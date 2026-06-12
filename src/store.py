"""Job store — backend-agnostic via SQLAlchemy.

Uses Neon (Postgres) when DATABASE_URL is set in .env, otherwise a local SQLite
file (data/db/jobs.db). Same code, same schema, same API either way — so we can
develop locally and run in the cloud with no code change.

Neon connection string from the Neon console looks like:
    postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require
Put it in .env as DATABASE_URL=...  (we auto-route it through the psycopg driver).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Column, DateTime, Integer, MetaData, String, Table, Text,
    case, create_engine, func, insert, select, update,
)
from sqlalchemy.exc import IntegrityError

from . import config
from .models import Job

_SQLITE_URL = f"sqlite:///{config.DB_DIR / 'jobs.db'}"


def _resolve_url() -> str:
    url = config.get("DATABASE_URL")
    if not url:
        config.DB_DIR.mkdir(parents=True, exist_ok=True)
        return _SQLITE_URL
    # SQLAlchemy needs the psycopg (v3) driver prefix for Postgres URLs
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


_engine = None
_metadata = MetaData()

jobs_table = Table(
    "jobs", _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dedup_key", String(512), unique=True, nullable=False),
    Column("source", String(64)),
    Column("title", String(512)),
    Column("company", String(512)),
    Column("location", String(512)),
    Column("description", Text),
    Column("apply_link", Text),
    Column("email", String(256)),
    Column("posted", String(128)),
    Column("hiring_contact", String(256)),
    Column("hiring_contact_url", Text),
    Column("external_id", String(256)),
    Column("raw", Text),
    Column("status", String(32), default="pending"),
    Column("match_score", Integer),
    Column("comment", Text),
    Column("created_at", DateTime, server_default=func.now()),
)


def engine():
    global _engine
    if _engine is None:
        url = _resolve_url()
        kwargs: dict[str, Any] = {"future": True}
        if url.startswith("postgresql"):
            # Neon's pooled endpoint is PgBouncer (transaction mode) — disable
            # psycopg server-side prepared statements, and recycle stale conns.
            kwargs["connect_args"] = {"prepare_threshold": None}
            kwargs["pool_pre_ping"] = True
            kwargs["pool_recycle"] = 300
        _engine = create_engine(url, **kwargs)
    return _engine


def backend() -> str:
    return engine().dialect.name  # "postgresql" or "sqlite"


def init_db() -> None:
    _metadata.create_all(engine())


def upsert_jobs(jobs: list[Job], raws: list[dict] | None = None) -> tuple[int, int]:
    """Insert new jobs, skipping any whose dedup_key already exists.
    Returns (added, skipped). Portable across Postgres/SQLite."""
    import json

    init_db()
    added = skipped = 0
    eng = engine()
    for i, job in enumerate(jobs):
        raw = json.dumps(raws[i]) if raws and i < len(raws) else None
        row = dict(
            dedup_key=job.dedup_key(), source=job.source, title=job.title,
            company=job.company, location=job.location, description=job.description,
            apply_link=job.apply_link, email=job.email, posted=job.posted,
            hiring_contact=job.hiring_contact, hiring_contact_url=job.hiring_contact_url,
            external_id=job.external_id, raw=raw, status="pending",
        )
        try:
            with eng.begin() as conn:
                conn.execute(insert(jobs_table).values(**row))
            added += 1
        except IntegrityError:
            skipped += 1  # dedup_key already present
    return added, skipped


def counts() -> dict[str, int]:
    init_db()
    with engine().connect() as conn:
        rows = conn.execute(
            select(jobs_table.c.status, func.count()).group_by(jobs_table.c.status)
        ).all()
    return {status: n for status, n in rows}


def list_jobs(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    stmt = select(jobs_table)
    if status:
        stmt = stmt.where(jobs_table.c.status == status)
    stmt = stmt.order_by(jobs_table.c.id).limit(limit)
    with engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(stmt)]


def unscored_jobs(limit: int = 500) -> list[dict[str, Any]]:
    """Pending jobs that haven't been scored yet (match_score IS NULL)."""
    init_db()
    stmt = (
        select(jobs_table)
        .where(jobs_table.c.status == "pending", jobs_table.c.match_score.is_(None))
        .order_by(jobs_table.c.id)
        .limit(limit)
    )
    with engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(stmt)]


def top_matches(limit: int = 20, min_score: int = 0, status: str = "pending") -> list[dict[str, Any]]:
    """Scored jobs ordered best-first — feeds the swipe bot (M4)."""
    init_db()
    stmt = (
        select(jobs_table)
        .where(
            jobs_table.c.status == status,
            jobs_table.c.match_score.is_not(None),
            jobs_table.c.match_score >= min_score,
        )
        .order_by(jobs_table.c.match_score.desc())
        .limit(limit)
    )
    with engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(stmt)]


def fit_pct(good: int = 70) -> dict[str, int]:
    """Lightweight: how many scored jobs are strong fits (single aggregate query)."""
    init_db()
    g = func.sum(case((jobs_table.c.match_score >= good, 1), else_=0))
    t = func.count(jobs_table.c.match_score)
    with engine().connect() as conn:
        row = conn.execute(select(g, t)).first()
    good_n, total = (row[0] or 0), (row[1] or 0)
    return {"good": int(good_n), "total": int(total),
            "pct": round(int(good_n) / total * 100) if total else 0}


def scored_jobs(limit: int = 1000) -> list[dict[str, Any]]:
    """All jobs that have a match_score (any status) — for batch fit summary."""
    init_db()
    stmt = (
        select(jobs_table)
        .where(jobs_table.c.match_score.is_not(None))
        .order_by(jobs_table.c.match_score.desc())
        .limit(limit)
    )
    with engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(stmt)]


def set_status(job_id: int, status: str) -> None:
    with engine().begin() as conn:
        conn.execute(
            update(jobs_table).where(jobs_table.c.id == job_id).values(status=status)
        )


def set_contact(job_id: int, email: str, name: str = "") -> None:
    with engine().begin() as conn:
        conn.execute(
            update(jobs_table)
            .where(jobs_table.c.id == job_id)
            .values(email=email, hiring_contact=name)
        )


def get_job(job_id: int) -> dict[str, Any] | None:
    with engine().connect() as conn:
        row = conn.execute(
            select(jobs_table).where(jobs_table.c.id == job_id)
        ).first()
    return dict(row._mapping) if row else None


def set_match(job_id: int, score: int, comment: str) -> None:
    with engine().begin() as conn:
        conn.execute(
            update(jobs_table)
            .where(jobs_table.c.id == job_id)
            .values(match_score=score, comment=comment)
        )
