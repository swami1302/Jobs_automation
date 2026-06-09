"""Copy all jobs from the local SQLite file into the configured DATABASE_URL
(Neon Postgres). Run once after setting DATABASE_URL in .env.

    .venv/bin/python -m scripts.migrate_to_neon

Preserves status / match_score / comment. Deduped by dedup_key, so it's safe to
re-run (existing rows are skipped).
"""
from __future__ import annotations

from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import IntegrityError

from src import config, store

SQLITE_URL = f"sqlite:///{config.DB_DIR / 'jobs.db'}"

_COLS = [
    "dedup_key", "source", "title", "company", "location", "description",
    "apply_link", "email", "posted", "hiring_contact", "hiring_contact_url",
    "external_id", "raw", "status", "match_score", "comment",
]


def main() -> None:
    dest = store.engine()
    if dest.dialect.name == "sqlite":
        raise SystemExit(
            "DATABASE_URL not set (still SQLite). Add your Neon URL to .env first."
        )
    print(f"Destination backend: {store.backend()}")
    store.init_db()

    src = create_engine(SQLITE_URL, future=True)
    with src.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(select(store.jobs_table))]
    print(f"Read {len(rows)} rows from local SQLite.")

    added = skipped = 0
    for r in rows:
        vals = {c: r.get(c) for c in _COLS}
        try:
            with dest.begin() as conn:
                conn.execute(insert(store.jobs_table).values(**vals))
            added += 1
        except IntegrityError:
            skipped += 1
    print(f"Migrated: added={added} skipped(dup)={skipped}")
    print(f"Neon counts now: {store.counts()}")


if __name__ == "__main__":
    main()
