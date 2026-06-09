"""M1 step 2: use Claude to turn resume text into a structured candidate profile.

The profile is what every later milestone uses: the scraper uses `target_titles`
+ `preferred_locations` to search, and the matcher scores each job against
`skills` / `seniority` / `total_years_experience` and writes the comment.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from . import config, llm


class Role(BaseModel):
    title: str
    company: str
    duration: str = Field(description="e.g. 'Jan 2022 - Present' or '2 years'")
    highlights: list[str] = Field(
        default_factory=list,
        description="2-4 short bullet points of what they did / achieved",
    )


class Profile(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    location: str = ""
    summary: str = Field(description="2-3 sentence professional summary")
    total_years_experience: float = Field(
        description="Best estimate of total years of professional experience"
    )
    seniority: str = Field(
        description="One of: intern, junior, mid, senior, lead, principal"
    )
    skills: list[str] = Field(description="Concrete technical + tooling skills")
    roles: list[Role] = Field(default_factory=list)
    education: list[str] = Field(
        default_factory=list, description="Degree, institution, year"
    )
    target_titles: list[str] = Field(
        description="5-8 job titles to search for, inferred from skills+experience"
    )
    preferred_locations: list[str] = Field(
        default_factory=list,
        description="Likely target locations incl. 'Remote' if suitable",
    )


SYSTEM = (
    "You are an expert technical recruiter. Analyze the candidate's resume and "
    "extract a structured profile. Infer target_titles and seniority from the "
    "actual skills and experience shown — be realistic, not aspirational. "
    "For target_titles, produce the exact kind of titles that appear on job "
    "portals (LinkedIn, Naukri, Wellfound, Indeed) so they can be used as search "
    "queries."
)


def build_profile(resume_text: str) -> Profile:
    """Extract a structured Profile from resume text (NVIDIA -> Gemini fallback)."""
    prompt = f"Here is the resume:\n\n<resume>\n{resume_text}\n</resume>"
    return llm.generate_structured(prompt, Profile, system=SYSTEM)


def save_profile(profile: Profile, path: Path | None = None) -> Path:
    path = path or config.PROFILE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.model_dump(), indent=2))
    return path


def load_profile(path: Path | None = None) -> Profile:
    path = path or config.PROFILE_PATH
    return Profile.model_validate_json(path.read_text())
