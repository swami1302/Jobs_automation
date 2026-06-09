# job-swipe-bot

Tinder-style job application assistant on Telegram.

Scrapes jobs from multiple portals → Claude matches them to your resume → you
swipe ✅/❌ in Telegram → on ✅ it writes a tailored cold email + LinkedIn message
for you to send.

## LLM providers (free, with fallback)

This project does **not** require a paid Claude key. It uses a fallback chain
(`src/llm.py`), tried in order from `LLM_PROVIDER_ORDER` in `.env`:

1. **NVIDIA** `meta/llama-3.3-70b-instruct` (free, build.nvidia.com) — primary
2. **Gemini** `gemini-2.5-flash` (free, aistudio.google.com) — fallback

If the primary is down/rate-limited, the next provider answers automatically
(transient 503/429/timeout errors auto-retry first). Both return the same
validated structured output, so the rest of the app is provider-agnostic.

### Adding a model later (no code needed)

Any OpenAI-compatible provider just needs env vars:

```bash
# known provider — add key + name in the order
LLM_PROVIDER_ORDER=nvidia,gemini,groq
GROQ_API_KEY=gsk_...

# brand-new provider — also give base_url + model
LLM_PROVIDER_ORDER=nvidia,gemini,myllm
MYLLM_API_KEY=...
MYLLM_BASE_URL=https://api.myllm.com/v1
MYLLM_MODEL=some-model
```

Built-in known providers: `nvidia`, `gemini`, `groq`, `openrouter`, `openai`,
`deepseek`, `together`, `anthropic`. A provider with a totally different API
shape just needs one small adapter in `src/llm.py` (keyed by `kind`).

## Build order

- **M0** Project scaffold ✅
- **M1** Resume → structured profile ✅  ← *done*
- **M2** Scrape jobs (Apify) → normalized job list ✅ *(live; jobs stored in DB)*
- **M3** LLM match + score each job  ← *next*

## Database

Backend-agnostic (`src/store.py`, SQLAlchemy):

- **No `DATABASE_URL`** → local **SQLite** at `data/db/jobs.db` (zero setup)
- **`DATABASE_URL` set** → **Neon Postgres** (cloud; persists across machines,
  has real credentials for any DB GUI, and is ready for the deployed bot in M8)

Same schema and code either way. To use Neon, put its connection string in `.env`:

```
DATABASE_URL=postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require
```

> SQLite has **no** username/password (it's just a file). Neon Postgres **does** —
> those are the creds you plug into a GUI like TablePlus/DBeaver/pgAdmin.

## M5 contact enrichment (planned)

The LinkedIn jobs actor returns **no hiring contact or email**. To get them in M5
we'll use, in order of preference:

1. **Apollo.io** API — a B2B contact/email database; given a company + role it
   finds the likely hiring person and their email. Best coverage. (`APOLLO_API_KEY`)
2. **Domain-guessing** — `firstname.lastname@company.com` patterns as a free fallback.
3. **Portal-native contacts** — Wellfound/Naukri expose recruiter names directly.

Whatever we find fills the `hiring_contact` / `email` columns, and M5 uses them to
draft the cold email + LinkedIn message.
- **M3** Claude matches + scores each job
- **M4** Telegram swipe bot
- **M5** On ✅ → generate cold email + LinkedIn templates
- **M6** Gmail one-tap send (optional)
- **M7** More portals + daily cron
- **M8** Deploy 24/7

## Setup

```bash
# 1. activate the venv (already created)
source .venv/bin/activate

# 2. keys already in .env: NVIDIA_API_KEY + GEMINI_API_KEY (both free)
#    APIFY_TOKEN / TELEGRAM_BOT_TOKEN come later (M2 / M4)
```

## M1 — build your profile

Your resume is already in `data/resumes/`. Run:

```bash
.venv/bin/python -m scripts.build_profile
```

This reads the resume, asks Claude to extract a structured profile, and writes
`data/profile.json`. That profile drives the job search and matching in later
milestones.

## Project layout

```
src/
  config.py     # loads .env, paths, key checks
  resume.py     # PDF -> text
  profile.py    # text -> structured Profile (Claude) + save/load
scripts/
  build_profile.py   # M1 runner
data/
  resumes/      # your resume PDF(s)
  profile.json  # generated (gitignored)
  db/           # job database (from M2)
```
