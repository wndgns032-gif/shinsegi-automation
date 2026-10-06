"""Telegram Channel — Bot API 사진 그룹 + 티저 캡션 (허브-스포크: 앞 2장 + IG 유도)."""
from __future__ import annotations

import json

import requests

from .base import Publisher


class TelegramPublisher(Publisher):
    name = "telegram"
    env_suffixes = ["BOT_TOKEN", "CHAT_ID"]

    def _publish(self, lang, content, card_paths, creds):
        token, chat_id = creds["BOT_TOKEN"], creds["CHAT_ID"]
        api = f"https://api.telegram.org/bot{token}"

        files, media = {}, []
        handles = []
        try:
            for i, path in enumerate(card_paths[:2]):  # 티저: 첫 2장만 노출
                key = f"file{i}"
                handles.append(open(path, "rb"))
                files[key] = handles[-1]
                media.append({"type": "photo", "media": f"attach://{key}"})
            r = requests.post(f"{api}/sendMediaGroup",
                              data={"chat_id": chat_id, "media": json.dumps(media)},
                              files=files, timeout=60)
            r.raise_for_status()
        finally:
            for h in handles:
                h.close()

        # 캡션은 별도 메시지로 (4096자 제한, 사진 캡션 1024자 제한 회피)
        r = requests.post(f"{api}/sendMessage",
                          data={"chat_id": chat_id, "text": content["teaser_caption"]}, timeout=30)
        r.raise_for_status()
        return {"platform": self.name, "lang": lang, "status": "published",
                "id": str(r.json()["result"]["message_id"])}
