"""Threads — Threads API 텍스트 게시물 (300자 이내 단일 완결 글)."""
from __future__ import annotations

import requests

from .base import Publisher

API = "https://graph.threads.net/v1.0"


class ThreadsPublisher(Publisher):
    name = "threads"
    env_prefix_override = "THREADS"
    env_suffixes = ["USER_ID", "TOKEN"]

    def _publish(self, lang, content, card_paths, creds):
        uid, token = creds["USER_ID"], creds["TOKEN"]
        r = requests.post(f"{API}/{uid}/threads", data={
            "media_type": "TEXT",
            "text": content["threads_text"],
            "access_token": token,
        }, timeout=30)
        r.raise_for_status()
        creation_id = r.json()["id"]

        r = requests.post(f"{API}/{uid}/threads_publish", data={
            "creation_id": creation_id, "access_token": token,
        }, timeout=30)
        r.raise_for_status()
        return {"platform": self.name, "lang": lang, "status": "published", "id": r.json().get("id")}
