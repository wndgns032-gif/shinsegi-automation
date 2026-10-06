"""Pollinations 묣료 이미지 접속 테스트 — 한 번만 실행."""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

import requests  # noqa: E402

REP = BASE / "_polli_report.txt"
lines: list[str] = []


def out(s: str) -> None:
    lines.append(s)


PROMPT = ("a quiet morning desk by the window, soft watercolor illustration, "
          "studio ghibli style, warm light, open notebook and a cup of tea, sharp focus")
url = ("https://image.pollinations.ai/prompt/" + requests.utils.quote(PROMPT)
       + "?width=1280&height=720&nologo=true&seed=1234&model=flux")

for attempt in (1, 2, 3):
    t0 = time.time()
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
        dt = time.time() - t0
        ct = r.headers.get("content-type", "")
        out(f"attempt{attempt}: HTTP {r.status_code} ct={ct} bytes={len(r.content)} {dt:.1f}s")
        if r.ok and "image" in ct and len(r.content) > 20000:
            dest = BASE / "_polli_test.jpg"
            dest.write_bytes(r.content)
            out(f"saved -> {dest}")
            break
    except Exception as e:  # noqa: BLE001
        out(f"attempt{attempt}: {type(e).__name__} {str(e)[:150]}")

REP.write_text("\n".join(lines), encoding="utf-8")
