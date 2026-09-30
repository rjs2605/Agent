"""Opportunity scoring (task 2).

FIT (0-40)          industry match 10 + India 5 + size match 15 + pain match 10 (AI judges pain only)
TIMING (0-40)       real signals in last 90 days; newer = more points (cap 40)
REACHABILITY (0-20) named person 20, role only 10, nothing 0
TOTAL = FIT + TIMING + REACHABILITY
"""
from config import INDIA_WORDS
from lib import settings
from lib.people import staff_count
from lib.reliability import all_values
from lib.util import days_ago, domain_of, parse_date

TYPE_LABEL = {"funding": "Funding", "hiring": "Hiring", "leader": "New leader", "product": "New product",
              "expansion": "Expansion", "customer_win": "Customer win", "pricing": "Pricing change", "other": "Signal"}


def _ago(days):
    if days <= 0:
        return "today"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    return f"{days // 30} months ago"


def compute(website, resolved, signals, contacts, pain_score, pain_reason):
    reasons = []
    t = settings.target()
    lo, hi = int(t["min_staff"]), int(t["max_staff"])

    # FIT
    text = " ".join(all_values(resolved, "what_they_sell") + all_values(resolved, "customers_industry")).lower()
    hits = [w for w in t["industries"] if w and w.lower() in text]
    industry = 10 if hits else 0
    reasons.append(f"Industry match: {', '.join(hits[:3])}" if hits else "Industry not in our target list")

    loc = " ".join(all_values(resolved, "locations")).lower()
    india = 5 if any(w in loc for w in INDIA_WORDS) or domain_of(website).endswith(".in") else 0
    reasons.append("Based in India" if india else "India presence not confirmed")

    staff = staff_count(resolved)
    if staff is None:
        size = 5
        reasons.append("Company size unknown")
    elif lo <= staff <= hi:
        size = 15
        reasons.append(f"Size fits (~{staff} staff)")
    elif lo * 0.4 <= staff < lo or hi < staff <= hi * 3:
        size = 7
        reasons.append(f"Size near our range (~{staff} staff)")
    else:
        size = 0
        reasons.append(f"Size outside our range (~{staff} staff)")

    reasons.append(f"Pain match {pain_score}/10: {pain_reason}")
    fit = industry + india + size + pain_score

    # TIMING
    timing = 0
    real = []
    for s in signals:
        if not s.get("is_signal"):
            continue
        d = parse_date(s.get("event_date")) or parse_date(s.get("detected_at"))
        age = days_ago(d)
        if age is None or age > 90:
            continue
        real.append((age, s))
    real.sort(key=lambda x: x[0])
    for age, s in real:
        pts = 20 if age <= 14 else 15 if age <= 30 else 10 if age <= 60 else 5
        timing += pts
        reasons.append(f"{TYPE_LABEL.get(s['type'], 'Signal')}: {s['description']} ({_ago(age)})")
    timing = min(timing, 40)
    if not real:
        reasons.append("No real signal in the last 90 days")

    # REACHABILITY
    first = next((c for c in contacts if c.get("rank") == 1), None)
    if first and first.get("name"):
        reach = 20
        reasons.append(f"Named contact found: {first['name']}")
    elif first and first.get("title"):
        reach = 10
        reasons.append(f"Only a role found: {first['title']}")
    else:
        reach = 0
        reasons.append("No contact found")

    return {"fit": fit, "timing": timing, "reachability": reach, "total": fit + timing + reach, "reasons": reasons}
