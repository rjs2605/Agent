"""Supabase (PostgreSQL) via its REST API. Server-side only: uses the secret key."""
import threading

import httpx

from config import env


class DBError(Exception):
    pass


class DB:
    def __init__(self):
        url = env("SUPABASE_URL")
        key = env("SUPABASE_SECRET_KEY")
        if not url or not key:
            raise DBError("SUPABASE_URL / SUPABASE_SECRET_KEY missing in .env.local")
        headers = {"apikey": key, "Content-Type": "application/json"}
        if key.startswith("eyJ"):  # legacy service_role JWT
            headers["Authorization"] = f"Bearer {key}"
        self.client = httpx.Client(base_url=url.rstrip("/") + "/rest/v1", headers=headers, timeout=30)

    @staticmethod
    def _check(r):
        if r.status_code >= 400:
            raise DBError(f"{r.status_code}: {r.text[:300]}")

    def select(self, table, **filters):
        """select('scores', company_id='eq.<id>', order='created_at.desc', limit=1)"""
        params = {"select": "*"}
        params.update({k: str(v) for k, v in filters.items()})
        r = self.client.get(f"/{table}", params=params)
        self._check(r)
        return r.json()

    def insert(self, table, rows, ignore_duplicates_on=None):
        prefer = "return=representation"
        params = {}
        if ignore_duplicates_on:
            prefer += ",resolution=ignore-duplicates"
            params["on_conflict"] = ignore_duplicates_on
        r = self.client.post(f"/{table}", json=rows, params=params, headers={"Prefer": prefer})
        self._check(r)
        return r.json()

    def upsert(self, table, rows, on_conflict):
        r = self.client.post(f"/{table}", json=rows, params={"on_conflict": on_conflict},
                             headers={"Prefer": "return=representation,resolution=merge-duplicates"})
        self._check(r)
        return r.json()

    def delete(self, table, **filters):
        if not filters:
            raise DBError("refusing to delete without a filter")
        r = self.client.delete(f"/{table}", params=filters, headers={"Prefer": "return=representation"})
        self._check(r)
        return r.json()

    def update(self, table, values, **filters):
        r = self.client.patch(f"/{table}", json=values, params=filters, headers={"Prefer": "return=representation"})
        self._check(r)
        return r.json()


_db = None
_lock = threading.Lock()


def db():
    global _db
    with _lock:
        if _db is None:
            _db = DB()
        return _db
