"""Daily automation: every day at the time set in Settings → Automation (IST, default 08:00)
1) re-checks researched companies older than 24h (up to "refresh_limit"), 2) keeps working through the queue.
Triggered by Vercel Cron (online), a timer thread (local), or the "Run now" button. Each run is logged."""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from lib import pipeline, settings
from lib.db import DBError, db
from lib.util import now_iso

log = logging.getLogger("automation")
IST = timezone(timedelta(hours=5, minutes=30))
SERVERLESS_BUDGET = 150  # seconds of research per Vercel run (the function limit is 300s)


def run_time():
    """(hour, minute) from settings, IST."""
    try:
        h, m = str(settings.automation().get("run_time") or "08:00").split(":")[:2]
        return max(0, min(23, int(h))), max(0, min(59, int(m)))
    except ValueError:
        return 8, 0


def schedule_text():
    h, m = run_time()
    return "Every day at " + datetime(2000, 1, 1, h, m).strftime("%I:%M %p").lstrip("0") + " IST"


def next_run_at():
    h, m = run_time()
    now = datetime.now(IST)
    run = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if run <= now or ran_today():
        run += timedelta(days=1)
    return run


def ran_today():
    """True if the scheduled run already happened today (IST)."""
    start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        rows = db().select("automation_runs", trigger="eq.schedule", order="started_at.desc", limit=1)
    except DBError:
        return False
    if not rows:
        return False
    t = datetime.fromisoformat(rows[0]["started_at"].replace("Z", "+00:00"))
    return t >= start


def is_due():
    """Today's run time has passed (IST) and today's scheduled run has not happened yet."""
    h, m = run_time()
    now = datetime.now(IST)
    return now >= now.replace(hour=h, minute=m, second=0, microsecond=0) and not ran_today()


_tick_lock = threading.Lock()


def tick():
    """Run the scheduled automation if it is due. Called by the local timer, Vercel Cron,
    an optional external pinger, and whenever someone opens the app."""
    if not _tick_lock.acquire(blocking=False):
        return {"ran": False, "note": "already running"}
    try:
        if not is_due():
            return {"ran": False, "note": f"not due - next run {next_run_at():%d %b %I:%M %p} IST"}
        return {"ran": True, **run("schedule")}
    finally:
        _tick_lock.release()


def stale_company_ids(limit):
    """Researched companies whose latest real snapshot is older than 24h, oldest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    last = {}
    for s in db().select("snapshots", select="company_id,created_at,raw_pages->manual"):
        if s.get("manual"):
            continue
        t = datetime.fromisoformat(s["created_at"].replace("Z", "+00:00"))
        if s["company_id"] not in last or t > last[s["company_id"]]:
            last[s["company_id"]] = t
    ids = []
    for c in db().select("companies", select="id,status,paused"):
        if c["status"] != "researched" or c.get("paused"):
            continue
        t = last.get(c["id"])
        if t is None or t < cutoff:
            ids.append((t or datetime.min.replace(tzinfo=timezone.utc), c["id"]))
    return [cid for _, cid in sorted(ids)[:limit]]


def _log_run(row, **values):
    try:
        if row is None:
            return db().insert("automation_runs", values)[0]
        db().update("automation_runs", values, id=f"eq.{row['id']}")
    except DBError:
        return None  # table not created yet: the run still works, just not logged
    return row


def run(trigger):
    """trigger: 'schedule' | 'manual'. Returns a summary dict."""
    auto = settings.automation()
    row = _log_run(None, trigger=trigger, started_at=now_iso())
    if trigger == "schedule" and not auto.get("daily_enabled", True):
        summary = {"note": "Daily automation is turned off in Settings", "refreshed": 0}
    elif auto.get("paused_all"):
        summary = {"note": "Skipped: research is paused (Pause all)", "refreshed": 0}
    else:
        ids = stale_company_ids(int(auto.get("refresh_limit") or 0))
        for cid in ids:
            pipeline.enqueue(cid)
        summary = {"refreshed": len(ids), "note": f"{len(ids)} companies queued for a re-check"}
        if pipeline.SERVERLESS:
            res = pipeline.run_queued_for(SERVERLESS_BUDGET)
            summary.update(res)
            summary["note"] += f"; researched {res['researched']}, failed {res['failed']}"
            if res["stopped_because"] == "limited":
                summary["note"] += " (stopped: AI limit reached)"
        else:
            summary["note"] += "; the background worker is researching the queue"
    _log_run(row, finished_at=now_iso(), queued=summary.get("refreshed", 0),
             researched=summary.get("researched", 0), failed=summary.get("failed", 0), note=summary["note"])
    return summary


def history(limit=10):
    try:
        return db().select("automation_runs", order="started_at.desc", limit=limit)
    except DBError:
        return []


def start_local_scheduler():
    """Local: checks every 30 seconds and runs the automation at the time set in Settings."""
    def loop():
        while True:
            try:
                tick()
            except Exception:
                log.exception("scheduled automation failed")
            time.sleep(30)
    threading.Thread(target=loop, daemon=True).start()
