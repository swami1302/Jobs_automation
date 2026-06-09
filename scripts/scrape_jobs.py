"""M2 runner: scrape fresh jobs -> normalize -> store in SQLite.

Usage:
    .venv/bin/python -m scripts.scrape_jobs

Reads target titles + location from data/profile.json (built in M1), asks the
Apify actor for recently-posted jobs, normalizes them, and stores new ones
(deduped) in data/db/jobs.db. Raw output is saved to data/db/raw_<source>.json
so we can verify the field mapping.

Tunable via .env:
    APIFY_ACTOR        default curious_coder/linkedin-jobs-scraper
    JOB_SOURCE         default linkedin
    JOBS_PER_RUN       default 20   (actor minimum is 10)
    MAX_TITLES         default 4    (how many target titles to search)
    SCRAPE_COMPANY     default true (gets company/contact details; slower/costlier)
"""
from __future__ import annotations

import json
import os
from urllib.parse import quote_plus

from src import config, scraper, store
from src.profile import load_profile


def linkedin_search_urls(titles: list[str], location: str) -> list[str]:
    """Build public LinkedIn job-search URLs (f_TPR=r604800 = posted last 7 days)."""
    base = "https://www.linkedin.com/jobs/search/"
    urls = []
    for t in titles:
        urls.append(
            f"{base}?keywords={quote_plus(t)}"
            f"&location={quote_plus(location)}&f_TPR=r604800"
        )
    return urls


def main() -> None:
    actor = config.get("APIFY_ACTOR", "curious_coder/linkedin-jobs-scraper")
    source = config.get("JOB_SOURCE", "linkedin")
    count = int(config.get("JOBS_PER_RUN", "20"))
    max_titles = int(config.get("MAX_TITLES", "4"))
    scrape_company = config.get("SCRAPE_COMPANY", "true").lower() == "true"

    profile = load_profile()
    terms = scraper.search_terms(profile)
    titles = terms["titles"][:max_titles]
    location = terms["location"]

    print(f"[1/4] Searching {source} for {titles} in '{location}'")
    urls = linkedin_search_urls(titles, location)
    run_input = {"urls": urls, "count": count, "scrapeCompany": scrape_company}

    print(f"[2/4] Running Apify actor '{actor}' (count={count}) ...")
    items = scraper.run_actor(actor, run_input, max_items=count)
    print(f"      Got {len(items)} raw items.")

    # save raw for inspection / debugging the field mapping
    raw_path = config.DB_DIR / f"raw_{source}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(items, indent=2, default=str))
    if items:
        print(f"      Sample item keys: {sorted(items[0].keys())}")
        print(f"      (raw saved -> {raw_path})")

    print("[3/4] Normalizing ...")
    jobs = scraper.normalize(items, source)
    print(f"      {len(jobs)} usable jobs after cleaning.")

    print("[4/4] Storing (dedup) ...")
    added, skipped = store.upsert_jobs(jobs, raws=items[: len(jobs)])
    print(f"      added={added} skipped(dup)={skipped}")
    print(f"      DB status counts: {store.counts()}\n")

    for j in jobs[:5]:
        print(f"  • {j.title}  @ {j.company}  [{j.location}]")
        if j.hiring_contact or j.email:
            print(f"      contact: {j.hiring_contact} {j.email}")


if __name__ == "__main__":
    main()
