"""M2 runner: scrape fresh, profile-relevant jobs -> normalize -> store.

    .venv/bin/python -m scripts.scrape_jobs

Search is configured in .env (falls back to the candidate profile if unset):
    JOB_TITLES        comma-separated roles (OR'd into one search per location)
    JOB_LOCATIONS     comma-separated; "Remote" becomes a remote-work search in India
    EXPERIENCE_LEVELS LinkedIn f_E codes, comma-separated:
                        1=Internship 2=Entry 3=Associate 4=Mid-Senior 5=Director 6=Exec
                        -> "2,3" = entry/associate (~<=2 yrs)
    FRESH_DAYS        only jobs posted within N days (default 7)
    JOBS_PER_RUN      total results cap (default 60)
    APIFY_ACTOR / JOB_SOURCE / SCRAPE_COMPANY as before
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

from src import config, scraper, store
from src.profile import load_profile

_PAREN = re.compile(r"\s*\([^)]*\)")  # strip "(React/Node)" etc. from titles


def _clean_title(t: str) -> str:
    return _PAREN.sub("", t).strip()


def keywords_or(titles: list[str]) -> str:
    """LinkedIn OR query: \"React Developer\" OR \"MERN Developer\" ..."""
    seen, parts = set(), []
    for t in titles:
        c = _clean_title(t)
        if c and c.lower() not in seen:
            seen.add(c.lower())
            parts.append(f'"{c}"')
    return " OR ".join(parts)


def search_urls(titles: list[str], locations: list[str], exp: list[str], days: int) -> list[str]:
    base = "https://www.linkedin.com/jobs/search/"
    kw = keywords_or(titles)
    tpr = f"r{days * 86400}"
    f_e = "".join(f"&f_E={e.strip()}" for e in exp if e.strip())
    urls = []
    for loc in locations:
        loc = loc.strip()
        remote = loc.lower() == "remote"
        geo = "India" if remote else loc
        url = (
            f"{base}?keywords={quote_plus(kw)}"
            f"&location={quote_plus(geo)}&f_TPR={tpr}{f_e}"
        )
        if remote:
            url += "&f_WT=2"  # remote work type
        urls.append(url)
    return urls


def main() -> None:
    profile = load_profile()
    actor = config.get("APIFY_ACTOR", "curious_coder/linkedin-jobs-scraper")
    source = config.get("JOB_SOURCE", "linkedin")
    count = int(config.get("JOBS_PER_RUN", "60"))
    days = int(config.get("FRESH_DAYS", "7"))
    exp = (config.get("EXPERIENCE_LEVELS", "2,3") or "").split(",")
    scrape_company = config.get("SCRAPE_COMPANY", "false").lower() == "true"

    titles_env = config.get("JOB_TITLES")
    titles = [t for t in titles_env.split(",")] if titles_env else profile.target_titles
    locs_env = config.get("JOB_LOCATIONS")
    locations = [l for l in locs_env.split(",")] if locs_env else (
        profile.preferred_locations or ["Remote"]
    )

    print(f"[1/4] {source}: titles={[_clean_title(t) for t in titles]}")
    print(f"      locations={locations} exp(f_E)={exp} fresh={days}d count={count}")
    urls = search_urls(titles, locations, exp, days)
    run_input = {"urls": urls, "count": count, "scrapeCompany": scrape_company}

    print(f"[2/4] Running actor '{actor}' across {len(urls)} searches ...")
    items = scraper.run_actor(actor, run_input, max_items=count)
    print(f"      Got {len(items)} raw items.")

    raw_path = config.DB_DIR / f"raw_{source}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(items, indent=2, default=str))

    print("[3/4] Normalizing ...")
    jobs = scraper.normalize(items, source)
    print(f"      {len(jobs)} usable jobs.")

    print("[4/4] Storing (dedup) ...")
    added, skipped = store.upsert_jobs(jobs, raws=items[: len(jobs)])
    print(f"      added={added} skipped(dup)={skipped}")
    print(f"      DB status counts: {store.counts()}")


if __name__ == "__main__":
    main()
