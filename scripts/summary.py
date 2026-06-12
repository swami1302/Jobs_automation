"""Print a batch fit summary + AI advice on broadening the search.

    .venv/bin/python -m scripts.summary
"""
from __future__ import annotations

from src import insights
from src.profile import load_profile


def main() -> None:
    s = insights.stats()
    if not s["total"]:
        print("No scored jobs yet. Run scrape + match first.")
        return

    print("=== Batch fit summary ===")
    print(f"  Scored: {s['total']}")
    print(f"  ✅ Strong (>= {insights.GOOD}): {s['good']}  ({s['good_pct']}%)")
    print(f"  🟡 Okay ({insights.OK}-{insights.GOOD-1}):    {s['ok']}")
    print(f"  ❌ Poor (< {insights.OK}):       {s['poor']}")
    print(f"  → {s['good_pct']}% of these jobs suit you "
          f"({s['ok_plus_pct']}% worth a look).\n")

    verdict_low = s["good_pct"] < 30
    print("Getting AI advice on your search…\n" if verdict_low
          else "Looks healthy — quick check…\n")
    adv = insights.recommend(load_profile(), s)

    print(f"Verdict: {adv.verdict}")
    print("Why:")
    for r in adv.reasons:
        print(f"  • {r}")
    print("\nSuggested broader search:")
    print(f"  titles:     {', '.join(adv.suggested_titles)}")
    print(f"  locations:  {', '.join(adv.suggested_locations)}")
    print(f"  experience: {adv.suggested_experience}")
    print(f"\n{adv.advice}")
    print("\nTip: open ⚙️ Search Settings in the GUI to apply these, then Scrape again.")


if __name__ == "__main__":
    main()
