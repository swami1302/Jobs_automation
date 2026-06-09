"""M3: score how well each job fits the candidate, using the LLM fallback chain.

For each job we get a 0-100 score + a one-line comment. The comment is what the
user will see on the swipe card (M4), so it should name the fit AND the main
gap/risk in one sentence. Scoring is realistic: a mid-level candidate applying to
a Lead/Principal role should score low on seniority fit.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from . import llm
from .profile import Profile

DESC_LIMIT = 2000  # keep prompts small/fast — first ~2k chars of the JD is plenty


class Match(BaseModel):
    score: int = Field(description="0-100: overall fit (skills + seniority + relevance)")
    seniority_fit: str = Field(description="one of: under, good, over")
    comment: str = Field(
        description="ONE sentence (<200 chars): the fit and the main gap/risk"
    )


SYSTEM = (
    "You are a pragmatic technical recruiter. Score how well a specific job fits a "
    "specific candidate from 0-100, weighing: skills overlap, seniority fit, and "
    "domain relevance. Be realistic and discriminating — do NOT inflate. A mid-level "
    "candidate applying to a Lead/Principal/Staff role should score low (seniority "
    "'over'); a strong skills+seniority match should score high. The comment must be "
    "ONE short sentence naming the fit and the single biggest gap or risk."
)


def _profile_block(p: Profile) -> str:
    return (
        f"CANDIDATE\n"
        f"- Seniority: {p.seniority} (~{p.total_years_experience} yrs)\n"
        f"- Skills: {', '.join(p.skills)}\n"
        f"- Target roles: {', '.join(p.target_titles)}\n"
        f"- Summary: {p.summary}"
    )


def _job_block(job: dict) -> str:
    desc = (job.get("description") or "")[:DESC_LIMIT]
    return (
        f"JOB\n"
        f"- Title: {job.get('title')}\n"
        f"- Company: {job.get('company')}\n"
        f"- Location: {job.get('location')}\n"
        f"- Description: {desc}"
    )


def score_job(profile: Profile, job: dict) -> Match:
    prompt = (
        f"{_profile_block(profile)}\n\n{_job_block(job)}\n\n"
        "Score this job for this candidate."
    )
    m = llm.generate_structured(prompt, Match, system=SYSTEM, verbose=False)
    m.score = max(0, min(100, m.score))  # clamp
    return m
