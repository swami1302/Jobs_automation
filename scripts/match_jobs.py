"""M3 runner: score every unscored pending job, save to Neon, show the ranking.

    .venv/bin/python -m scripts.match_jobs

Only scores jobs that don't have a score yet, so re-running is cheap and safe.
"""
from __future__ import annotations

from src import matcher, store
from src.profile import load_profile


def main() -> None:
    profile = load_profile()
    jobs = store.unscored_jobs()
    print(f"Backend: {store.backend()} | candidate: {profile.name}")
    print(f"Scoring {len(jobs)} unscored job(s) ...\n")

    done = failed = 0
    for i, job in enumerate(jobs, 1):
        try:
            m = matcher.score_job(profile, job)
            store.set_match(job["id"], m.score, m.comment)
            done += 1
            print(f"  [{i}/{len(jobs)}] {m.score:3d}  {job['title'][:42]:42} ({m.seniority_fit})")
        except Exception as e:  # noqa: BLE001 — keep going, report at end
            failed += 1
            print(f"  [{i}/{len(jobs)}] ERR  {job['title'][:42]:42} -> {str(e)[:80]}")

    print(f"\nScored {done}, failed {failed}.\n")
    print("=== Ranked (best fit first) ===")
    for r in store.top_matches(limit=20):
        print(f"  {r['match_score']:3d}  {r['title'][:40]:40} @ {r['company'][:18]:18}")
        print(f"       {r['comment']}")


if __name__ == "__main__":
    main()
