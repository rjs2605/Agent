"""Trigger detection (task 6): the AI compares old vs new snapshot facts + news (inside analyze.analyze_all);
this module validates sources, dates and duplicates."""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from lib.util import norm_url, parse_date, today

SIGNAL_TYPES = ["funding", "hiring", "leader", "product", "expansion", "customer_win", "pricing", "other"]


class Change(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["funding", "hiring", "leader", "product", "expansion", "customer_win", "pricing", "other"] = "other"
    is_signal: bool
    description: str
    source_url: Optional[str] = None
    event_date: Optional[str] = None

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, v):
        v = str(v or "other").lower().replace(" ", "_")
        return v if v in SIGNAL_TYPES else "other"


class Changes(BaseModel):
    changes: list[Change] = []

    @field_validator("changes", mode="before")
    @classmethod
    def _list(cls, v):
        return v or []


def process(changes, news, allowed, existing_signals):
    """Checks the AI's changes (made in analyze.analyze_all) and returns rows for the signals table."""
    news_dates = {norm_url(n["url"]): parse_date(n.get("published_date")) for n in news or [] if n.get("url")}
    seen = {(norm_url(s.get("source_url")), s.get("type"), (s.get("description") or "").strip().lower())
            for s in existing_signals}
    seen_urls_types = {(norm_url(s.get("source_url")), s.get("type")) for s in existing_signals}

    rows = []
    for c in changes:
        src = allowed.get(norm_url(c.source_url)) if c.source_url else None
        if not src:
            continue  # no source -> not shown
        key = norm_url(src)
        is_news = key in news_dates
        if is_news and (key, c.type) in seen_urls_types:
            continue  # same news already recorded on an earlier run
        if (key, c.type, c.description.strip().lower()) in seen:
            continue
        event = news_dates.get(key) if is_news else None
        event = event or parse_date(c.event_date) or today()
        if event > today():
            event = today()
        rows.append({
            "type": c.type,
            "is_signal": c.is_signal,
            "description": c.description.strip(),
            "source_url": src,
            "event_date": event.isoformat(),
        })
    return rows
