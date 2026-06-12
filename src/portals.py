"""Portal registry — each job source = an Apify actor + an input builder.

All portals feed the same normalizer (src/scraper.normalize) and DB, tagged by
`source`. Cross-portal duplicates collapse via Job.dedup_key. Which portals run
is controlled by JOB_SOURCES in .env (default: linkedin,indeed,naukri).

Each builder: build(titles, locations, exp_codes, days, count) -> run_input dict.
  titles      list[str]  e.g. ["React Developer", "Full Stack Developer (React/Node)"]
  locations   list[str]  e.g. ["Bengaluru", "Remote"]
  exp_codes   list[str]  LinkedIn f_E codes ["2","3"] (other portals map as best they can)
  days        int        freshness window
  count       int        max results for this portal
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus

_PAREN = re.compile(r"\s*\([^)]*\)")


def clean_titles(titles: list[str]) -> list[str]:
    out, seen = [], set()
    for t in titles:
        c = _PAREN.sub("", t).strip()
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


def _or_query(titles: list[str]) -> str:
    return " OR ".join(f'"{t}"' for t in clean_titles(titles))


def _slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _PAREN.sub("", t).lower()).strip("-")


def _nearest(days: int, allowed: list[int]) -> int:
    return min(allowed, key=lambda x: abs(x - days))


# ---------------------------------------------------------------- builders


def linkedin_input(titles, locations, exp_codes, days, count) -> dict:
    kw = _or_query(titles)
    tpr = f"r{days * 86400}"
    f_e = "".join(f"&f_E={e.strip()}" for e in exp_codes if e.strip())
    urls = []
    for loc in locations:
        loc = loc.strip()
        remote = loc.lower() == "remote"
        geo = "India" if remote else loc
        u = (f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(kw)}"
             f"&location={quote_plus(geo)}&f_TPR={tpr}{f_e}")
        if remote:
            u += "&f_WT=2"
        urls.append(u)
    return {"urls": urls, "count": count, "scrapeCompany": False}


def indeed_input(titles, locations, exp_codes, days, count) -> dict:
    q = _or_query(titles)
    start = []
    for loc in locations:
        l = "Remote" if loc.strip().lower() == "remote" else loc.strip()
        start.append({"url": (
            f"https://in.indeed.com/jobs?q={quote_plus(q)}"
            f"&l={quote_plus(l)}&fromage={days}&sort=date"
        )})
    per = max(1, count // max(1, len(start)))
    return {
        "startUrls": start,
        "maxItemsPerSearch": per,
        "country": "IN",
        "followApplyRedirects": True,
    }


def naukri_input(titles, locations, exp_codes, days, count) -> dict:
    # Naukri actor takes one location string; "" = pan-India (broadest).
    non_remote = [l for l in locations if l.strip().lower() != "remote"]
    location = non_remote[0] if len(non_remote) == 1 else ""
    return {
        "job_title": ", ".join(clean_titles(titles)),
        "location": location,
        "no_of_jobs": count,
        "job_age": str(_nearest(days, [1, 3, 7, 15, 30])),
        "experience": 0,  # min years — 0 surfaces entry/junior roles
    }


def wellfound_input(titles, locations, exp_codes, days, count) -> dict:
    # Remote role pages (best fit for startups). Requires RESIDENTIAL proxy.
    urls = [{"url": f"https://wellfound.com/role/r/{_slug(t)}"}
            for t in clean_titles(titles)]
    return {
        "listingStartUrls": urls,
        "scrapeJobDetails": False,
        "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
    }


PORTALS: dict[str, dict] = {
    "linkedin": {"actor": "curious_coder/linkedin-jobs-scraper", "build": linkedin_input},
    "indeed": {"actor": "misceres/indeed-scraper", "build": indeed_input},
    "naukri": {"actor": "nuclear_quietude/naukri-job-scraper", "build": naukri_input},
    "wellfound": {"actor": "mscraper/wellfound-jobs-scraper", "build": wellfound_input},
}
