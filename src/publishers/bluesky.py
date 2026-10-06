"""Bluesky — AT Protocol 텍스트 게시 (300자 제한, Threads 텍스트 재사용)."""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from .base import Publisher

BSKY = "https://bsky.social"


class BlueskyPublisher(Publisher):
    name = "bluesky"
    env_suffixes = ["HANDLE", "APP_PASSWORD"]

    def _publish(self, lang, content, card_paths, creds):
        s = requests.post(f"{BSKY}/xrpc/com.atproto.server.createSession", json={
            "identifier": creds["HANDLE"], "password": creds["APP_PASSWORD"],
        }, timeout=30)
        s.raise_for_status()
        token = s.json()["accessJwt"]

        r = requests.post(
            f"{BSKY}/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "repo": creds["HANDLE"],
                "collection": "app.bsky.feed.post",
                "record": {
                    "$type": "app.bsky.feed.post",
                    "text": content["threads_text"][:300],
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "langs": [lang],
                },
            },
            timeout=30,
        )
        r.raise_for_status()
        return {"platform": self.name, "lang": lang, "status": "published", "id": r.json().get("uri")}

    def fetch_metrics(self, lang):
        creds = self.credentials(lang)
        if not all(creds.values()):
            return None
        r = requests.get(f"{BSKY}/xrpc/app.bsky.feed.getAuthorFeed",
                         params={"actor": creds["HANDLE"], "limit": 20}, timeout=30)
        r.raise_for_status()
        today = datetime.now(timezone.utc).date().isoformat()
        m = {"views": 0, "likes": 0, "comments": 0, "shares": 0, "saves": 0}
        for item in r.json().get("feed", []):
            rec = item.get("post", {})
            if not rec.get("indexedAt", "").startswith(today):
                continue
            m["likes"] += rec.get("likeCount", 0)
            m["comments"] += rec.get("replyCount", 0)
            m["shares"] += rec.get("repostCount", 0)
        return m
