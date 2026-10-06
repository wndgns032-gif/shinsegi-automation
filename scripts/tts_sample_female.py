"""edge-tts 4개 언어 **여성 목소리** 샘플 생성 (말하는 투 스크립트).

무료 AI TTS 조사 결과 (2026-09-20):
- ElevenLabs: 무료 10k자/월, 상업 이용 금지 + 출처 표기 의무 → 탈락
- Google Cloud TTS: 월 100만자 무료지만 GCP 키 필요 + 중국 네트워크 접속 불가 → 탈락
- Kokoro-82M: 로컬 무료(Apache 2.0)지만 영어 중심, ko/fr 음성 없음 → 탈락
- **edge-tts: MS 신경망 음성(AI TTS), 무제한·무키·무가입, 이 PC에서 검증 완료 → 채택**

여성 음성 라인업 (전 언어 여성, 친근한 뉴스 전달 톤):
  ko: ko-KR-SunHiNeural   — 따뜻하고 자연스러운 여성
  en: en-US-JennyNeural   — 밝고 또렷한 여성 (검증된 대표 음성)
  zh: zh-CN-XiaoxiaoNeural — 중국어 대표 여성 음성
  fr: fr-FR-DeniseNeural  — 차분한 여성
"""
import asyncio
from pathlib import Path

import edge_tts

OUT = Path(__file__).resolve().parent.parent / "data" / "tts_samples"
OUT.mkdir(parents=True, exist_ok=True)

SAMPLES = {
    "ko": {
        "voice": "ko-KR-SunHiNeural",
        "text": "안녕하세요, 오늘의 한국 이야기예요. 요즘 샤인머스캣 가격이 진짜 뛰고 있거든요? 그런데 그 뒤에 농가들의 피땀어린 노력이 숨어 있었다는 사실, 알고 계셨나요? 자, 지금부터 카드로 보여드릴게요!",
    },
    "en": {
        "voice": "en-US-JennyNeural",
        "text": "Hi guys, here's today's story from Korea. Shine Muscat grape prices are going absolutely crazy right now. But did you know what farmers went through behind those perfect clusters? Let me walk you through the cards!",
    },
    "zh-cn": {
        "voice": "zh-CN-XiaoxiaoNeural",
        "text": "大家好，又到了今天的韩国新鲜事时间。最近阳光玫瑰葡萄的价格真的涨疯了。但你可能不知道，这背后藏着农户们多少年的辛苦付出。接下来就用卡片讲给你听！",
    },
    "fr": {
        "voice": "fr-FR-DeniseNeural",
        "text": "Bonjour à tous, voici l'histoire du jour en Corée. Le prix du Shine Muscat s'envole littéralement en ce moment. Mais ce que les agriculteurs ont enduré derrière ces grappes parfaites, vous ne l'imaginez pas. Je vous raconte tout dans les cartes !",
    },
}


async def synth(lang: str, voice: str, text: str) -> None:
    out = OUT / f"sample_female_{lang}.mp3"
    tts = edge_tts.Communicate(text, voice)
    await tts.save(str(out))
    print(f"{lang}: {out.name} ({out.stat().st_size // 1024} KB, {voice})")


async def main() -> None:
    for lang, s in SAMPLES.items():
        await synth(lang, s["voice"], s["text"])


if __name__ == "__main__":
    asyncio.run(main())
