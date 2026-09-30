"""AI analysis: extract facts (with sources) and write the company brief."""
import json
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from lib import settings
from lib.ai import GROUNDING_RULE, generate_json
from lib.signals import Change
from lib.util import norm_url

FACT_KEYS = [
    "what_they_sell", "customers_industry", "size_hint", "locations", "funding",
    "open_roles", "tech_tools", "leaders", "recent_launches", "pain_points",
]


# ---------- models ----------

class Fact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: str
    source_url: Optional[str] = None
    date: Optional[str] = None
    confidence: Optional[str] = None

    @field_validator("value", mode="before")
    @classmethod
    def _str(cls, v):
        return str(v) if v is not None else v


class Facts(BaseModel):
    model_config = ConfigDict(extra="ignore")
    what_they_sell: list[Fact] = []
    customers_industry: list[Fact] = []
    size_hint: list[Fact] = []
    locations: list[Fact] = []
    funding: list[Fact] = []
    open_roles: list[Fact] = []
    open_roles_count: Optional[int] = None
    tech_tools: list[Fact] = []
    leaders: list[Fact] = []
    recent_launches: list[Fact] = []
    pain_points: list[Fact] = []

    @field_validator(*FACT_KEYS, mode="before")
    @classmethod
    def _list(cls, v):
        if v is None:
            return []
        if isinstance(v, dict):
            v = [v]
        return [x for x in v if isinstance(x, dict) and x.get("value") not in (None, "", "null")]


class Line(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str
    source_url: Optional[str] = None


class Brief(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: list[Line] = []
    what_they_do: list[Line] = []
    size_locations_funding: list[Line] = []
    recent_news: list[Line] = []
    hiring: list[Line] = []
    pain_points: list[Line] = []
    opening_angle: list[Line] = []
    risks_unknowns: list[Line] = []

    @field_validator("*", mode="before")
    @classmethod
    def _list(cls, v):
        if v is None:
            return []
        if isinstance(v, (dict, str)):
            v = [v]
        return [({"text": x} if isinstance(x, str) else x) for x in v if x]


BRIEF_SECTIONS = [
    ("summary", "One-line summary"),
    ("what_they_do", "What they do + who they sell to"),
    ("size_locations_funding", "Size, locations, funding"),
    ("recent_news", "Recent news / changes"),
    ("hiring", "Hiring signals"),
    ("pain_points", "Likely pain points"),
    ("opening_angle", "Best angle to open the conversation"),
    ("risks_unknowns", "Risks / unknowns"),
]


# ---------- sources ----------

def build_sources(pages, news, manual_text=None):
    """Returns (prompt_text, allowed) where allowed maps normalized url -> original url."""
    parts, allowed = [], {}
    for label, page in pages.items():
        parts.append(f"=== SOURCE ({label} page of company website) source_url: {page['url']}\n{page['text']}")
        allowed[norm_url(page["url"])] = page["url"]
    for item in news or []:
        if not item.get("url"):
            continue
        parts.append(
            f"=== SOURCE (news) source_url: {item['url']} published: {item.get('published_date') or 'unknown'}\n"
            f"{item.get('title') or ''}\n{item.get('content') or ''}"
        )
        allowed[norm_url(item["url"])] = item["url"]
    if manual_text:
        parts.append(f"=== SOURCE (older company info pasted by user) source_url: manual:old-info\n{manual_text}")
        allowed["manual:old-info"] = "manual:old-info"
    return "\n\n".join(parts), allowed


# ---------- facts only (used for pasted old info) ----------

FACTS_SHAPE = """{"what_they_sell":[{"value":"...","source_url":"...","date":null}],
 "customers_industry":[], "size_hint":[], "locations":[], "funding":[],
 "open_roles":[], "open_roles_count":null, "tech_tools":[],
 "leaders":[{"value":"Full Name - Title","source_url":"...","date":null}],
 "recent_launches":[], "pain_points":[]}"""

FACT_RULES = f"""RULES: {GROUNDING_RULE}
- source_url must be copied exactly from the "source_url:" of the SOURCE the fact came from.
- If a thing is not found, use an empty list [] (open_roles_count: null).
- date: the date the fact refers to, or the news "published" date, as YYYY-MM-DD; null if not shown.
- If two sources give different values for the same thing (employee count, funding), include BOTH items.
- pain_points: problems this company likely has that our product could solve (high support volume,
  hiring support agents, many customers, several languages, fast growth). Cite the source text you reasoned from."""


def extract_facts(company_name, sources_text):
    prompt = f"""You research companies for a B2B sales team. We sell {settings.target()["product"]}.
Company: {company_name}

{FACT_RULES}

Return JSON in exactly this shape: {FACTS_SHAPE}

SOURCES:
{sources_text}
"""
    return generate_json(prompt, Facts)


# ---------- one call: facts + brief + signal/noise changes ----------

class Analysis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    facts: Facts = Facts()
    brief: Brief = Brief()
    changes: list[Change] = []

    @field_validator("facts", "brief", mode="before")
    @classmethod
    def _obj(cls, v):
        return v or {}

    @field_validator("changes", mode="before")
    @classmethod
    def _list(cls, v):
        return v or []


def slim_facts(resolved):
    if not resolved:
        return None
    return {k: [{"value": i["value"], "source_url": i["source_url"], "date": i["date"]} for i in v["items"]]
            for k, v in resolved.items() if isinstance(v, dict) and "items" in v}


def analyze_all(company_name, sources_text, old_facts):
    prompt = f"""You research companies for a B2B sales team. We sell {settings.target()["product"]}.
Company: {company_name}
Do THREE things using only the SOURCES below (and OLD FACTS for part C).

A) "facts": extract facts.
{FACT_RULES}

B) "brief": answer "What should I know before approaching {company_name}?" in fixed sections.
- Every line needs source_url copied exactly from a SOURCE. Short, plain sentences. Put dates in recent_news.
- summary: exactly one line. risks_unknowns: missing/uncertain things (source_url may be null here only).

C) "changes": sales triggers.
- Compare OLD FACTS (earlier snapshot) with the facts you found now; list every real difference.
  If OLD FACTS is null (first research), skip the comparison.
- Also list each news SOURCE as a change.
- SIGNAL (is_signal=true): funding, new leader, hiring spike, new product, new location, big customer win, pricing change.
- NOISE (is_signal=false): blog post, design/text change, footer, cookie banner, minor edits, unrelated or old news.
- type: funding | hiring | leader | product | expansion | customer_win | pricing | other.
- source_url: copied exactly from the SOURCE (or OLD FACTS) it came from. event_date: YYYY-MM-DD if shown, else null.

Return JSON in exactly this shape:
{{"facts": {FACTS_SHAPE},
 "brief": {{"summary":[{{"text":"...","source_url":"..."}}], "what_they_do":[], "size_locations_funding":[],
   "recent_news":[], "hiring":[], "pain_points":[], "opening_angle":[], "risks_unknowns":[]}},
 "changes": [{{"type":"funding","is_signal":true,"description":"Raised $10M Series A led by X","source_url":"...","event_date":"2026-09-01"}}]}}

OLD FACTS: {json.dumps(old_facts, ensure_ascii=False)}

SOURCES:
{sources_text}
"""
    return generate_json(prompt, Analysis)


def clean_brief(brief, allowed):
    """Keep only lines whose source is a page/news actually read (risks may have no source)."""
    out = {}
    for key, _title in BRIEF_SECTIONS:
        lines = []
        for line in getattr(brief, key):
            src = allowed.get(norm_url(line.source_url)) if line.source_url else None
            if src or key == "risks_unknowns":
                lines.append({"text": line.text, "source_url": src})
        out[key] = lines[:1] if key == "summary" else lines
    return out
