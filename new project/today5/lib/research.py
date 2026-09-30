"""Research with fallbacks (all chosen in Settings → Integrations):
- Website reader: Jina Reader -> direct page fetch (no key needed)
- Web/news search: primary (Tavily or Jina Search) -> the other one; Tavily main key -> Tavily backup key"""
import html
import re
from urllib.parse import quote

import httpx

from config import PAGE_CHAR_LIMIT
from lib import settings
from lib.util import domain_of

JINA = "https://r.jina.ai/"
JINA_SEARCH = "https://s.jina.ai/"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
SOFT_404 = r"404|not found|page not found|doesn.t exist|no longer available"
TAVILY = "https://api.tavily.com/search"

# (label, paths to try in order; first that works is kept)
PAGE_GROUPS = [
    ("home", [""]),
    ("about", ["/about", "/about-us"]),
    ("careers", ["/careers", "/jobs"]),
    ("blog", ["/blog", "/news"]),
    ("pricing", ["/pricing"]),
]


class ResearchError(Exception):
    pass


def _looks_ok(text):
    if not text or len(text.strip()) < 200:
        return False
    title = re.search(r"^Title:\s*(.*)$", text, re.M)
    return not (title and re.search(SOFT_404, title.group(1), re.I))  # "soft 404": error page sent as 200


def _read_jina(url):
    headers = {}
    key = settings.integration("jina_key")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        r = httpx.get(JINA + url, headers=headers, timeout=60, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or re.search(r"Target URL returned error [45]\d\d", r.text):
        return None
    return r.text


def _read_direct(url):
    """Fallback reader: fetch the HTML ourselves and keep the visible text."""
    try:
        r = httpx.get(url, headers={"User-Agent": BROWSER_UA}, timeout=30, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
        return None
    raw = r.text
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    title = html.unescape(m.group(1)).strip() if m else ""
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return f"Title: {title}\n\nURL Source: {url}\n\n{text}"


def read_page(url):
    for reader in (_read_jina, _read_direct):
        text = reader(url)
        if _looks_ok(text):
            return text[:PAGE_CHAR_LIMIT]
    return None


def _body(text):
    """Page text without Jina's header lines (for duplicate detection)."""
    text = re.sub(r"^(Title|URL Source|Published Time|Warning):.*$", "", text, flags=re.M)
    return re.sub(r"https?://\S+", "", text).strip()


def read_site(website):
    """Returns {label: {"url": ..., "text": ...}} for pages that exist."""
    pages = {}
    seen_bodies = set()
    for label, paths in PAGE_GROUPS:
        for path in paths:
            url = website + path
            text = read_page(url)
            if not text:
                continue
            body = _body(text)[:2000]
            if body in seen_bodies:  # redirected back to a page we already have
                break
            seen_bodies.add(body)
            pages[label] = {"url": url, "text": text}
            break
    return pages


def name_from_home(pages, website):
    home = pages.get("home", {}).get("text", "")
    m = re.search(r"^Title:\s*(.+)$", home, re.M)
    if m:
        title = re.split(r"\s[|\-–—:]\s", m.group(1))[0]
        title = re.sub(r"[®™©]", "", title).strip()
        if 1 < len(title) <= 60:
            return title
    return domain_of(website).split(".")[0].capitalize()


def _tavily(key, query, topic, max_results, include_domains):
    body = {"query": query, "topic": topic, "max_results": max_results, "search_depth": "basic"}
    if include_domains:
        body["include_domains"] = include_domains
    try:
        r = httpx.post(TAVILY, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=40)
    except httpx.HTTPError as e:
        raise ResearchError(f"Tavily network error: {e}") from e
    if r.status_code >= 400:
        raise ResearchError(f"Tavily error {r.status_code}")
    return [{"title": i.get("title"), "url": i.get("url"), "content": (i.get("content") or "")[:1200],
             "published_date": i.get("published_date")} for i in r.json().get("results", [])]


def _jina_search(key, query, max_results):
    try:
        r = httpx.get(JINA_SEARCH + "?q=" + quote(query), timeout=60,
                      headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                               "X-Respond-With": "no-content"})
    except httpx.HTTPError as e:
        raise ResearchError(f"Jina Search network error: {e}") from e
    if r.status_code >= 400:
        raise ResearchError(f"Jina Search error {r.status_code}")
    data = r.json().get("data") or []
    return [{"title": i.get("title"), "url": i.get("url"),
             "content": (i.get("description") or i.get("content") or "")[:1200],
             "published_date": i.get("date") or i.get("publishedTime")} for i in data[:max_results]]


def web_search(query, topic="general", max_results=5, include_domains=None):
    """Tries each configured search provider in order until one answers."""
    get = settings.integration
    tavily = [("Tavily", lambda k=k: _tavily(k, query, topic, max_results, include_domains))
              for k in dict.fromkeys([get("tavily_key"), get("tavily_key_backup")]) if k]
    jina = [("Jina Search", lambda: _jina_search(get("jina_key"), query, max_results))] if get("jina_key") else []
    chain = jina + tavily if get("search_primary") == "jina" else tavily + jina
    if not chain:
        raise ResearchError("No search key set (Settings → Integrations)")
    problems = []
    for name, fn in chain:
        try:
            return fn()
        except ResearchError as e:
            problems.append(f"{name}: {e}")
    raise ResearchError("All search providers failed - " + "; ".join(problems))


tavily_search = web_search  # old name


def search_news(name):
    """News is a bonus: if Tavily fails (no key, limit), research continues with the website only."""
    try:
        return web_search(f"{name} funding OR hiring OR launch OR expansion", topic="news", max_results=5)
    except ResearchError:
        return []


def test_tavily(key):
    try:
        r = httpx.post(TAVILY, json={"query": "test", "max_results": 1},
                       headers={"Authorization": f"Bearer {key}"}, timeout=30)
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"Network error: {e}"}
    if r.status_code == 200:
        return {"ok": True, "message": "Works"}
    return {"ok": False, "message": "Key rejected" if r.status_code in (401, 403) else f"Error {r.status_code}: {r.text[:100]}"}


def test_jina_search(key):
    if not key:
        return {"ok": False, "message": "Jina Search needs a Jina key"}
    try:
        res = _jina_search(key, "test", 1)
        return {"ok": True, "message": f"Works ({len(res)} result)"}
    except ResearchError as e:
        return {"ok": False, "message": str(e)}


def test_jina(key):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        r = httpx.get(JINA + "https://example.com", headers=headers, timeout=40)
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"Network error: {e}"}
    if r.status_code == 200:
        return {"ok": True, "message": "Works" + ("" if key else " (without a key, lower limit)")}
    return {"ok": False, "message": "Key rejected" if r.status_code in (401, 403) else f"Error {r.status_code}"}
