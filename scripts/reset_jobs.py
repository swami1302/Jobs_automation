"""Wipe all jobs from the database (Neon or SQLite) — start fresh.

    .venv/bin/python -m scripts.reset_jobs --yes

Deletes every row in the `jobs` table (status, scores, contacts — everything).
The table/schema stays; only the data is cleared. Requires --yes to run.
"""
from __future__ import annotations

import sys

from sqlalchemy import delete

from src import store


def main() -> None:
    if "--yes" not in sys.argv:
        print("This DELETES ALL JOBS. Re-run with --yes to confirm:")
        print("    .venv/bin/python -m scripts.reset_jobs --yes")
        return
    store.init_db()
    before = sum(store.counts().values())
    with store.engine().begin() as conn:
        conn.execute(delete(store.jobs_table))
    print(f"Backend: {store.backend()}")
    print(f"Deleted {before} job(s). Counts now: {store.counts()}")


if __name__ == "__main__":
    main()
