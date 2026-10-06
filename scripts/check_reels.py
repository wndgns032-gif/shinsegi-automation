"""새 TTS 엔진으로 리일스 1개를 만들어 파이프라인을 검증한다 (발행 없음)."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from src import reels  # noqa: E402
from src import tts  # noqa: E402

SCRIPT = ("앞을 막는 것이 곧 길이 된다. 마르쿠스 아우렐리우스는 이렇게 말했어요. "
          "제일 비싼 가방은 두 번 들고 다녔어요. 비 올까봐, 바닥에 놓을까봐 겁이 났죠. "
          "막은 게 가격이 아니라 망가질까 봐 하는 마음이었어요. "
          "오늘, 나중에 쓰려고 남겨둔 물건 하나를 꺼내서 그냥 써 보세요.")

cards = sorted((BASE / "data" / "preview" / "2026-09-21_0134" / "ko").glob("card_*.png"),
               key=lambda x: int(x.stem.split("_")[1]))
out = BASE / "data" / "preview" / "reels_test"
out.mkdir(parents=True, exist_ok=True)

print("voice:", tts.voice_for("ko"))
audio = tts.synth(SCRIPT, "ko", out / "voice_ko.mp3")
mp4 = reels.build_reels(cards, audio, out / "reels_test_ko.mp4")
print(f"OK: {mp4} ({mp4.stat().st_size // 1024}KB)")
