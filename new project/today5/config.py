"""Settings: reads .env.local and holds the ideal-customer config."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_env_file():
    path = ROOT / ".env.local"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def env(name, default=None):
    value = os.environ.get(name)
    return value if value else default


# ---- What we sell and who we sell to (change these to re-target the app) ----

PRODUCT = (
    "a customer-support automation tool: a shared helpdesk plus an AI chat agent "
    "that answers routine customer questions, so support teams handle more "
    "tickets without hiring more agents"
)

ICP = {
    "description": "Indian B2B or D2C companies with 50-1000 staff that run customer support or sales teams",
    "country": "India",
    "min_staff": 50,
    "max_staff": 1000,
    "industries": [
        "saas", "software", "d2c", "direct-to-consumer", "e-commerce", "ecommerce",
        "online store", "fintech", "payments", "lending", "wealth", "investing",
        "insurance", "edtech", "education", "healthtech", "health", "logistics",
        "delivery", "travel", "mobility", "rental", "subscription", "consumer",
        "retail", "fashion", "apparel", "beauty", "cosmetics", "personal care",
        "food", "beverage", "furniture", "jewellery", "jewelry", "marketplace",
        "real estate", "proptech", "hospitality", "telecom",
    ],
}

INDIA_WORDS = [
    "india", "bengaluru", "bangalore", "mumbai", "delhi", "gurugram", "gurgaon",
    "noida", "pune", "hyderabad", "chennai", "kolkata", "ahmedabad", "jaipur",
]

# Person to approach
TARGET_ROLES = [
    "Head of Customer Support", "Head of Customer Experience", "VP Customer Success",
    "Director of Customer Support", "VP Operations", "Head of Operations",
]
SMALL_COMPANY_ROLES = ["Founder", "Co-founder", "CEO"]
SMALL_COMPANY_MAX_STAFF = 50

# Sites treated as "directories/aggregators" in data reliability
DIRECTORY_DOMAINS = [
    "crunchbase.com", "tracxn.com", "linkedin.com", "glassdoor", "ambitionbox.com",
    "zaubacorp.com", "tofler.in", "owler.com", "zoominfo.com", "pitchbook.com",
    "wikipedia.org", "g2.com", "capterra", "justdial.com", "indeed.", "naukri.com",
]

# Pipeline limits
PAGE_CHAR_LIMIT = 8000
GEMINI_MIN_INTERVAL = float(env("GEMINI_MIN_INTERVAL", "4"))  # seconds between AI calls (free-tier friendly)
CRON_BATCH = int(env("CRON_BATCH", "3"))  # companies re-researched per daily run
