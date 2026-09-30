"""Small helpers: dates, URLs, staff-count parsing."""
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse


def today():
    return date.today()


def parse_date(value):
    """Return a date from ISO / RFC-2822 / 'Sep 2026' style strings, else None."""
    if not value:
        return None
    if isinstance(value, date):
        return value if not isinstance(value, datetime) else value.date()
    s = str(value).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(s).date()
    except (TypeError, ValueError, IndexError):
        pass
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%B %Y", "%b %Y", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def days_ago(d):
    return (today() - d).days if d else None


def normalize_website(raw):
    """'Example.com/about/' -> 'https://example.com'. Returns None if not a URL."""
    s = (raw or "").strip().strip('"').strip("'")
    if not s:
        return None
    if not re.match(r"^https?://", s, re.I):
        s = "https://" + s
    p = urlparse(s)
    host = (p.hostname or "").lower()
    if "." not in host or " " in host:
        return None
    return f"https://{host}"


def norm_url(u):
    """For comparing URLs: lower host, no trailing slash, no fragment."""
    if not u:
        return ""
    u = u.strip()
    if u.startswith("manual:"):
        return u
    p = urlparse(u if re.match(r"^https?://", u, re.I) else "https://" + u)
    host = (p.hostname or "").lower().removeprefix("www.")
    path = p.path.rstrip("/")
    q = f"?{p.query}" if p.query else ""
    return f"{host}{path}{q}"


def domain_of(u):
    p = urlparse(u if re.match(r"^https?://", u or "", re.I) else "https://" + (u or ""))
    return (p.hostname or "").lower().removeprefix("www.")


def parse_staff(text):
    """Best guess of employee count from text like '200-500 employees', '1,200+ staff', '2k people'."""
    if not text:
        return None
    t = str(text).lower().replace(",", "")
    num = r"(\d+(?:\.\d+)?)\s*(k)?"
    m = re.search(num + r"\s*(?:-|to|–)\s*" + num + r"\s*\+?\s*(?:employees|staff|people|team|members|strong)", t)
    if m:
        a = float(m.group(1)) * (1000 if m.group(2) else 1)
        b = float(m.group(3)) * (1000 if m.group(4) else 1)
        return int((a + b) / 2)
    m = re.search(num + r"\s*\+?\s*(?:employees|staff|people|team members|members|strong|employee)", t)
    if m:
        return int(float(m.group(1)) * (1000 if m.group(2) else 1))
    m = re.search(r"(?:team of|employs|headcount of|headcount:?)\s*" + num, t)
    if m:
        return int(float(m.group(1)) * (1000 if m.group(2) else 1))
    return None


def number_signature(text):
    """Set of numbers in a value, used to tell 'same fact' from 'conflicting fact'."""
    return frozenset(re.findall(r"\d+(?:\.\d+)?", str(text or "").replace(",", "")))


def now_iso():
    return datetime.now(timezone.utc).isoformat()
