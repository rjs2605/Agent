"""AI helper: send a prompt, get JSON back, validate it with pydantic.
Main provider Gemini; if Gemini fails or hits its limit, Groq takes over automatically."""
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from config import GEMINI_MIN_INTERVAL, env
from lib import settings

GROQ_URL = "https://api.groq.com/openai/v1"
GROQ_MIN_INTERVAL = float(env("GROQ_MIN_INTERVAL", "2"))
GROQ_MAX_CHARS = int(env("GROQ_MAX_CHARS", "24000"))  # free-tier token-per-minute friendly
LIMIT_PAUSE = timedelta(minutes=10)                       # wait this long when every provider is at its limit

GROUNDING_RULE = (
    "Use ONLY the text given. Every fact must include source_url. "
    "If not found, write null. Do not guess."
)


class AIError(Exception):
    """AI could not produce a usable answer."""


class AILimitError(AIError):
    """Every AI provider is at its rate/daily limit (or overloaded). Retry later."""


class ProviderError(Exception):
    def __init__(self, msg, limit=False):
        super().__init__(msg)
        self.limit = limit


_locks = {"gemini": threading.Lock(), "groq": threading.Lock()}
_last = {"gemini": 0.0, "groq": 0.0}
_gemini_clients = {}


def _throttle(name, interval):
    with _locks[name]:
        wait = interval - (time.monotonic() - _last[name])
        if wait > 0:
            time.sleep(wait)
        _last[name] = time.monotonic()


# ---------- Gemini ----------

def _gemini_client(key):
    if key not in _gemini_clients:
        _gemini_clients[key] = genai.Client(api_key=key)
    return _gemini_clients[key]


def _gemini(prompt, key, model):
    for attempt in range(2):
        _throttle("gemini", GEMINI_MIN_INTERVAL)
        try:
            res = _gemini_client(key).models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
            )
            return res.text or ""
        except errors.APIError as e:
            code = getattr(e, "code", None)
            if code in (500, 503) and attempt == 0:
                time.sleep(3)
                continue
            if code in (429, 500, 503):
                raise ProviderError("busy or daily limit reached", limit=True) from e
            if code == 404:
                raise ProviderError(f"model '{model}' not found - pick another in Settings") from e
            if code in (400, 401, 403):
                raise ProviderError("key rejected - check it in Settings") from e
            raise ProviderError(f"error {code}") from e
        except httpx.HTTPError as e:
            raise ProviderError("network error", limit=True) from e
    raise ProviderError("busy", limit=True)


# ---------- Groq (OpenAI-compatible) ----------

def _shrink(prompt, max_chars):
    """Keep the instructions; trim each SOURCE block evenly so the prompt fits."""
    if len(prompt) <= max_chars:
        return prompt
    head, sep, rest = prompt.partition("SOURCES:")
    if not sep:
        return prompt[:max_chars]
    blocks = rest.split("\n=== SOURCE")
    budget = max(2000, max_chars - len(head) - 200)
    per = max(300, budget // max(1, len(blocks)))
    return head + sep + "\n=== SOURCE".join(b[:per] for b in blocks)


def _groq(prompt, key, model):
    _throttle("groq", GROQ_MIN_INTERVAL)
    try:
        r = httpx.post(
            f"{GROQ_URL}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "You reply with valid JSON only."},
                    {"role": "user", "content": _shrink(prompt, GROQ_MAX_CHARS)},
                ],
            },
            timeout=90,
        )
    except httpx.HTTPError as e:
        raise ProviderError("network error", limit=True) from e
    if r.status_code in (429, 500, 502, 503):
        raise ProviderError("busy or daily limit reached", limit=True)
    if r.status_code == 413:
        raise ProviderError("prompt too large for this model", limit=True)
    if r.status_code in (401, 403):
        raise ProviderError("key rejected - check it in Settings")
    if r.status_code == 404 or (r.status_code == 400 and "model" in r.text.lower()):
        raise ProviderError(f"model '{model}' not available - pick another in Settings")
    if r.status_code >= 400:
        raise ProviderError(f"error {r.status_code}")
    return r.json()["choices"][0]["message"]["content"] or ""


# ---------- routing ----------

def providers():
    """Order: primary provider (main key, backup key), then the other provider (main key, backup key)."""
    get = settings.integration
    gemini = [("Gemini", k, lambda p, k=k: _gemini(p, k, get("gemini_model")))
              for k in dict.fromkeys([get("gemini_key"), get("gemini_key_backup")]) if k]
    groq = [("Groq", k, lambda p, k=k: _groq(p, k, get("groq_model")))
            for k in dict.fromkeys([get("groq_key"), get("groq_key_backup")]) if k]
    chain = groq + gemini if get("ai_primary") == "groq" else gemini + groq
    out, seen = [], {}
    for name, _k, fn in chain:  # label backup keys so errors are clear
        seen[name] = seen.get(name, 0) + 1
        out.append((name if seen[name] == 1 else f"{name} (backup key)", fn))
    return out


def blocked_until():
    v = settings.automation().get("ai_block_until")
    if not v:
        return None
    t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return t if t > datetime.now(timezone.utc) else None


def _call_any(prompt):
    if blocked_until():
        raise AILimitError("AI limit reached on every provider. Research continues automatically later.")
    chain = providers()
    if not chain:
        raise AIError("No AI key set. Add a Gemini or Groq key in Settings → Integrations.")
    problems, all_limited = [], True
    for name, fn in chain:
        try:
            return fn(prompt)
        except ProviderError as e:
            problems.append(f"{name}: {e}")
            all_limited = all_limited and e.limit
    if all_limited:
        until = datetime.now(timezone.utc) + LIMIT_PAUSE
        try:
            settings.save("automation", {"ai_block_until": until.isoformat()})
        except Exception:
            pass
        raise AILimitError("AI limit reached (" + "; ".join(problems) + "). Research continues automatically later.")
    raise AIError("AI failed - " + "; ".join(problems))


def _parse(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(text)


def generate_json(prompt, model_cls):
    """Call the AI chain, validate against model_cls. Retries once on bad JSON, then raises AIError."""
    last_error = None
    for _ in range(2):
        text = _call_any(prompt)
        try:
            return model_cls.model_validate(_parse(text))
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
    raise AIError(f"AI returned unusable data twice ({str(last_error)[:120]})")


# ---------- Settings → Integrations "Test" buttons ----------

def test_gemini(key, model):
    try:
        names = sorted(m.name.removeprefix("models/") for m in _gemini_client(key).models.list()
                       if "flash" in m.name or "pro" in m.name)
    except Exception as e:
        return {"ok": False, "message": f"Key rejected or network error: {str(e)[:120]}"}
    try:
        _gemini('Return JSON {"ok": true}', key, model)
        return {"ok": True, "message": f"Works with model {model}", "models": names}
    except ProviderError as e:
        return {"ok": False, "message": f"Key works, but model '{model}': {e}", "models": names}


def test_groq(key, model):
    try:
        r = httpx.get(f"{GROQ_URL}/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"Network error: {e}"}
    if r.status_code != 200:
        return {"ok": False, "message": "Key rejected" if r.status_code in (401, 403) else f"Error {r.status_code}"}
    names = sorted(m["id"] for m in r.json().get("data", []))
    try:
        _groq('Return JSON {"ok": true}', key, model)
        return {"ok": True, "message": f"Works with model {model}", "models": names}
    except ProviderError as e:
        return {"ok": False, "message": f"Key works, but model '{model}': {e}", "models": names}
