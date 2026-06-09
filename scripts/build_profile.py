"""M1 runner: resume PDF -> structured profile.json

Usage:
    .venv/bin/python -m scripts.build_profile [path/to/resume.pdf]

Defaults to the first PDF found in data/resumes/.
"""
from __future__ import annotations

import sys
from pathlib import Path

from src import config
from src.profile import build_profile, save_profile
from src.resume import extract_text


def pick_resume(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    pdfs = sorted(config.RESUMES_DIR.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"No PDF in {config.RESUMES_DIR}. Pass a path or drop a resume there.")
    return pdfs[0]


def main() -> None:
    resume_path = pick_resume(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"[1/3] Reading resume: {resume_path}")
    text = extract_text(resume_path)
    print(f"      Extracted {len(text)} characters.")

    print(f"[2/3] Analyzing (providers: {', '.join(config.PROVIDER_ORDER)}) ...")
    profile = build_profile(text)

    out = save_profile(profile)
    print(f"[3/3] Saved profile -> {out}\n")

    print(f"  Name:        {profile.name}")
    print(f"  Seniority:   {profile.seniority} (~{profile.total_years_experience} yrs)")
    print(f"  Top skills:  {', '.join(profile.skills[:8])}")
    print(f"  Will search: {', '.join(profile.target_titles)}")
    print(f"  Locations:   {', '.join(profile.preferred_locations) or '(none)'}")


if __name__ == "__main__":
    main()
