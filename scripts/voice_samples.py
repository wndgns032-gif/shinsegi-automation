"""음성 샘플 생성 — src.tts 실제 체인으로 각 언어 후보 음성을 mp3로 뽑는다.

사용: python scripts/voice_samples.py [언어 ...]   (인자 없으면 전체)
결과: data/voice_samples/sample__<lang>__<voice>.mp3
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from src import tts  # noqa: E402

OUT = BASE / "data" / "voice_samples"
OUT.mkdir(parents=True, exist_ok=True)

TEXTS = {
    "en": "It is not that you failed. You just found one more way that does not work. "
          "The bag you paid the most for, you carried twice. The cheap one goes everywhere.",
    "ko": "실패한 게 아니에요. 안 되는 방법을 하나 더 알아낸 거예요. "
          "제일 비싼 가방은 두 번 들고 다녔고, 싼 가방은 매일 들고 다녔어요.",
    "zh-cn": "不是你失败了，只是又找到了一种行不通的方法。最贵的包只背过两次，便宜的包天天背。",
    "fr": "Tu n'as pas échoué. Tu as trouvé une façon de plus qui ne marche pas. "
          "Le sac le plus cher, porté deux fois. Le sac à dix euros, tous les jours.",
}

PLAN = [
    ("ko", None), ("ko", "F1"), ("ko", "F3"),
    ("en", None), ("en", "af_bella"),
    ("zh-cn", None),
    ("fr", None), ("fr", "ff_siwis"),
]


def duration(path: Path) -> float:
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        ff = "ffmpeg"
    r = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True, errors="ignore")
    import re
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr)
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def main() -> None:
    langs = [a for a in sys.argv[1:] if not a.startswith("-")] or None
    for lang, voice in PLAN:
        if langs and lang not in langs:
            continue
        out = OUT / f"sample__{lang}__{voice or 'default'}.mp3"
        try:
            tts.synth(TEXTS[lang], lang, out, voice=voice)
            print(f"[ok  ] {lang}/{voice or 'default'}: {duration(out):.1f}s -> {out.name}")
        except Exception as e:  # noqa: BLE001
            print(f"[fail] {lang}/{voice or 'default'}: {type(e).__name__}: {str(e)[:160]}")


if __name__ == "__main__":
    main()
