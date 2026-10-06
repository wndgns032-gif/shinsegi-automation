"""edge-tts 4개 언어 목소리 샘플 생성 (말하는 투 스크립트 테스트)."""
import asyncio
import sys
from pathlib import Path

import edge_tts

OUT = Path(__file__).resolve().parent.parent / "data" / "tts_samples"
OUT.mkdir(parents=True, exist_ok=True)

SAMPLES = {
    "ko": {
        "voice": "ko-KR-InJoonNeural",
        "text": "안녕하세요, 오늘의 한국 이야기입니다. 요즘 샤인머스캣 가격이 크게 뛰고 있는데요, 그 뒤에는 농가들의 피땀어린 노력이 있었습니다. 자세한 이야기는 카드에서 확인해보세요!",
    },
    "en": {
        "voice": "en-US-GuyNeural",
        "text": "Hi, here's today's story from Korea. Shine Muscat grape prices are surging right now, but behind those price tags are farmers who spent years perfecting every cluster. The full story is in the cards, take a look!",
    },
    "zh-cn": {
        "voice": "zh-CN-YunxiNeural",
        "text": "大家好，今天继续聊韩国的新鲜事。阳光玫瑰葡萄的价格最近大涨，但背后是农户们多年的辛苦付出。详细内容请看卡片，别走开！",
    },
    "fr": {
        "voice": "fr-FR-DeniseNeural",
        "text": "Bonjour, voici l'histoire du jour venant de Corée. Le prix du Shine Muscat s'envole, mais derrière ces grappes parfaites se cachent des années d'efforts. Toute l'histoire est dans les cartes, jetez un œil !",
    },
}


async def synth(lang: str, voice: str, text: str) -> None:
    out = OUT / f"sample_{lang}.mp3"
    tts = edge_tts.Communicate(text, voice)
    await tts.save(str(out))
    print(f"{lang}: {out.name} ({out.stat().st_size // 1024} KB, {voice})")


async def main() -> None:
    for lang, s in SAMPLES.items():
        await synth(lang, s["voice"], s["text"])


if __name__ == "__main__":
    asyncio.run(main())
