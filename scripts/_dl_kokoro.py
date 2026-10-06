"""Kokoro-82M 모델 다운로드 — 이어받기(Resume) + 다중 미러."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent / "models"
BASE.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("kokoro-v1.0.onnx", [
        "https://hf-mirror.com/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/onnx/model.onnx",
        "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/onnx/model.onnx",
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    ]),
    ("voices-v1.0.bin", [
        "https://hf-mirror.com/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/voices-v1.0.bin",
        "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/voices-v1.0.bin",
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
    ]),
]

TIMEOUT = (30, 120)


def head_size(url: str) -> int:
    try:
        r = requests.head(url, allow_redirects=True, timeout=30)
        n = int(r.headers.get("content-length", 0))
        return n
    except Exception:  # noqa: BLE001
        return 0


def download(name: str, urls: list[str]) -> bool:
    dest = BASE / name
    part = dest.with_suffix(".part")
    for url in urls:
        total = head_size(url)
        print(f"[try ] {name} <- {url} (total {total/1e6:.0f} MB)", flush=True)
        for attempt in range(12):  # 끊기면 이어받기 재시도
            got = part.stat().st_size if part.exists() else 0
            if total and got >= total:
                break
            headers = {"Range": f"bytes={got}-"} if got else {}
            try:
                with requests.get(url, headers=headers, stream=True, timeout=TIMEOUT) as r:
                    if r.status_code not in (200, 206):
                        print(f"  [http {r.status_code}] 다음 미러로", flush=True)
                        break
                    with open(part, "ab") as f:
                        for chunk in r.iter_content(1 << 20):
                            if not chunk:
                                break
                            f.write(chunk)
                            got += len(chunk)
                    if total:
                        print(f"  {got/1e6:.0f}/{total/1e6:.0f} MB", end="\r", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  [retry {attempt+1}] {type(e).__name__}: {str(e)[:80]}", flush=True)
                time.sleep(3)
                continue
        else:
            continue
        if part.exists() and part.stat().st_size > 1_000_000:
            if total and part.stat().st_size < total * 0.98:
                print(f"\n  [warn] 크기 미달 {part.stat().st_size}/{total}", flush=True)
                continue
            part.replace(dest)
            print(f"\n[ok  ] {name} {dest.stat().st_size/1e6:.1f} MB", flush=True)
            return True
    return False


for nm, us in TARGETS:
    dest = BASE / nm
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"[skip] {nm} ({dest.stat().st_size/1e6:.1f} MB)")
        continue
    if not download(nm, us):
        print(f"[ERR ] {nm} 실패", flush=True)
        sys.exit(1)

print("DONE", flush=True)
