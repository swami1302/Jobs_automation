# Contributing to job-swipe-bot

A Tinder-style job-application assistant on Telegram. It scrapes jobs from
multiple portals, uses an LLM to score each against **your** resume, lets you
swipe ✅/❌ on Telegram, and on ✅ drafts a tailored cold email + LinkedIn message
you can send.

> **This repo ships personalized to its original author** (one resume, one set of
> search preferences). Nothing in the *code* is hard-coded to a person — all the
> "you" lives in two places you replace with your own:
> 1. `data/resumes/<your-resume>.pdf` → generates `data/profile.json`
> 2. your own API keys + search prefs in `.env`
>
> Swap those and the whole system is yours. See **[Make it yours](#make-it-yours)**.

---

## How it works

```
                 ┌── Apify actors (LinkedIn / Indeed / Naukri)
  scrape  ───────┤   src/portals.py · src/scraper.py
                 └── normalize → DB (src/store.py: SQLite or Neon Postgres)
                          │
  match   ── LLM scores each job vs YOUR profile ── src/matcher.py
                          │   (free provider chain, src/llm.py)
                          ▼
  swipe   ── Telegram bot sends top matches one card at a time ── src/bot.py
                          │   ✅ Apply / ❌ Skip / 🔖 Save
                          ▼
  on ✅   ── enrich contact (Hunter.io)  ── src/contacts.py
            draft cold email + LinkedIn msg ── src/messages.py
            optional one-tap Gmail send    ── src/mailer.py
```

Everything is driven by `data/profile.json`, which is built **once** from your
resume. The LLM never sees a hard-coded identity — only that profile.

---

## Quick start

```bash
# 1. Python 3.12+ and a virtualenv
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. configure your keys
cp .env.example .env        # then fill in the values (see Configuration below)

# 3. build YOUR profile from YOUR resume
#    drop your resume PDF into data/resumes/ first
.venv/bin/python -m scripts.build_profile     # → writes data/profile.json

# 4. scrape → score → swipe
.venv/bin/python -m scripts.scrape_jobs
.venv/bin/python -m scripts.match_jobs
.venv/bin/python -m scripts.run_bot           # open Telegram, send /start
```

Or drive the whole pipeline from the terminal UI: `.venv/bin/python -m scripts.tui`.

---

## Make it yours

The system is generic; only your **inputs** are personal. To re-target it:

| What | Where | How to replace |
|------|-------|----------------|
| Your resume | `data/resumes/*.pdf` | drop in your PDF, run `scripts.build_profile` |
| Your profile | `data/profile.json` | auto-generated (gitignored) — never edit by hand |
| Search prefs | `.env` | set `JOB_TITLES`, `JOB_LOCATIONS`, `EXPERIENCE_LEVELS` |
| Your bot | `.env` | your own `TELEGRAM_BOT_TOKEN` from @BotFather |
| Your sender | `.env` | your own `GMAIL_ADDRESS` + app password (for sending) |
| Your signature | `.env` | `RESUME_URL` (public link shown in the LinkedIn message) |

`data/profile.json` and `.env` are **gitignored** — your data never gets committed.
A contributor wanting to generalize further could move the remaining
profile-shaped prose out of `src/profile.py`'s prompt, but it already works for
any resume as-is.

---

## Configuration (`.env`)

Copy `.env.example` and fill what you need. Highlights:

- **LLM providers** (free, no paid Claude key required). A fallback chain tried in
  `LLM_PROVIDER_ORDER` order — first one with a working key answers:
  - `NVIDIA_API_KEY` — `meta/llama-3.3-70b-instruct` (build.nvidia.com)
  - `GEMINI_API_KEY` — `gemini-2.5-flash` (aistudio.google.com)
- **Scraping**: `APIFY_TOKEN`, plus `JOB_SOURCES`, `JOB_TITLES`, `JOB_LOCATIONS`.
- **Bot**: `TELEGRAM_BOT_TOKEN`, optional `TELEGRAM_USER_ID` lock, `MIN_MATCH_SCORE`.
- **DB**: leave `DATABASE_URL` blank for local SQLite, or set a Neon Postgres URL.
- **Contacts / send**: `HUNTER_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`.
- **Deploy flags**: `AUTOSTART_BOT`, `DAILY_CRON`, `CRON_HOUR/MINUTE/TZ`.

---

## Project layout

```
src/
  config.py     # .env loading, paths, key checks
  resume.py     # PDF → text
  profile.py    # text → structured Profile (LLM) + save/load
  llm.py        # provider-agnostic LLM with free fallback chain
  portals.py    # portal registry: each source = an Apify actor + input builder
  scraper.py    # run actors + normalize results
  store.py      # SQLAlchemy store (SQLite local / Neon Postgres in prod)
  models.py     # Job model, status constants, dedup key
  matcher.py    # LLM scoring (0–100 + seniority fit + comment)
  bot.py        # Telegram swipe bot (long-polling)
  contacts.py   # Hunter.io enrichment + LinkedIn recruiter search
  messages.py   # cold-email + LinkedIn-message generation
  mailer.py     # Gmail SMTP send with resume attachment
  insights.py   # batch fit stats + search advice
scripts/
  build_profile.py  scrape_jobs.py  match_jobs.py  run_bot.py
  daily.py          # scrape→match in one shot (used by the daily scheduler)
  tui.py            # Textual terminal control panel
  panel.py          # Flask web panel + /health (deploy host)
  reset_jobs.py  migrate_to_neon.py  summary.py
data/
  resumes/  profile.json (gitignored)  db/ (local SQLite)
```

---

## Deploying (24/7)

`scripts/panel.py` is the deploy host: it serves a `/health` endpoint and, when
`AUTOSTART_BOT=true`, launches the Telegram bot on boot (with a watchdog that
respawns it on crash). `DAILY_CRON=true` runs `scripts/daily.py` once a day.

A `render.yaml` blueprint is included for Render's free tier. Because the bot
uses **outbound** long-polling (which does *not* reset Render's 15-min idle
timer), point an uptime pinger (e.g. UptimeRobot, 5-min HTTP check) at
`https://<your-app>/health` to keep the instance awake.

---

## Extending the system

**Add a job portal** — register an Apify actor + input builder in `src/portals.py`:

```python
def myportal_input(titles, locations, exp_codes, days, count) -> dict:
    return { ... }   # whatever run_input the actor expects

PORTALS["myportal"] = {"actor": "owner/actor-name", "build": myportal_input}
```
Then add `myportal` to `JOB_SOURCES`. The shared normalizer (`src/scraper.normalize`)
handles common field names; extend it if your actor uses unusual keys.

**Add an LLM provider** — usually zero code. Any OpenAI-compatible endpoint:
```bash
LLM_PROVIDER_ORDER=nvidia,gemini,myllm
MYLLM_API_KEY=...
MYLLM_BASE_URL=https://api.myllm.com/v1
MYLLM_MODEL=some-model
```
Built-in known providers: `nvidia`, `gemini`, `groq`, `openrouter`, `openai`,
`deepseek`, `together`, `anthropic`. A provider with a non-OpenAI API shape needs
one small adapter in `src/llm.py` (keyed by `kind`).

---

## Contributing guidelines

- **Branch + PR.** Keep changes focused; describe the *why* in the PR.
- **No secrets in commits.** `.env`, `data/profile.json`, and resumes are
  gitignored — keep it that way. Never paste real keys in code, issues, or PRs.
- **Be provider-agnostic.** New LLM calls go through `src/llm.py`, never a
  hard-coded vendor SDK in feature code.
- **Match the surrounding style.** Small, readable functions; assemble final
  output in code (the LLM produces *content*, not formatting).
- **Ethics:** this tool generates copy-paste outreach for **you** to send. Do
  **not** add auto-apply / auto-connect from a user's own LinkedIn account — it's
  against LinkedIn's terms and gets accounts banned.

---

## License

Add a `LICENSE` file before publishing if you intend others to reuse it
(MIT is a common, permissive choice).
