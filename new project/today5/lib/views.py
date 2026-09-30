"""Read models for the pages: company list, company detail, Today's top 5 (task 9), export."""
from datetime import timedelta

from lib.db import db
from lib.util import days_ago, parse_date, today


def _latest_by_company(rows):
    out = {}
    for r in sorted(rows, key=lambda r: r["created_at"], reverse=True):
        out.setdefault(r["company_id"], r)
    return out


def _latest_contacts(rows):
    """Latest contact per (company, rank)."""
    out = {}
    for r in sorted(rows, key=lambda r: r["created_at"], reverse=True):
        out.setdefault((r["company_id"], r["rank"]), r)
    return out


def _signal_date(s):
    return parse_date(s.get("event_date")) or parse_date(s.get("detected_at"))


def companies_list():
    d = db()
    companies = d.select("companies", order="seq.asc")
    scores = _latest_by_company(d.select("scores", select="id,company_id,total,fit,timing,reachability,created_at"))
    sigs = d.select("signals", is_signal="eq.true", select="company_id")
    counts = {}
    for s in sigs:
        counts[s["company_id"]] = counts.get(s["company_id"], 0) + 1
    out = []
    for c in companies:
        sc = scores.get(c["id"])
        out.append({**c, "score": sc, "signal_count": counts.get(c["id"], 0)})
    out.sort(key=lambda c: (float(c["score"]["total"]) if c["score"] else -1), reverse=True)
    return out


def summary(companies):
    from lib import ai, pipeline, settings
    counts = {k: 0 for k in ("new", "queued", "researching", "researched", "failed")}
    for c in companies:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    until = ai.blocked_until()
    return {
        "total": len(companies),
        **counts,
        "paused": sum(1 for c in companies if c.get("paused")),
        "paused_all": bool(settings.automation().get("paused_all")),
        "ai_blocked_until": until.isoformat() if until else None,
        "serverless": pipeline.SERVERLESS,
    }


def delete_company(cid):
    """Deletes the company and everything saved for it (cascade)."""
    return db().delete("companies", id=f"eq.{cid}")


def export_rows(ids=None):
    """One flat row per company (CSV/Excel/PDF), plus full details when exporting chosen companies."""
    d = db()
    companies = d.select("companies", order="seq.asc")
    if ids:
        companies = [c for c in companies if c["id"] in ids]
    scores = _latest_by_company(d.select("scores"))
    messages = _latest_by_company(d.select("messages"))
    briefs = _latest_by_company(d.select("briefs"))
    contacts = _latest_contacts(d.select("contacts"))
    sigs = {}
    for s in d.select("signals"):
        sigs.setdefault(s["company_id"], []).append(s)
    rows, details = [], []
    for c in companies:
        cid = c["id"]
        sc, msg, br = scores.get(cid) or {}, messages.get(cid) or {}, (briefs.get(cid) or {}).get("brief") or {}
        real = sorted([s for s in sigs.get(cid, []) if s.get("is_signal")],
                      key=lambda s: (_signal_date(s) or today()).isoformat(), reverse=True)
        top = real[0] if real else {}
        who, backup = contacts.get((cid, 1)) or {}, contacts.get((cid, 2)) or {}
        summary_line = (br.get("summary") or [{}])[0].get("text", "")
        rows.append({
            "Company": c.get("name") or "", "Website": c["website"], "Status": c["status"],
            "Paused": "yes" if c.get("paused") else "no",
            "Score": sc.get("total", ""), "Fit": sc.get("fit", ""), "Timing": sc.get("timing", ""),
            "Reachability": sc.get("reachability", ""),
            "Why now": top.get("description", ""), "Signal date": top.get("event_date", ""),
            "Signal source": top.get("source_url", ""),
            "Contact": who.get("name") or "", "Contact title": who.get("title") or "",
            "Contact LinkedIn": who.get("profile_url") or "", "Contact confidence": who.get("confidence") or "",
            "Backup contact": backup.get("name") or "", "Backup title": backup.get("title") or "",
            "Summary": summary_line,
            "Message subject": msg.get("subject", ""), "Message": msg.get("body", ""),
            "Score reasons": " | ".join(sc.get("reasons") or []),
            "Last error": c.get("last_error") or "",
        })
        if ids:
            details.append({"company": c, "brief": br, "signals": sigs.get(cid, []), "score": sc,
                            "contacts": [x for x in (who, backup) if x], "message": msg})
    return {"rows": rows, "details": details}


def company_detail(cid):
    d = db()
    rows = d.select("companies", id=f"eq.{cid}")
    if not rows:
        return None
    one = lambda t: (d.select(t, company_id=f"eq.{cid}", order="created_at.desc", limit=1) or [None])[0]
    contacts = _latest_contacts(d.select("contacts", company_id=f"eq.{cid}"))
    sigs = d.select("signals", company_id=f"eq.{cid}")
    sigs.sort(key=lambda s: (_signal_date(s) or today()).isoformat(), reverse=True)
    snaps = d.select("snapshots", company_id=f"eq.{cid}", order="created_at.desc",
                     select="id,created_at,facts,news,raw_pages")
    latest_real = next((s for s in snaps if "manual" not in (s.get("raw_pages") or {})), None)
    if latest_real:
        latest_real["raw_pages"] = {k: {"url": v["url"], "chars": len(v.get("text") or "")}
                                    for k, v in (latest_real.get("raw_pages") or {}).items()}
    return {
        "company": rows[0],
        "brief": one("briefs"),
        "score": one("scores"),
        "message": one("messages"),
        "contacts": [contacts[k] for k in sorted(contacts, key=lambda k: k[1])],
        "signals": sigs,
        "snapshot": latest_real,
        "snapshot_count": len(snaps),
        "manual_snapshots": [{"id": s["id"], "created_at": s["created_at"]} for s in snaps
                             if "manual" in (s.get("raw_pages") or {})],
        "actions": d.select("actions", company_id=f"eq.{cid}", order="created_at.desc"),
    }


def hidden_company_ids(actions):
    """done / not_relevant hide for good; snooze hides until snooze_until."""
    hidden = set()
    for cid, a in _latest_by_company(actions).items():
        if a["action"] in ("done", "not_relevant"):
            hidden.add(cid)
        elif a["action"] == "snooze":
            until = parse_date(a.get("snooze_until"))
            if until and until >= today():
                hidden.add(cid)
    return hidden


def _signal_confidence(sig, all_sigs, website):
    same_type = [s for s in all_sigs if s["type"] == sig["type"] and s.get("is_signal")]
    from lib.reliability import classify_source
    from lib.util import domain_of
    src = classify_source(sig.get("source_url") or "", domain_of(website))
    if src == "own_site" or len(same_type) >= 2:
        return "high"
    if src == "news":
        return "medium"
    return "low"


def today_five():
    """Max 5: needs a real signal in the last 30 days, not done/not relevant/snoozed,
    sorted by total score. If fewer qualify, return fewer (no weak fillers)."""
    d = db()
    companies = {c["id"]: c for c in d.select("companies", status="eq.researched")}
    hidden = hidden_company_ids(d.select("actions"))
    scores = _latest_by_company(d.select("scores"))
    messages = _latest_by_company(d.select("messages"))
    contacts = _latest_contacts(d.select("contacts"))
    by_company = {}
    for s in d.select("signals", is_signal="eq.true"):
        by_company.setdefault(s["company_id"], []).append(s)

    cards = []
    for cid, c in companies.items():
        if cid in hidden or cid not in scores:
            continue
        recent = [s for s in by_company.get(cid, []) if (days_ago(_signal_date(s)) or 999) <= 30]
        if not recent:
            continue
        recent.sort(key=lambda s: _signal_date(s), reverse=True)
        top = recent[0]
        cards.append({
            "company": c,
            "score": scores[cid],
            "why_now": {**top, "date": _signal_date(top).isoformat()},
            "who": contacts.get((cid, 1)),
            "message": messages.get(cid),
            "confidence": _signal_confidence(top, by_company.get(cid, []), c["website"]),
        })
    cards.sort(key=lambda x: float(x["score"]["total"]), reverse=True)
    return cards[:5]


def record_action(company_id, action):
    if action not in ("done", "snooze", "not_relevant"):
        raise ValueError("action must be done, snooze or not_relevant")
    row = {"company_id": company_id, "action": action}
    if action == "snooze":
        row["snooze_until"] = (today() + timedelta(days=7)).isoformat()
    return db().insert("actions", row)[0]
