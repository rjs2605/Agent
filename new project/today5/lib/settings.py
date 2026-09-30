"""Settings saved from the website (Settings tab), stored in the `settings` table.
Values saved on the website win; otherwise the .env / Vercel environment value is used."""
import threading
import time

from config import (ICP, PRODUCT, SMALL_COMPANY_MAX_STAFF, SMALL_COMPANY_ROLES, TARGET_ROLES, env)
from lib.db import DBError, db

DEFAULTS = {
    "integrations": {
        "ai_primary": "",                # gemini | groq  (the other one is the fallback)
        "gemini_key": "", "gemini_key_backup": "", "gemini_model": "",
        "groq_key": "", "groq_key_backup": "", "groq_model": "",
        "search_primary": "",            # tavily | jina  (the other one is the fallback)
        "tavily_key": "", "tavily_key_backup": "",
        "jina_key": "",                  # used by the website reader and Jina Search
    },
    "target": {
        "product": PRODUCT,
        "description": ICP["description"],
        "industries": ICP["industries"],
        "min_staff": ICP["min_staff"],
        "max_staff": ICP["max_staff"],
        "roles": TARGET_ROLES,
        "small_roles": SMALL_COMPANY_ROLES,
        "small_max_staff": SMALL_COMPANY_MAX_STAFF,
    },
    "automation": {
        "daily_enabled": True,
        "run_time": "08:00",      # daily run time, IST (HH:MM)
        "paused_all": False,
        "refresh_limit": 5,       # researched companies re-checked per daily run
        "ai_block_until": None,   # set when every AI provider is at its limit
    },
}

ENV_KEYS = {
    "ai_primary": "AI_PRIMARY", "search_primary": "SEARCH_PRIMARY",
    "gemini_key": "GEMINI_API_KEY", "gemini_key_backup": "GEMINI_API_KEY_BACKUP", "gemini_model": "GEMINI_MODEL",
    "groq_key": "GROQ_API_KEY", "groq_key_backup": "GROQ_API_KEY_BACKUP", "groq_model": "GROQ_MODEL",
    "tavily_key": "TAVILY_API_KEY", "tavily_key_backup": "TAVILY_API_KEY_BACKUP",
    "jina_key": "JINA_API_KEY",
}
MODEL_DEFAULTS = {"gemini_model": "gemini-flash-latest", "groq_model": "llama-3.3-70b-versatile",
                  "ai_primary": "gemini", "search_primary": "tavily"}
SECRET_FIELDS = {"gemini_key", "gemini_key_backup", "groq_key", "groq_key_backup",
                 "tavily_key", "tavily_key_backup", "jina_key"}

_cache = {}
_lock = threading.Lock()
TTL = 15


def section(name):
    with _lock:
        hit = _cache.get(name)
        if hit and time.monotonic() - hit[0] < TTL:
            return dict(hit[1])
    merged = dict(DEFAULTS[name])
    try:
        rows = db().select("settings", key=f"eq.{name}")
        if rows and isinstance(rows[0].get("value"), dict):
            merged.update({k: v for k, v in rows[0]["value"].items() if k in DEFAULTS[name]})
    except DBError:
        pass  # settings table not created yet -> defaults
    with _lock:
        _cache[name] = (time.monotonic(), merged)
    return dict(merged)


def save(name, values):
    current = section(name)
    current.update({k: v for k, v in values.items() if k in DEFAULTS[name]})
    db().upsert("settings", {"key": name, "value": current}, on_conflict="key")
    with _lock:
        _cache.pop(name, None)
    return current


def integration(field):
    """Key or model: website value, else environment value, else default."""
    return (section("integrations").get(field) or env(ENV_KEYS[field]) or MODEL_DEFAULTS.get(field, "")).strip()


def integration_source(field):
    if section("integrations").get(field):
        return "website"
    if env(ENV_KEYS[field]):
        return "environment"
    return "default" if field in MODEL_DEFAULTS else "missing"


def mask(value):
    return "" if not value else ("•" * 8 + value[-4:])


def target():
    return section("target")


def automation():
    return section("automation")
