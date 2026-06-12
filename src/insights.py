"""Batch fit summary + AI advice.

After matching, summarize how well the current batch fits the candidate, and —
if the good-match rate is low — recommend how to broaden the search (titles,
locations, experience level, portals).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from . import config, llm, store
from .profile import Profile

GOOD = 70   # >= this = strong fit
OK = 50     # >= this = worth a look


def stats() -> dict:
    rows = store.scored_jobs()
    total = len(rows)
    good = sum(1 for r in rows if (r["match_score"] or 0) >= GOOD)
    ok = sum(1 for r in rows if OK <= (r["match_score"] or 0) < GOOD)
    poor = total - good - ok
    return {
        "total": total,
        "good": good,
        "ok": ok,
        "poor": poor,
        "good_pct": round(good / total * 100) if total else 0,
        "ok_plus_pct": round((good + ok) / total * 100) if total else 0,
        "rows": rows,
    }


class SearchAdvice(BaseModel):
    verdict: str = Field(description="one short line, e.g. 'Weak batch — broaden the search'")
    reasons: list[str] = Field(description="2-4 short reasons the match rate is what it is")
    suggested_titles: list[str] = Field(description="broader/alternative job titles to search")
    suggested_locations: list[str] = Field(description="locations incl. Remote to widen the pool")
    suggested_experience: str = Field(
        description="LinkedIn f_E codes to use, e.g. '2,3' (entry/associate) or '2,3,4' to include mid"
    )
    advice: str = Field(description="2-3 sentence friendly recommendation ending by asking the user to confirm or tweak preferences")


def recommend(profile: Profile, s: dict) -> SearchAdvice:
    # show the model a sample of low scorers (with their comments) + current config
    low = [r for r in s["rows"] if (r["match_score"] or 0) < OK][:12]
    sample = "\n".join(
        f"- {r['title']} @ {r['company']}: {r['match_score']} — {r['comment']}"
        for r in low
    ) or "(none)"
    prompt = (
        f"CANDIDATE: {profile.name}, {profile.seniority} (~{profile.total_years_experience}y)\n"
        f"Skills: {', '.join(profile.skills)}\n\n"
        f"CURRENT SEARCH\n- titles: {config.get('JOB_TITLES','(profile defaults)')}\n"
        f"- locations: {config.get('JOB_LOCATIONS','(profile defaults)')}\n"
        f"- experience f_E: {config.get('EXPERIENCE_LEVELS','2,3')}\n\n"
        f"BATCH RESULT: {s['total']} jobs, {s['good']} strong (>= {GOOD}), "
        f"{s['ok']} okay, {s['poor']} poor. Good-fit rate {s['good_pct']}%.\n\n"
        f"SAMPLE OF POORLY-MATCHED JOBS (title @ company: score — why):\n{sample}\n\n"
        "Diagnose why the good-fit rate is what it is and recommend concrete, broader "
        "search settings (titles/locations/experience) likely to surface better matches "
        "for THIS candidate."
    )
    return llm.generate_structured(prompt, SearchAdvice, verbose=False)
