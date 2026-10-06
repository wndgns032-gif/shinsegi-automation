"""한국어를 지원하는 Kokoro 계열 모델 검색."""
from __future__ import annotations

import requests

for host in ("https://hf-mirror.com", "https://huggingface.co"):
    try:
        r = requests.get(f"{host}/api/models", params={
            "search": "kokoro", "filter": "language:ko", "limit": 30, "full": "false"}, timeout=30)
        r.raise_for_status()
        print(f"[{host}] language:ko")
        for m in r.json():
            print(" -", m.get("modelId"), m.get("downloads"))
    except Exception as e:  # noqa: BLE001
        print(f"[{host}] FAIL {type(e).__name__}: {str(e)[:120]}")
    try:
        r = requests.get(f"{host}/api/models", params={
            "search": "kokoro korean", "limit": 20}, timeout=30)
        r.raise_for_status()
        print(f"[{host}] search 'kokoro korean'")
        for m in r.json():
            print(" -", m.get("modelId"), m.get("downloads"))
    except Exception as e:  # noqa: BLE001
        print(f"[{host}] FAIL2 {type(e).__name__}: {str(e)[:120]}")
    break
