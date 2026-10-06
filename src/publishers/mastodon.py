"""Mastodon — 텍스트 툿 (Threads 텍스트 재사용)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from .base import Publisher

KST = timezone(timedelta(hours=9))


class MastodonPublisher(Publisher):
    name = "mastodon"
    env_suffixes = ["BASE_URL", "TOKEN"]

    def _headers(self, creds):
        return {"Authorization": f"Bearer {creds['TOKEN']}"}

    def _publish(self, lang, content, card_paths, creds):
        base = creds["BASE_URL"].rstrip("/")
        r = requests.post(f"{base}/api/v1/statuses",
                          headers=self._headers(creds),
                          json={"status": content["threads_text"], "language": lang},
                          timeout=30)
        r.raise_for_status()
        return {"platform": self.name, "lang": lang, "status": "published", "id": r.json().get("id")}

    def fetch_metrics(self, lang):
        creds = self.credentials(lang)
        if not all(creds.values()):
            return None
        base = creds["BASE_URL"].rstrip("/")
        v = requests.get(f"{base}/api/v1/accounts/verify_credentials",
                         headers=self._headers(creds), timeout=30)
        v.raise_for_status()
        uid = v.json()["id"]
        r = requests.get(f"{base}/api/v1/accounts/{uid}/statuses",
                         headers=self._headers(creds), params={"limit": 20}, timeout=30)
        r.raise_for_status()
        today = datetime.now(KST).date().isoformat()
        m = {"views": 0, "likes": 0, "comments": 0, "shares": 0, "saves": 0}
        for st in r.json():
            if not st.get("created_at", "").startswith(today):
                continue
            m["likes"] += st.get("favourites_count", 0)
            m["comments"] += st.get("replies_count", 0)
            m["shares"] += st.get("reblogs_count", 0)
        return m
