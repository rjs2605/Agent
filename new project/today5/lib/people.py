"""Find the right person (task 3): first choice + backup, with reason and confidence.
The same AI call also judges "pain match" for scoring (saves one call per company)."""
import json
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from lib import settings
from lib.ai import generate_json
from lib.reliability import all_values
from lib.research import ResearchError, web_search
from lib.util import norm_url, parse_staff


class Person(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: Optional[str] = None
    title: Optional[str] = None
    profile_url: Optional[str] = None
    reason: str = ""
    confidence: Literal["high", "medium", "low"] = "low"

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        v = str(v or "low").lower()
        return v if v in ("high", "medium", "low") else "low"


class PeopleAndPain(BaseModel):
    model_config = ConfigDict(extra="ignore")
    first: Optional[Person] = None
    backup: Optional[Person] = None
    pain_score: int = 0
    pain_reason: str = ""

    @field_validator("pain_score", mode="before")
    @classmethod
    def _clamp(cls, v):
        try:
            return max(0, min(10, int(float(v))))
        except (TypeError, ValueError):
            return 0


def staff_count(resolved):
    for v in all_values(resolved, "size_hint"):
        n = parse_staff(v)
        if n:
            return n
    return None


def target_roles(resolved):
    t = settings.target()
    n = staff_count(resolved)
    if n is not None and n < int(t["small_max_staff"]):
        return list(t["small_roles"]) + list(t["roles"])
    return list(t["roles"]) + list(t["small_roles"])


def find_and_pain(company_name, pages, resolved):
    """Returns (contact_rows, pain_score, pain_reason)."""
    t = settings.target()
    roles = target_roles(resolved)
    small = roles[0] in t["small_roles"]
    phrase = "Founder" if small else "Head of Customer"
    try:
        linkedin = web_search(f'site:linkedin.com/in "{company_name}" "{phrase}"',
                                 max_results=6, include_domains=["linkedin.com"])
    except ResearchError:
        linkedin = []

    team_text = "\n\n".join(p["text"][:4000] for k, p in pages.items() if k in ("about", "home"))
    leaders = all_values(resolved, "leaders")
    li_text = [{"title": r["title"], "url": r["url"], "snippet": (r["content"] or "")[:300]} for r in linkedin]
    sells = all_values(resolved, "what_they_sell") + all_values(resolved, "customers_industry")
    pains = all_values(resolved, "pain_points")

    prompt = f"""We sell {t["product"]}. Two tasks about {company_name}. Use ONLY the text given.

1) Pick the best person to contact. Preferred roles, best first: {", ".join(roles)}.
- name must appear in the text below; profile_url must be one of the LinkedIn result urls, else null.
- If no fitting name is found, set name null and put the best target role in title.
- first = first choice, backup = second choice (a different person or role).
- reason: one short sentence why this person. confidence: high | medium | low.

2) Pain match: how strongly does the company likely need what we sell? pain_score 0-10
(0 = no evidence, 10 = clear strong need), pain_reason: one short sentence.

Return JSON: {{"first":{{"name":"...","title":"...","profile_url":null,"reason":"...","confidence":"medium"}},
"backup":{{"name":null,"title":"...","profile_url":null,"reason":"...","confidence":"low"}},
"pain_score":0,"pain_reason":"..."}}

WHAT THEY DO: {json.dumps(sells, ensure_ascii=False)}
PAIN EVIDENCE: {json.dumps(pains, ensure_ascii=False)}
OPEN ROLES: {json.dumps(all_values(resolved, "open_roles")[:15], ensure_ascii=False)}
LEADERS FOUND ON WEBSITE/NEWS: {json.dumps(leaders, ensure_ascii=False)}
LINKEDIN RESULTS: {json.dumps(li_text, ensure_ascii=False)}
WEBSITE TEXT (home/about):
{team_text}
"""
    result = generate_json(prompt, PeopleAndPain)

    haystack = (team_text + json.dumps(leaders) + json.dumps(li_text)).lower()
    li_urls = {norm_url(r["url"]): r["url"] for r in linkedin if r.get("url")}
    rows = []
    for rank, p in ((1, result.first), (2, result.backup)):
        if p is None:
            p = Person(title=roles[min(rank - 1, len(roles) - 1)], reason="", confidence="low")
        name = (p.name or "").strip() or None
        if name and name.lower() not in haystack:
            name = None  # not in the sources -> do not show a made-up name
        profile = li_urls.get(norm_url(p.profile_url)) if p.profile_url else None
        reason = p.reason or ""
        if not name:
            reason = (reason + " " if reason else "") + "(name not found)"
        rows.append({
            "name": name,
            "title": p.title or roles[min(rank - 1, len(roles) - 1)],
            "profile_url": profile,
            "rank": rank,
            "reason": reason.strip(),
            "confidence": p.confidence if name else "low",
        })
    pain_score = result.pain_score if (sells or pains) else 0
    pain_reason = result.pain_reason or ("No pain evidence found" if not pain_score else "")
    return rows, pain_score, pain_reason
