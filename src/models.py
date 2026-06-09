"""Shared data models. The normalized Job is the common format every portal
scraper maps into, and what the matcher (M3) and bot (M4) consume."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

# job lifecycle in the DB
PENDING = "pending"   # scraped, not yet shown / scored
APPLIED = "applied"   # user swiped right
SKIPPED = "skipped"   # user swiped left
SAVED = "saved"       # user bookmarked


class Job(BaseModel):
    source: str = ""                 # portal: linkedin / wellfound / naukri / indeed
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    apply_link: str = ""
    email: str = ""                  # contact email if exposed
    posted: str = ""                 # e.g. "2 days ago" / a date string
    hiring_contact: str = ""         # "meet the hiring team" name, if any
    hiring_contact_url: str = ""     # their profile link, if any
    external_id: str = ""            # portal's own id, if present

    def dedup_key(self) -> str:
        """Same job posted on multiple portals collapses to one entry."""
        norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
        return f"{norm(self.company)}|{norm(self.title)}"
