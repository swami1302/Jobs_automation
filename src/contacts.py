"""M5 contact enrichment: find a hiring/contact email for a job.

Order of preference:
  1. Hunter.io Domain Search (free tier ~25/mo) — real emails for the company,
     preferring recruiting/HR roles.
  2. Domain-guess fallback — careers@<domain> when Hunter has nothing or quota
     is exhausted.

We only call this for jobs the user actually ✅ Applies to, so the small free
Hunter quota is plenty.
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote_plus, urlparse

import httpx

from . import config

log = logging.getLogger("contacts")

_HR_HINTS = ("recruit", "talent", "hiring", "people", "hr", "human resource")

# Email scan of the job description (free — saves a Hunter lookup when the JD
# already lists a contact).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_EMAIL_JUNK = (
    "noreply", "no-reply", "donotreply", "do-not-reply", "example.",
    "@sentry", "sentry.io", "wixpress", ".png", ".jpg", ".jpeg", ".gif", "@2x",
)
_RECRUIT_LOCAL = (
    "recruit", "talent", "hiring", "hr@", "hr.", "career", "jobs@", "job@",
    "apply", "people", "hello@", "careers",
)


def _scan_jd_email(job: dict) -> str | None:
    """Find a usable contact email in the job description; prefer recruiting-ish
    addresses. Returns None if the JD has no clean email."""
    desc = job.get("description") or ""
    fallback = None
    for match in _EMAIL_RE.findall(desc):
        low = match.lower()
        if any(j in low for j in _EMAIL_JUNK):
            continue
        if any(h in low for h in _RECRUIT_LOCAL):
            return match
        fallback = fallback or match
    return fallback


def hunter_credits() -> int | None:
    """Remaining Hunter search credits (available − used), or None if unknown.

    Uses Hunter's /account endpoint, which does NOT consume search quota.
    """
    key = config.get("HUNTER_API_KEY")
    if not key:
        return None
    try:
        r = httpx.get("https://api.hunter.io/v2/account",
                      params={"api_key": key}, timeout=15)
        if r.status_code != 200:
            return None
        searches = ((r.json().get("data") or {}).get("requests") or {}).get("searches") or {}
        used, available = searches.get("used"), searches.get("available")
        if used is None or available is None:
            return None
        return max(0, available - used)
    except Exception:
        return None


def company_domain(job: dict) -> str | None:
    """Get the company's web domain from the scraped raw item, else None."""
    raw = job.get("raw")
    data = {}
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
    website = (
        data.get("companyWebsite")
        or data.get("companyWebsiteUrl")
        or data.get("website")
        or ""
    )
    if website:
        net = urlparse(website if "//" in website else f"//{website}").netloc
        return net.lower().removeprefix("www.") or None
    return None


def _hunter_search(domain: str | None = None, company: str | None = None) -> dict | None:
    """Hunter Domain Search by domain OR company name (Hunter resolves the domain)."""
    key = config.get("HUNTER_API_KEY")
    if not key or (not domain and not company):
        return None
    params = {"api_key": key, "limit": 10}
    if domain:
        params["domain"] = domain
    else:
        params["company"] = company
    try:
        r = httpx.get(
            "https://api.hunter.io/v2/domain-search", params=params, timeout=20
        )
        if r.status_code != 200:
            return None
        emails = (r.json().get("data") or {}).get("emails") or []
    except Exception:
        return None
    if not emails:
        return None

    def score(e: dict) -> tuple:
        pos = (e.get("position") or "").lower()
        dept = (e.get("department") or "").lower()
        hr = any(h in pos or h in dept for h in _HR_HINTS)
        personal = (e.get("type") == "personal")
        return (hr, personal, e.get("confidence") or 0)

    best = max(emails, key=score)
    name = " ".join(filter(None, [best.get("first_name"), best.get("last_name")]))
    return {
        "email": best.get("value", ""),
        "name": name,
        "position": best.get("position") or "",
        "source": "hunter",
    }


def enrich(job: dict) -> dict | None:
    """Return {email, name, position, source} or None if nothing usable.

    Tries Hunter by domain (if known) else by company name; falls back to a
    generic careers@ guess when a domain is known but Hunter found nothing.
    """
    # 1) Reuse a contact already on the job (a prior Apply, or one the scraper
    #    captured) — zero API cost.
    stored = (job.get("email") or "").strip()
    if stored:
        return {"email": stored, "name": job.get("hiring_contact") or "",
                "position": "", "source": "stored"}

    # 2) Scan the job description for an email — free, saves a Hunter credit.
    jd_email = _scan_jd_email(job)
    if jd_email:
        return {"email": jd_email, "name": "", "position": "", "source": "jd"}

    domain = company_domain(job)
    company = job.get("company") or ""

    # 3) Hunter — but only if credits remain (don't waste a call when exhausted).
    credits = hunter_credits()
    if credits is not None:
        log.info("Hunter credits remaining: %s", credits)
    if credits is None or credits > 0:
        hit = _hunter_search(domain=domain, company=company or None)
        if hit and hit.get("email"):
            return hit
    elif credits == 0:
        log.info("skipping Hunter — no search credits left")

    # 4) Last resort: a generic careers@ guess when we at least know the domain.
    if domain:
        return {"email": f"careers@{domain}", "name": "", "position": "",
                "source": "guess"}
    return None


def linkedin_people_search(company: str) -> str:
    """LinkedIn people search scoped to the company + filtered to HR/recruiter roles.

    A true company filter needs LinkedIn's internal company URN (not resolvable
    offline), so we use a boolean keyword query: the quoted company name AND any
    of the HR/recruiting titles. The user clicks through to message them.
    """
    company = (company or "").strip()
    roles = '(recruiter OR "talent acquisition" OR "HR" OR "hiring manager")'
    kw = f'"{company}" {roles}' if company else roles
    return f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(kw)}"
