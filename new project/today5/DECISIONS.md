# Decision log

| Decision | Reason | What I skipped |
|---|---|---|
| Python standard-library server + plain HTML/Tailwind (CDN) instead of Next.js + shadcn | Node.js is not available on the build machine; Python 3.14 with httpx, pydantic and google-genai already is | Next.js App Router, React components, shadcn/ui |
| Supabase through its REST API (httpx) | Same database and tables as the guide, no extra SDK needed; secret key used only on the server | supabase-js |
| pydantic instead of zod | Same role: validate AI JSON, retry once, otherwise mark the company failed | zod |
| Research runs in one background worker, one company at a time | Stays within the free-tier limits of Gemini (calls spaced 4s apart), Tavily and Jina; the UI polls status | Parallel research |
| Source type and confidence decided by code, not by AI | Reliability rules must be deterministic and explainable | Trusting AI "confidence" labels |
| Facts, brief lines, signals and profile links whose source is not a page/news actually read are dropped | "Never show a fact without a source link" and no hallucinated sources | Showing unsourced AI text |
| Contact names must appear in the source text | Prevents invented people | Guessing names from roles |
| Added `companies.last_error` and `signals.event_date` columns | Show why a run failed; timing and "last 30 days" need the event date, not the detection date | — |
| Contacts computed before the score, saved right after it | Reachability needs the contact, while the save order from the guide is kept | — |
| Message: code checks (<90 words, banned phrases, a question) plus an AI "generic?" check, then one regeneration | Matches the guide's rules; limits API calls | Multiple rewrite rounds |
| Daily refresh: `cron_daily.py` locally; Vercel Cron -> `/api/cron/daily` (protected by `CRON_SECRET`) | Vercel Cron only runs on production | Vercel Cron locally |
| On Vercel, research runs inside the request, one company per request; the page drains the queue | Serverless functions cannot keep a background worker alive | A paid queue service |
| Added `companies.status_updated_at` | Detects and retries runs cut off by the 300s function limit | — |
| Test list: 20 Indian D2C/fintech companies | Match the ideal customer; the app scores their size itself | Hand-checking each company's headcount |
| One username/password login with a signed cookie | Simple for a small team; works on Vercel without a session store; credentials kept only in env vars (public repo) | Per-user accounts |
| Facts + brief + signals in one AI call; person + pain in one; message + generic check in one | Free Gemini allows about 20 requests a day; 8 calls per company became 3 | Separate calls per step |
| Every external API has a backup, editable in Settings | The free tiers hit limits often; switching keys without redeploying | Paid plans |
| Keys saved on the website are stored in the `settings` table (server-only, RLS on) and always shown masked | Change keys from the frontend safely | Showing full keys |
| One company researched at a time (database lock), in CSV order | Many open tabs or cron runs cannot burn the quota in parallel | Parallel research |
| Exports built in the browser (SheetJS, jsPDF from cdnjs) | No server packages needed; works on Vercel | Server-side PDF |
