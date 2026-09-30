"""LeadPulse - web server (Python standard library only).
Local:  python app.py  ->  http://localhost:8000
Vercel: api/index.py routes every request to the same Handler.
"""
import json
import logging
import mimetypes
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import env  # noqa: E402
from lib import ai, auth, automation, pipeline, research, settings, views  # noqa: E402
from lib.db import DBError, db  # noqa: E402
from lib.util import domain_of, normalize_website  # noqa: E402

WEB = Path(__file__).resolve().parent / "web"
PAGES = {"/": "index.html", "/companies": "companies.html", "/settings": "settings.html", "/how-it-works": "how.html"}
PUBLIC_API = {"/api/login", "/api/cron/daily"}
ID = r"([0-9a-f-]{36})"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def name_from_domain(website):
    first = domain_of(website).split(".")[0]
    return first.replace("-", " ").title()


def settings_payload():
    integ = {}
    for field in settings.DEFAULTS["integrations"]:
        value = settings.integration(field)
        integ[field] = {
            "value": settings.mask(value) if field in settings.SECRET_FIELDS else value,
            "set": bool(value),
            "source": settings.integration_source(field),
        }
    auto = settings.automation()
    return {
        "integrations": integ,
        "target": settings.target(),
        "automation": {**auto, "schedule": automation.schedule_text(),
                       "next_run": automation.next_run_at().isoformat(),
                       "runner": "Vercel (checked when the app is opened + daily Vercel Cron)" if pipeline.SERVERLESS
                                 else "this computer (while python app.py is running)",
                       "tick_url": "/api/cron/daily"},
        "runs": automation.history(),
        "serverless": pipeline.SERVERLESS,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logging.info("%s %s", self.command, self._path())

    # ---- helpers ----
    def _send(self, status, body, ctype, extra_headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra_headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status=200, extra_headers=()):
        self._send(status, json.dumps(data, default=str).encode(), "application/json", extra_headers)

    def _file(self, path):
        if not path.is_file():
            return self._json({"error": "not found"}, 404)
        self._send(200, path.read_bytes(), mimetypes.guess_type(str(path))[0] or "application/octet-stream")

    def _redirect(self, to):
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _path(self):
        """Request path. On Vercel every request is rewritten to /api/index?__path=<original path>."""
        u = urlparse(self.path)
        original = parse_qs(u.query).get("__path")
        path = original[0].split("?")[0] if original else u.path
        return "/" + path.strip("/") if path.strip("/") else "/"

    def _query(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items() if k != "__path"}
        original = parse_qs(u.query).get("__path")
        if original and "?" in original[0]:  # query kept inside __path by some rewrites
            q.update({k: v[0] for k, v in parse_qs(original[0].split("?", 1)[1]).items()})
        return q

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except json.JSONDecodeError:
            return {}

    def _logged_in(self):
        return auth.valid_token(auth.token_from_cookie_header(self.headers.get("Cookie")))

    def _secure(self):
        return pipeline.SERVERLESS or self.headers.get("X-Forwarded-Proto") == "https"

    def _safe(self, fn):
        try:
            fn()
        except DBError as e:
            msg = str(e)
            if "PGRST205" in msg or "does not exist" in msg:
                msg = "Database tables are missing. Run schema.sql / migration.sql in Supabase → SQL Editor."
            self._json({"error": f"Database: {msg}"}, 500)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:  # keep the server alive
            logging.exception("request failed")
            self._json({"error": str(e)[:300]}, 500)

    def _guard(self, path):
        """True if the request may continue; otherwise the response is already sent."""
        if path == "/login" or path.startswith("/static/") or path in PUBLIC_API:
            return True
        if self._logged_in():
            return True
        if path.startswith("/api/"):
            self._json({"error": "Please log in"}, 401)
        else:
            self._redirect("/login")
        return False

    # ---- GET ----
    def do_GET(self):
        self._safe(self._get)

    def _get(self):
        path = self._path()
        if not self._guard(path):
            return
        if path == "/login":
            return self._redirect("/") if self._logged_in() else self._file(WEB / "login.html")
        if path in PAGES:
            return self._file(WEB / PAGES[path])
        if re.fullmatch(r"/companies/" + ID, path):
            return self._file(WEB / "company.html")
        if path.startswith("/static/"):
            f = (WEB / path.removeprefix("/static/")).resolve()
            return self._file(f) if WEB in f.parents else self._json({"error": "not found"}, 404)

        if path == "/api/me":
            return self._json({"user": env("APP_USERNAME"), "serverless": pipeline.SERVERLESS})
        if path == "/api/companies":
            companies = views.companies_list()
            return self._json({"companies": companies, "summary": views.summary(companies)})
        m = re.fullmatch(r"/api/companies/" + ID, path)
        if m:
            detail = views.company_detail(m.group(1))
            return self._json(detail) if detail else self._json({"error": "not found"}, 404)
        if path == "/api/today":
            return self._json(views.today_five())
        if path == "/api/export":
            ids = [i for i in (self._query().get("ids") or "").split(",") if i]
            return self._json(views.export_rows(ids or None))
        if path == "/api/settings":
            return self._json(settings_payload())
        if path == "/api/cron/daily":
            secret = env("CRON_SECRET")
            if not secret or self.headers.get("Authorization") != f"Bearer {secret}":
                return self._json({"error": "Unauthorized"}, 401)
            return self._json(automation.tick())
        return self._json({"error": "not found"}, 404)

    # ---- DELETE ----
    def do_DELETE(self):
        self._safe(self._delete)

    def _delete(self):
        path = self._path()
        if not self._guard(path):
            return
        m = re.fullmatch(r"/api/companies/" + ID, path)
        if m:
            views.delete_company(m.group(1))
            return self._json({"deleted": True})
        return self._json({"error": "not found"}, 404)

    # ---- POST ----
    def do_POST(self):
        self._safe(self._post)

    def _post(self):
        path = self._path()
        if not self._guard(path):
            return
        body = self._body()

        if path == "/api/login":
            if not auth.configured():
                return self._json({"error": "Login is not set up: add APP_USERNAME and APP_PASSWORD "
                                            "to .env.local (local) or Vercel Environment Variables."}, 400)
            if not auth.check_login(body.get("username"), body.get("password")):
                return self._json({"error": "Wrong username or password"}, 401)
            cookie = auth.cookie_header(auth.make_token(), self._secure())
            return self._json({"ok": True}, extra_headers=[("Set-Cookie", cookie)])
        if path == "/api/logout":
            return self._json({"ok": True}, extra_headers=[("Set-Cookie", auth.cookie_header("", self._secure(), clear=True))])

        if path == "/api/companies":
            raw = body.get("urls") or []
            if isinstance(raw, str):
                raw = re.split(r"[\s,;]+", raw)
            cleaned, invalid = [], []
            for u in raw:
                if not str(u).strip():
                    continue
                n = normalize_website(str(u))
                (cleaned if n else invalid).append(n or str(u).strip())
            cleaned = list(dict.fromkeys(cleaned))
            status = "queued" if body.get("research") else "new"
            added = []
            for i in range(0, len(cleaned), 500):  # big CSV files go in chunks
                chunk = [{"website": w, "name": name_from_domain(w), "status": status} for w in cleaned[i:i + 500]]
                added += db().insert("companies", chunk, ignore_duplicates_on="website")
            return self._json({"added": len(added), "duplicates": len(cleaned) - len(added), "invalid": invalid})

        m = re.fullmatch(r"/api/companies/" + ID + r"/research", path)
        if m:
            cid = m.group(1)
            pipeline.enqueue(cid, first=True)
            if pipeline.SERVERLESS:  # no background worker: try to research it now, inside this request
                return self._json(pipeline.run_next())
            return self._json({"state": "queued"})
        m = re.fullmatch(r"/api/companies/" + ID + r"/pause", path)
        if m:
            db().update("companies", {"paused": bool(body.get("paused"))}, id=f"eq.{m.group(1)}")
            return self._json({"paused": bool(body.get("paused"))})
        m = re.fullmatch(r"/api/companies/" + ID + r"/old-info", path)
        if m:
            text = (body.get("text") or "").strip()
            if len(text) < 30:
                raise ValueError("Paste at least a few lines of older company info")
            snap = pipeline.save_old_info(m.group(1), text)
            return self._json({"snapshot_id": snap["id"]})

        if path == "/api/research-all":
            only_new = bool(body.get("only_new"))
            ids = [c["id"] for c in db().select("companies", select="id,status,paused")
                   if not c.get("paused") and c["status"] not in ("queued", "researching")
                   and (not only_new or c["status"] in ("new", "failed"))]
            for i in range(0, len(ids), 200):
                chunk = ids[i:i + 200]
                db().update("companies", {"status": "queued", "last_error": None},
                            id=f"in.({','.join(chunk)})")
            return self._json({"queued": len(ids)})
        if path == "/api/run-next":
            if not pipeline.SERVERLESS:
                return self._json({"state": "worker", "company_id": None})
            return self._json(pipeline.run_next())
        if path == "/api/pause-all":
            settings.save("automation", {"paused_all": bool(body.get("paused"))})
            return self._json({"paused_all": bool(body.get("paused"))})
        if path == "/api/actions":
            if not body.get("company_id"):
                raise ValueError("company_id is required")
            return self._json(views.record_action(body["company_id"], body.get("action")))

        if path == "/api/settings/integrations":
            values = {}
            for field, v in body.items():
                if field not in settings.DEFAULTS["integrations"]:
                    continue
                v = (v or "").strip() if isinstance(v, str) else v
                if field in settings.SECRET_FIELDS:
                    if v == "__clear__":
                        values[field] = ""
                    elif v and not v.startswith("•"):
                        values[field] = v  # empty or masked = keep the saved key
                else:
                    values[field] = v
            settings.save("integrations", values)
            settings.save("automation", {"ai_block_until": None})  # new keys -> try again right away
            return self._json(settings_payload())
        if path == "/api/settings/target":
            t = settings.DEFAULTS["target"]
            values = {}
            for k in t:
                if k not in body:
                    continue
                v = body[k]
                if isinstance(t[k], list):
                    v = [x.strip() for x in (v if isinstance(v, list) else str(v).split(",")) if x.strip()]
                elif isinstance(t[k], int):
                    v = int(v)
                else:
                    v = str(v).strip()
                values[k] = v
            if "min_staff" in values and "max_staff" in values and values["min_staff"] > values["max_staff"]:
                raise ValueError("Min staff must be less than max staff")
            settings.save("target", values)
            return self._json(settings_payload())
        if path == "/api/settings/automation":
            values = {}
            if "daily_enabled" in body:
                values["daily_enabled"] = bool(body["daily_enabled"])
            if "run_time" in body:
                if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", str(body["run_time"]).strip()):
                    raise ValueError("Run time must look like 08:00")
                h, m = str(body["run_time"]).strip().split(":")
                values["run_time"] = f"{int(h):02d}:{m}"
            if "refresh_limit" in body:
                values["refresh_limit"] = max(0, min(100, int(body["refresh_limit"])))
            settings.save("automation", values)
            return self._json(settings_payload())
        if path == "/api/integrations/test":
            return self._json(self._test(body))
        if path == "/api/automation/tick":
            return self._json(automation.tick())
        if path == "/api/automation/run":
            return self._json(automation.run("manual"))
        return self._json({"error": "not found"}, 404)

    def _test(self, body):
        get = settings.integration
        p = body.get("provider")
        typed = (body.get("key") or "").strip()
        key = typed if typed and not typed.startswith("•") else None
        model = (body.get("model") or "").strip()
        if p in ("gemini", "gemini_backup"):
            k = key or get("gemini_key" if p == "gemini" else "gemini_key_backup")
            return ai.test_gemini(k, model or get("gemini_model")) if k else {"ok": False, "message": "No key"}
        if p in ("groq", "groq_backup"):
            k = key or get("groq_key" if p == "groq" else "groq_key_backup")
            return ai.test_groq(k, model or get("groq_model")) if k else {"ok": False, "message": "No key"}
        if p in ("tavily", "tavily_backup"):
            k = key or get("tavily_key" if p == "tavily" else "tavily_key_backup")
            return research.test_tavily(k) if k else {"ok": False, "message": "No key"}
        if p == "jina":
            return research.test_jina(key or get("jina_key"))
        if p == "jina_search":
            return research.test_jina_search(key or get("jina_key"))
        raise ValueError("unknown provider")


def reset_stuck():
    """If the server stopped mid-run, put that company back in the queue."""
    try:
        db().update("companies", {"status": "queued"}, status="eq.researching")
    except Exception as e:
        logging.warning("could not reset stuck companies: %s", e)


if __name__ == "__main__":
    port = int(env("PORT", "8000"))
    if not auth.configured():
        print("WARNING: APP_USERNAME / APP_PASSWORD are not set in .env.local - nobody can log in.")
    reset_stuck()
    pipeline.start_worker()
    automation.start_local_scheduler()
    print(f"LeadPulse running at http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
