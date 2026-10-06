"""Pinterest — API v5 핀 생성 (허브-스포크: 첫 번째 카드 + 티저 캡션)."""
from __future__ import annotations

import base64

import requests

from .base import Publisher

API = "https://api.pinterest.com/v5"


class PinterestPublisher(Publisher):
    name = "pinterest"
    env_suffixes = ["TOKEN", "BOARD_ID"]

    def _publish(self, lang, content, card_paths, creds):
        with open(card_paths[0], "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        caption = content["teaser_caption"]  # 허브-스포크: 첫 카드 + 티저 캡션
        r = requests.post(
            f"{API}/pins",
            headers={"Authorization": f"Bearer {creds['TOKEN']}"},
            json={
                "board_id": creds["BOARD_ID"],
                "title": caption[:100],
                "description": caption[:480],  # Pinterest 본문 500자 제한 대비
                "media_source": {
                    "source_type": "image_base64",
                    "content_type": "image/png",
                    "data": img_b64,
                },
            },
            timeout=60,
        )
        r.raise_for_status()
        return {"platform": self.name, "lang": lang, "status": "published", "id": r.json().get("id")}
