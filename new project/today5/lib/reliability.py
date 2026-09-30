"""Data reliability (task 7): source priority, newest wins, conflicts, confidence.

Source priority: company's own website > news > directories/aggregators > AI inference.
Confidence: high = own website or 2+ sources agree; medium = one good (news) source;
low = directory only, older than a year, or inferred. Facts without a real source are dropped.
"""
from config import DIRECTORY_DOMAINS
from lib.analyze import FACT_KEYS
from lib.util import days_ago, domain_of, norm_url, number_signature, parse_date

PRIORITY = {"own_site": 0, "news": 1, "directory": 2, "manual": 2, "inferred": 3}
SINGLE_VALUE_KEYS = {"size_hint", "funding"}


def classify_source(url, company_domain):
    if url.startswith("manual:"):
        return "manual"
    d = domain_of(url)
    if d == company_domain or d.endswith("." + company_domain):
        return "own_site"
    if any(x in d for x in DIRECTORY_DOMAINS):
        return "directory"
    return "news"


def _same(a, b):
    sa, sb = number_signature(a), number_signature(b)
    if sa and sb:
        return sa == sb
    na = "".join(ch for ch in a.lower() if ch.isalnum())
    nb = "".join(ch for ch in b.lower() if ch.isalnum())
    return na == nb


def resolve(facts, allowed, company_domain):
    out = {}
    for key in FACT_KEYS:
        items = []
        for f in getattr(facts, key):
            url = allowed.get(norm_url(f.source_url)) if f.source_url else None
            if not url:
                continue  # never keep a fact without a real source
            d = parse_date(f.date)
            items.append({
                "value": f.value.strip(),
                "source_url": url,
                "source_type": "inferred" if key == "pain_points" else classify_source(url, company_domain),
                "date": d.isoformat() if d else None,
            })

        for it in items:
            agreeing = {o["source_url"] for o in items if _same(o["value"], it["value"])}
            age = days_ago(parse_date(it["date"]))
            if it["source_type"] == "inferred" or (age is not None and age > 365):
                it["confidence"] = "low"
            elif it["source_type"] == "own_site" or len(agreeing) >= 2:
                it["confidence"] = "high"
            elif it["source_type"] == "news":
                it["confidence"] = "medium"
            else:
                it["confidence"] = "low"

        # higher-priority source first; newer date first within the same level
        items.sort(key=lambda i: (PRIORITY[i["source_type"]], -(parse_date(i["date"]).toordinal() if i["date"] else 0)))

        conflict = False
        if key in SINGLE_VALUE_KEYS and len(items) > 1:
            conflict = any(not _same(items[0]["value"], o["value"]) for o in items[1:])
        out[key] = {"items": items, "conflict": conflict}

    out["open_roles_count"] = facts.open_roles_count
    return out


def top_value(resolved, key):
    items = (resolved or {}).get(key, {}).get("items", [])
    return items[0] if items else None


def all_values(resolved, key):
    return [i["value"] for i in (resolved or {}).get(key, {}).get("items", [])]
