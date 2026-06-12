"""M2/M7a runner: scrape fresh jobs from ALL enabled portals -> normalize -> store.

    .venv/bin/python -m scripts.scrape_jobs

Portals run independently (one failing doesn't stop the others) and all feed the
same DB, deduped across sources. Configure in .env:
    JOB_SOURCES       comma-sep portals: linkedin,indeed,naukri
    JOB_TITLES        roles to search (comma-sep)
    JOB_LOCATIONS     locations incl. Remote (comma-sep)
    EXPERIENCE_LEVELS LinkedIn f_E codes (2,3 = entry/associate)
    FRESH_DAYS        only jobs newer than N days (default 7)
    JOBS_PER_RUN      max results PER PORTAL (default 50)
"""
from __future__ import annotations

import json

from src import config, portals, scraper, store
from src.profile import load_profile


def main() -> None:
    profile = load_profile()
    sources = [s.strip() for s in
               config.get("JOB_SOURCES", "linkedin,indeed,naukri").split(",") if s.strip()]
    count = int(config.get("JOBS_PER_RUN", "50"))
    days = int(config.get("FRESH_DAYS", "7"))
    exp = [e for e in (config.get("EXPERIENCE_LEVELS", "2,3") or "").split(",") if e]

    titles_env = config.get("JOB_TITLES")
    titles = titles_env.split(",") if titles_env else profile.target_titles
    locs_env = config.get("JOB_LOCATIONS")
    locations = locs_env.split(",") if locs_env else (
        profile.preferred_locations or ["Remote"])

    print(f"Sources: {sources}")
    print(f"Titles: {portals.clean_titles(titles)}")
    print(f"Locations: {locations} | exp {exp} | fresh {days}d | {count}/portal\n")

    total_added = total_skipped = 0
    for src in sources:
        spec = portals.PORTALS.get(src)
        if not spec:
            print(f"[{src}] unknown portal — skipped")
            continue
        try:
            run_input = spec["build"](titles, locations, exp, days, count)
            print(f"[{src}] running {spec['actor']} …")
            items = scraper.run_actor(spec["actor"], run_input, max_items=count)
            (config.DB_DIR / f"raw_{src}.json").write_text(
                json.dumps(items, indent=2, default=str))
            jobs = scraper.normalize(items, src)
            added, skipped = store.upsert_jobs(jobs, raws=items[: len(jobs)])
            total_added += added
            total_skipped += skipped
            print(f"[{src}] {len(items)} scraped → added {added}, dup {skipped}")
        except Exception as e:  # noqa: BLE001 — keep going with other portals
            print(f"[{src}] FAILED: {str(e).splitlines()[0][:160]}")

    print(f"\nTotal: added {total_added}, dup {total_skipped}")
    print(f"DB status counts: {store.counts()}")


if __name__ == "__main__":
    main()
