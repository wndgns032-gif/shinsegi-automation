"""게시 어댑터 베이스 — 자격증명 없으면 자동 dry-run."""
from __future__ import annotations

import os
from pathlib import Path


class Publisher:
    name: str = ""
    env_prefix_override: str | None = None  # instagram -> IG, facebook -> FB
    env_suffixes: list[str] = []
    extra_env: list[str] = []  # 계정 무관 전역 변수 (예: PUBLIC_IMAGE_BASE_URL)

    def prefix(self, lang: str) -> str:
        p = self.env_prefix_override or self.name.upper()
        return f"{p}_{lang.upper().replace('-', '_')}"

    def credentials(self, lang: str) -> dict[str, str | None]:
        return {s: os.getenv(f"{self.prefix(lang)}_{s}") for s in self.env_suffixes}

    def missing(self, lang: str) -> list[str]:
        creds = self.credentials(lang)
        miss = [f"{self.prefix(lang)}_{s}" for s, v in creds.items() if not v]
        miss += [e for e in self.extra_env if not os.getenv(e)]
        return miss

    def publish(self, lang: str, content: dict, card_paths: list[Path]) -> dict:
        miss = self.missing(lang)
        if miss:
            return {"platform": self.name, "lang": lang, "status": "dry-run",
                    "detail": f"missing env: {', '.join(miss)}"}
        try:
            return self._publish(lang, content, card_paths, self.credentials(lang))
        except Exception as e:  # noqa: BLE001 - 플랫폼별 예외를 일지에 남기기 위한 최상위 포착
            return {"platform": self.name, "lang": lang, "status": "error", "detail": str(e)[:500]}

    def _publish(self, lang: str, content: dict, card_paths: list[Path], creds: dict) -> dict:
        raise NotImplementedError

    def fetch_metrics(self, lang: str) -> dict | None:
        """성과 지표 {views, likes, comments, shares, saves}. 미구현/실패 시 None."""
        return None
