"""Kokoro 보이스 목록 확인 (HF voices 폴더 + 로컬 bin 키)."""
from __future__ import annotations

import json
from pathlib import Path

import requests

for host in ("https://hf-mirror.com", "https://huggingface.co"):
    try:
        r = requests.get(f"{host}/api/models/hexgrad/Kokoro-82M/tree/main/voices", timeout=30)
        r.raise_for_status()
        names = [x["path"] for x in r.json() if x["type"] == "file"]
        print(f"[{host}] {len(names)} files")
        print(", ".join(sorted(names)))
        break
    except Exception as e:  # noqa: BLE001
        print(f"[{host}] FAIL {type(e).__name__}: {str(e)[:120]}")

p = Path(__file__).resolve().parent.parent / "models" / "voices-v1.0.bin"
if p.exists():
    import numpy as np
    v = np.load(p)
    keys = sorted(v.keys())
    print(f"\n[local voices-v1.0.bin] {len(keys)}")
    print(", ".join(keys))
    print("\nprefix groups:", sorted({k.split('_')[0] for k in keys}))
