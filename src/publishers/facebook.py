"""Facebook Page — Graph API 사진 묶음 게시 (허브-스포크: 앞 2장 티저 + IG 유도)."""
from __future__ import annotations

import requests

from .base import Publisher

GRAPH = "https://graph.facebook.com/v21.0"


class FacebookPublisher(Publisher):
    name = "facebook"
    env_prefix_override = "FB"
    env_suffixes = ["PAGE_ID", "TOKEN"]

    def _publish(self, lang, content, card_paths, creds):
        page_id, token = creds["PAGE_ID"], creds["TOKEN"]

        media_ids = []
        for path in card_paths[:2]:  # 티저: 첫 2장만 노출
            with open(path, "rb") as f:
                r = requests.post(
                    f"{GRAPH}/{page_id}/photos",
                    data={"published": "false", "access_token": token},
                    files={"source": f},
                    timeout=60,
                )
            r.raise_for_status()
            media_ids.append(r.json()["id"])

        data = {"message": content["teaser_caption"], "access_token": token}
        for i, mid in enumerate(media_ids):
            data[f"attached_media[{i}]"] = f'{{"media_fbid":"{mid}"}}'
        r = requests.post(f"{GRAPH}/{page_id}/feed", data=data, timeout=30)
        r.raise_for_status()
        return {"platform": self.name, "lang": lang, "status": "published", "id": r.json().get("id")}
