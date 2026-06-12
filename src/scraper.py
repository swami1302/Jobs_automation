"""M2: scrape jobs via Apify and normalize them into our Job format.

Design: each portal is just an Apify actor + an input + the shared normalizer.
The normalizer uses broad field fallbacks because different actors name fields
differently (title vs jobTitle, companyName vs company, etc.). We also save the
raw items so we can inspect exact field names and tighten the mapping if needed.
"""
from __future__ import annotations

import re
from typing import Any

from apify_client import ApifyClient

from . import config
from .models import Job
from .profile import Profile


def get_client() -> ApifyClient:
    return ApifyClient(config.require("APIFY_TOKEN"))


def _dataset_id(run) -> str | None:
    """apify-client v3 returns a Pydantic Run object; older/raw returns a dict."""
    if run is None:
        return None
    return getattr(run, "default_dataset_id", None) or (
        run.get("defaultDatasetId") if isinstance(run, dict) else None
    )


def fetch_dataset(dataset_id: str, max_items: int = 50) -> list[dict]:
    """Read up to `max_items` items from an Apify dataset."""
    client = get_client()
    items: list[dict] = []
    for item in client.dataset(dataset_id).iterate_items():
        items.append(item)
        if len(items) >= max_items:
            break
    return items


def run_actor(actor_id: str, run_input: dict, max_items: int = 50) -> list[dict]:
    """Run an Apify actor to completion and return up to `max_items` dataset items."""
    client = get_client()
    run = client.actor(actor_id).call(run_input=run_input)
    dataset_id = _dataset_id(run)
    if not dataset_id:
        raise RuntimeError(f"Actor {actor_id} returned no dataset (run={run}).")
    return fetch_dataset(dataset_id, max_items)


# ---- normalization -------------------------------------------------------

def _first(item: dict, *keys: str) -> str:
    """Return the first present, non-empty value among candidate keys (as str)."""
    for k in keys:
        v = item.get(k)
        if isinstance(v, dict):  # some actors nest, e.g. {"company": {"name": ...}}
            v = v.get("name") or v.get("title") or v.get("url")
        if v:
            return re.sub(r"\s+", " ", str(v)).strip()  # collapse newlines/tabs
    return ""


def normalize_item(item: dict, source: str) -> Job:
    return Job(
        source=source,
        title=_first(item, "title", "jobTitle", "positionName", "position", "name",
                     "job_title"),
        company=_first(item, "companyName", "company", "company_name", "organization",
                       "company_name_text"),
        location=_first(item, "location", "jobLocation", "place", "formattedLocation",
                        "city"),
        description=_first(
            item, "description", "descriptionText", "jobDescription",
            "description_text", "snippet", "job_description",
        ),
        apply_link=_first(
            item, "jobUrl", "applyUrl", "applicationUrl", "externalApplyLink",
            "link", "url", "jobPostingUrl", "job_url",
        ),
        email=_first(item, "contactEmail", "email", "recruiterEmail"),
        posted=_first(
            item, "postedAt", "postedTime", "publishedAt", "listedAt",
            "postedDate", "postingDateParsed", "date", "job_age",
        ),
        hiring_contact=_first(
            item, "hiringPerson", "posterFullName", "jobPosterName", "recruiterName",
        ),
        hiring_contact_url=_first(
            item, "posterProfileUrl", "hiringPersonUrl", "recruiterProfileUrl",
        ),
        external_id=_first(item, "id", "jobId", "trackingId", "jobPostingId"),
    )


def normalize(items: list[dict], source: str) -> list[Job]:
    jobs = [normalize_item(it, source) for it in items]
    # drop entries with neither a title nor a company (junk rows)
    return [j for j in jobs if j.title or j.company]


# ---- search terms from the profile ---------------------------------------

def search_terms(profile: Profile) -> dict[str, Any]:
    """Pull the search inputs the scrapers need from the candidate profile."""
    return {
        "titles": profile.target_titles,
        "location": (profile.preferred_locations or ["Remote"])[0],
    }
