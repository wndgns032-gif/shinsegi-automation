"""로컬 TTS 모델 다운로드 (이어받기 지원).

Kokoro-82M  : models/kokoro-v1.0.onnx, models/voices-v1.0.bin
Supertonic-3: models/supertonic-3/onnx/*, models/supertonic-3/voice_styles/*
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent / "models"
HOSTS = ["https://hf-mirror.com", "https://huggingface.co"]

KOKORO = [
    ("kokoro-v1.0.onnx", "onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/onnx/model.onnx", 326_000_000),
    ("voices-v1.0.bin", "onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/voices-v1.0.bin", 27_000_000),
]
SUPER_FILES = [
    "onnx/duration_predictor.onnx", "onnx/text_encoder.onnx", "onnx/tts.json",
    "onnx/unicode_indexer.json", "onnx/vector_estimator.onnx", "onnx/vocoder.onnx",
] + [f"voice_styles/{v}.json" for v in ("F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5")]


def fetch(url: str, dest: Path, min_size: int) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")  # 이어받기 파일 (예: kokoro-v1.0.part)
    for attempt in range(15):
        got = part.stat().st_size if part.exists() else 0
        if got >= min_size * 0.98 and dest.exists():
            return True
        try:
            headers = {"Range": f"bytes={got}-"} if got else {}
            with requests.get(url, headers=headers, stream=True, timeout=(30, 120)) as r:
                if r.status_code not in (200, 206):
                    print(f"   http {r.status_code} -> 미러 전환", flush=True)
                    return False
                with open(part, "ab") as f:
                    for chunk in r.iter_content(1 << 20):
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
        except Exception as e:  # noqa: BLE001
            print(f"   retry {attempt+1}: {type(e).__name__}", flush=True)
            time.sleep(2)
            continue
        if dest.exists() and part.stat().st_size >= min_size * 0.98:
            part.replace(dest)
            return True
        # 사이즈 확인용 HEAD
        try:
            total = int(requests.head(url, allow_redirects=True, timeout=30)
                        .headers.get("content-length", 0))
        except Exception:  # noqa: BLE001
            total = min_size
        if total and part.stat().st_size >= total * 0.98:
            part.replace(dest)
            return True
    return False


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    for name, path, size in KOKORO:
        dest = BASE / name
        if dest.exists() and dest.stat().st_size > size * 0.5:
            print(f"[skip] {name} {dest.stat().st_size/1e6:.0f}MB")
            continue
        print(f"[dl  ] {name}", flush=True)
        ok = False
        for h in HOSTS:
            if fetch(f"{h}/{path}", dest, size):
                ok = True
                break
        print(f"      -> {'OK' if ok else 'FAIL'} {dest.stat().st_size/1e6 if dest.exists() else 0:.0f}MB", flush=True)

    for rel in SUPER_FILES:
        dest = BASE / "supertonic-3" / rel
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"[skip] {rel}")
            continue
        print(f"[dl  ] {rel}", flush=True)
        ok = False
        for h in HOSTS:
            if fetch(f"{h}/Supertone/supertonic-3/resolve/main/{rel}", dest,
                     {"vector_estimator": 256_000_000, "vocoder": 101_000_000,
                      "text_encoder": 36_000_000}.get(Path(rel).stem, 100_000)):
                ok = True
                break
        print(f"      -> {'OK' if ok else 'FAIL'}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
