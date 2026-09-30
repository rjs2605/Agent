# LeadPulse — AI Sales Radar ("Today's 5")

An AI sales assistant that researches companies from their website and news, scores them, finds the right person to contact, and every day shows **only the top 5 companies worth acting on**, each with the reason why now and a ready-to-send personal message.

## Problem and who it is for

Sales teams waste hours researching accounts that are not ready to buy. Today's 5 does the research and tells you who to contact **today**, and why.

**What we sell (config):** a customer-support automation tool (shared helpdesk plus an AI chat agent).
**Ideal customer:** Indian B2B or D2C companies with 50–1000 staff that run customer-support or sales teams.
Both are set in `config.py` (`PRODUCT`, `ICP`, `TARGET_ROLES`).

## How it works (pipeline in 5 lines)

1. **Input**: paste URLs or upload a CSV. URLs are cleaned (`https://`, no path, no trailing slash) and duplicates are skipped.
2. **Research**: Jina Reader reads the home, about, careers/jobs, blog/news and pricing pages (404s are skipped, each page is cut to 8,000 characters). Tavily searches the news.
3. **AI analysis**: Gemini extracts facts using only the given text. Every fact needs a `source_url`, missing facts are left empty, and the JSON is validated with pydantic (one retry, otherwise the company is marked failed).
4. **Structured output**: an 8-section brief, signals, score, first-choice and backup contact, and a message.
5. **Database**: rows are saved in the order snapshot → brief → signals → score → contacts → message, and the company status becomes `researched`.

## Scoring formula and why

`TOTAL (0–100) = FIT (0–40) + TIMING (0–40) + REACHABILITY (0–20)`

| Part | Rule |
|---|---|
| FIT | industry keyword match 10 + based in India 5 + size fit 15 (50–1000 staff = 15; near the range = 7; unknown = 5) + **pain match 0–10 (the only part judged by AI)** |
| TIMING | each real signal in the last 90 days adds 20 (≤14 days), 15 (≤30), 10 (≤60) or 5 (≤90), capped at 40 |
| REACHABILITY | named person 20, only a role 10, nothing 0 |

**Why:** fit alone gives a static list, and timing is what makes "today" different from last month. Reachability matters because a great account with no contact cannot be acted on. Everything except the pain judgement is plain code, so scores are repeatable and explainable. The reasons are shown on screen as short sentences, for example "Funding: Raised Series A (3 weeks ago)".

## Signal vs noise rules

Every research run compares the latest snapshot's facts with the previous snapshot's facts and also classifies each news item.

- **SIGNAL:** funding, new leader, hiring spike, new product, new location, big customer win, pricing change.
- **NOISE:** blog post, design or text change, footer, cookie banner, minor edits, unrelated or old news.

Only signals (`is_signal = true`) affect TIMING. The same news item is never recorded twice. For demos, **"Compare with older info"** on the Signals tab saves pasted text as an older snapshot, so the next run shows a two-point-in-time comparison.

## Data reliability rules

- **Source priority:** company's own website > reputable recent news > directories/aggregators (Crunchbase, LinkedIn, Tracxn…) > AI inference. The source type is decided by code from the URL, not by the AI.
- **Newest wins** within the same priority level.
- **Conflicts:** when two sources disagree on size or funding, both values are kept, the higher-priority one is shown first, and a **Conflicting** badge shows both values with their links.
- **Confidence:** high = official website or 2+ sources agree; medium = one good (news) source; low = directory only, older than a year, or inferred.
- **Never show a fact without a source:** any fact, brief line or signal whose `source_url` is not one of the pages or news actually read is dropped. Contact names that do not appear in the source text are removed ("name not found").

## The "only 5 today" change

The home page used to be a ranked list. It now shows **at most 5** companies (`GET /api/today`):

1. The company must have at least one real signal in the last 30 days.
2. Companies marked Done or Not relevant are hidden; snoozed ones are hidden for 7 days.
3. Companies are sorted by total score.
4. If fewer than 5 qualify, fewer are shown. The list is never padded with weak companies.

Clicking Done / Snooze / Not relevant saves an `actions` row, animates the card away, and the next qualifying company moves up.

## Features

- **Login**: one username and password (`APP_USERNAME` / `APP_PASSWORD`). Every page and API route is locked without it.
- **Companies**:
  - Paste websites or upload a CSV (100+ is fine), with a preview and duplicate check first.
  - Research runs one company at a time, in the order the companies were added.
  - Each company has **Pause**, **Delete** and **Export** buttons. For the whole list there are **Pause all** and **Export all**.
  - Exports are available as CSV, Excel or PDF.
- **Settings → Integrations**: every API except the database has a backup, and all keys can be changed from the website with a **Test** button:
  - AI: Gemini ⇄ Groq, with a backup key for each and your choice of which goes first.
  - Search: Tavily ⇄ Jina Search, plus a backup Tavily key.
  - Website reader: Jina, falling back to a direct page fetch.
- **Settings → Automation**:
  - Runs every day at the time you set (IST). Locally a timer runs it at that time. Online it starts the first time the app is opened after that time, plus a daily Vercel Cron check (and an optional free cron-job.org pinger for exact timing).
  - Shows the next run, has an on/off switch, a "companies re-checked per day" limit, a **Run now** button and the run history.
- **Settings → Target customer**: product, ideal customer, company size, industries and roles, all editable. They drive the scoring and contact search.
- **AI usage**: about 3 calls per company:
  1. facts + brief + signals
  2. person + pain match
  3. message + generic check

  When every AI provider is at its limit, the company waits in the queue and research continues automatically later.

## Run locally

Requires only Python 3.11+ with `httpx`, `pydantic` and `google-genai`.

1. In Supabase, open **SQL Editor**, paste `schema.sql` and click **Run**. If you already ran an older version, run `migration.sql` instead.
2. Fill in `.env.local` (see `.env.example`).
3. Run `python app.py` and open http://localhost:8000.
4. Daily refresh: run `python cron_daily.py`. It re-researches companies that have not been updated in 24 hours, `CRON_BATCH` at a time. `GET /api/cron/daily` with `Authorization: Bearer <CRON_SECRET>` does the same through the server.

## Deploy (Vercel)

- `api/index.py` is the Vercel entry point. `vercel.json` routes every URL to it, so the same code runs locally and on Vercel.
- On Vercel there is no background worker. Research for one company runs inside one request (`maxDuration` 300s), and the companies page researches queued companies one after another (`POST /api/run-next`).
- `/api/cron/daily` (with `Authorization: Bearer <CRON_SECRET>`) runs the automation only when it is due (your run time has passed and it has not run today). Vercel Cron calls it once a day at 02:30 UTC (08:00 IST), because the Hobby plan allows only daily crons. The app also checks when it is opened. Each run queues stale companies and researches as many as fit in about 150 seconds; anything left continues on the next run or while the companies page is open.
- A run cut off by a timeout (status stuck on "researching" for more than 6 minutes) is retried automatically.

## What I would build next

- A real team/leadership page crawler (more pages, sitemap-based) for better contact finding.
- Email lookup and verification for the chosen contact, plus one-click send and reply tracking.
- Learning from feedback: use Done / Not relevant history to re-weight the scoring.
- Multi-user accounts, each with its own ideal-customer config.
- A weekly digest email of "Today's 5".
