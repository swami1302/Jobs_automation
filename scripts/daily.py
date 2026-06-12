"""M7b daily task: scrape fresh jobs from all portals, then score the new ones.

    .venv/bin/python -m scripts.daily

Runs scrape_jobs -> match_jobs back-to-back, so a single invocation refreshes the
queue end-to-end. The panel's internal scheduler (DAILY_CRON=true) calls this once
a day; it's also runnable by hand or from a Render Cron Job. A failure in scrape
does NOT skip the match step — already-scraped jobs still get scored.
"""
from __future__ import annotations

import traceback

from scripts import match_jobs, scrape_jobs


def main() -> None:
    print("=== daily: scrape ===")
    try:
        scrape_jobs.main()
    except Exception:  # noqa: BLE001 — still score whatever made it into the DB
        print("scrape step FAILED:")
        traceback.print_exc()

    print("\n=== daily: match ===")
    match_jobs.main()
    print("\n=== daily: done ===")


if __name__ == "__main__":
    main()
