"""오류 일지 — data/errors.log에 JSON 라인으로 누적."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))


def log_error(data_dir: Path, stage: str, message: str, detail: str = "") -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(KST).isoformat(timespec="seconds"),
        "stage": stage,
        "message": message,
        "detail": detail[:2000],
    }
    with open(data_dir / "errors.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
