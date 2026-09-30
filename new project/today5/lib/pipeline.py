"""Runs all steps for one company (task 5):
Input -> Research -> AI analysis -> Structured output -> Database.
Save order: snapshot -> brief -> signals -> score -> contacts -> message.
(score needs contacts for reachability, so contacts are computed first and saved right after the score)

AI calls per company: 1) facts + brief + signals, 2) person + pain match, 3) message + generic check
(+1 only if the message breaks a rule).
"""
import logging
import os
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

from lib import ai, analyze, outreach, people, reliability, research, score, settings, signals
from lib.db import db
from lib.util import domain_of, norm_url, now_iso

log = logging.getLogger("pipeline")

# On Vercel there is no long-running process: research runs inside the request.
SERVERLESS = bool(os.environ.get("VERCEL"))
STUCK_AFTER = timedelta(minutes=6)  # a "researching" row older than this was cut off by a timeout


def set_status(company_id, status, **extra):
    db().update("companies", {"status": status, "status_updated_at": now_iso(), **extra}, id=f"eq.{company_id}")


def latest(table, company_id):
    rows = db().select(table, company_id=f"eq.{company_id}", order="created_at.desc", limit=1)
    return rows[0] if rows else None


def friendly(e):
    """Short message for the companies list."""
    if isinstance(e, (ai.AIError, research.ResearchError)):
        return str(e)[:300]
    return f"Unexpected error: {str(e)[:200]}"


def run(company_id):
    """Research one company. Returns 'done', 'failed' or 'limited' (AI limit: company goes back to the queue)."""
    d = db()
    rows = d.select("companies", id=f"eq.{company_id}")
    if not rows:
        return "failed"
    company = rows[0]
    set_status(company_id, "researching", last_error=None)
    try:
        website = company["website"]
        prev = latest("snapshots", company_id)

        # 2. research
        pages = research.read_site(website)
        if "home" not in pages:
            raise research.ResearchError("Website could not be read (the site is down or blocks automatic readers)")
        name = research.name_from_home(pages, website)
        news = research.search_news(name)

        # 3. AI analysis (one call: facts + brief + changes vs the previous snapshot)
        sources_text, allowed = analyze.build_sources(pages, news)
        old_facts = analyze.slim_facts(prev.get("facts")) if prev else None
        result = analyze.analyze_all(name, sources_text, old_facts)
        resolved = reliability.resolve(result.facts, allowed, domain_of(website))

        # 4-5. structured output + save
        snap = d.insert("snapshots", {
            "company_id": company_id,
            "raw_pages": {k: {"url": v["url"], "text": v["text"]} for k, v in pages.items()},
            "news": news,
            "facts": resolved,
        })[0]

        brief = analyze.clean_brief(result.brief, allowed)
        d.insert("briefs", {"company_id": company_id, "snapshot_id": snap["id"], "brief": brief})

        existing = d.select("signals", company_id=f"eq.{company_id}")
        prev_allowed = dict(allowed)
        for v in ((prev or {}).get("facts") or {}).values():
            if isinstance(v, dict):
                for it in v.get("items", []):
                    prev_allowed.setdefault(norm_url(it["source_url"]), it["source_url"])
        new_signals = signals.process(result.changes, news, prev_allowed, existing)
        if new_signals:
            d.insert("signals", [{**s, "company_id": company_id} for s in new_signals])
        all_signals = existing + new_signals

        contact_rows, pain_score, pain_reason = people.find_and_pain(name, pages, resolved)
        sc = score.compute(website, resolved, all_signals, contact_rows, pain_score, pain_reason)
        d.insert("scores", {"company_id": company_id, **sc})
        saved_contacts = d.insert("contacts", [{**c, "company_id": company_id} for c in contact_rows])

        first = next((c for c in saved_contacts if c["rank"] == 1), None)
        msg = outreach.write(name, brief, all_signals, first)
        d.insert("messages", {"company_id": company_id, "contact_id": first["id"] if first else None, **msg})

        set_status(company_id, "researched", name=name, last_error=None)
        return "done"
    except ai.AILimitError as e:
        log.warning("AI limit while researching %s: %s", company_id, e)
        set_status(company_id, "queued", last_error="Waiting: AI limit reached. Continues automatically later.")
        return "limited"
    except Exception as e:  # any other failure -> mark failed, never crash the app
        log.error("research failed for %s: %s\n%s", company_id, e, traceback.format_exc())
        set_status(company_id, "failed", last_error=friendly(e))
        return "failed"


def save_old_info(company_id, text):
    """Demo helper: paste older company info; saved as an older snapshot so the next run can diff against it."""
    d = db()
    company = d.select("companies", id=f"eq.{company_id}")[0]
    name = company.get("name") or domain_of(company["website"])
    sources_text, allowed = analyze.build_sources({}, [], manual_text=text)
    facts = analyze.extract_facts(name, sources_text)
    resolved = reliability.resolve(facts, allowed, domain_of(company["website"]))
    return d.insert("snapshots", {
        "company_id": company_id,
        "raw_pages": {"manual": {"url": "manual:old-info", "text": text[:8000]}},
        "news": [],
        "facts": resolved,
    })[0]


# ---------- queue ----------
# Companies are marked "queued" in the database and researched ONE AT A TIME in CSV/list order (seq).
# Local: a background thread takes the next one. Vercel: each request (page or cron) takes the next one.

def _parse_t(v):
    return datetime.fromisoformat(v.replace("Z", "+00:00")) if v else None


def queue_state():
    """Returns ('paused'|'limited'|'busy'|'idle'|'ready', next_company_row)."""
    if settings.automation().get("paused_all"):
        return "paused", None
    if ai.blocked_until():
        return "limited", None
    now = datetime.now(timezone.utc)
    rows = db().select("companies", select="id,status,status_updated_at,paused,seq")
    ready = []
    for c in rows:
        t = _parse_t(c.get("status_updated_at"))
        if c["status"] == "researching":
            if t and now - t <= STUCK_AFTER:
                return "busy", None  # someone is researching right now -> wait (one at a time)
            ready.append(c)          # stuck after a timeout -> retry
        elif c["status"] == "queued":
            ready.append(c)
    ready = [c for c in ready if not c.get("paused")]
    if not ready:
        return "idle", None
    ready.sort(key=lambda c: c.get("seq") or 0)
    return "ready", ready[0]


def run_next():
    """Research the next queued company now (if allowed). Returns {"state": ..., "company_id": ...}."""
    state, row = queue_state()
    if state != "ready":
        return {"state": state, "company_id": None}
    claimed = db().update("companies", {"status": "researching", "status_updated_at": now_iso()},
                          id=f"eq.{row['id']}", status=f"eq.{row['status']}")
    if not claimed:
        return {"state": "busy", "company_id": None}  # another request took it
    return {"state": run(row["id"]), "company_id": row["id"]}


def enqueue(company_id, first=False):
    """Mark a company to be researched. first=True puts it at the front of the queue."""
    values = {"status": "queued", "status_updated_at": now_iso(), "last_error": None}
    if first:
        rows = db().select("companies", select="seq", order="seq.asc", limit=1)
        values["seq"] = (rows[0]["seq"] if rows and rows[0].get("seq") is not None else 0) - 1
    db().update("companies", values, id=f"eq.{company_id}", status="neq.researching")


def run_queued_for(seconds):
    """Serverless: keep researching queued companies while time is left. Returns counts."""
    start, done, failed, last_state = time.monotonic(), 0, 0, "idle"
    while time.monotonic() - start < seconds:
        r = run_next()
        last_state = r["state"]
        if r["state"] == "done":
            done += 1
        elif r["state"] == "failed":
            failed += 1
        else:
            break
    return {"researched": done, "failed": failed, "stopped_because": last_state}


def _worker():
    while True:
        try:
            r = run_next()
            if r["state"] in ("done", "failed"):
                continue
        except Exception:
            log.exception("worker error")
        time.sleep(5)


def start_worker():
    threading.Thread(target=_worker, daemon=True).start()
