"""Login: one username + password from the environment (APP_USERNAME / APP_PASSWORD).
The session is a signed cookie, so it works on Vercel without a session store."""
import base64
import hashlib
import hmac
import time

from config import env

COOKIE = "lp_session"
MAX_AGE = 7 * 24 * 3600  # stay logged in for 7 days


def configured():
    return bool(env("APP_USERNAME") and env("APP_PASSWORD"))


def _secret():
    raw = f"{env('APP_USERNAME')}|{env('APP_PASSWORD')}|{env('SUPABASE_SECRET_KEY', '')}|{env('CRON_SECRET', '')}"
    return hashlib.sha256(raw.encode()).digest()


def check_login(username, password):
    if not configured():
        return False
    ok_user = hmac.compare_digest((username or "").encode(), env("APP_USERNAME").encode())
    ok_pass = hmac.compare_digest((password or "").encode(), env("APP_PASSWORD").encode())
    return ok_user and ok_pass


def make_token():
    exp = str(int(time.time()) + MAX_AGE)
    payload = f"{env('APP_USERNAME')}|{exp}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def valid_token(token):
    if not token or not configured():
        return False
    try:
        user, exp, sig = base64.urlsafe_b64decode(token.encode()).decode().rsplit("|", 2)
    except Exception:
        return False
    good = hmac.new(_secret(), f"{user}|{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and exp.isdigit() and int(exp) > time.time()


def token_from_cookie_header(header):
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return None


def cookie_header(token, secure, clear=False):
    attrs = f"{COOKIE}={'' if clear else token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={0 if clear else MAX_AGE}"
    return attrs + ("; Secure" if secure else "")
