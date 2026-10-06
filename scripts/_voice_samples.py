"""음성 후보 샘플 생성 — 사용자가 직접 들어보고 고를 수 있게."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import tts  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "voice_samples"
OUT.mkdir(parents=True, exist_ok=True)

SCRIPTS = {
    "ko": "실패에서 배운 건, 절대 실패하지 않는다는 게 아니에요. 다시 일어나는 속도가 빨라진다는 거예요. 오늘 넘어졌다면, 그건 늦어진 게 아니라 연습한 겁니다.",
    "en": "What you learn from failure is not that you never fall. It is that you get up faster. If you fell today, you are not behind. You are practicing.",
    "zh-cn": "失败教给你的，不是从此不再跌倒，而是站起来变得更快。今天摔倒了，不代表你落后了，只是又练习了一次。",
    "fr": "Ce que l'échec t'apprend, ce n'est pas de ne plus jamais tomber. C'est de te relever plus vite. Si tu es tombé aujourd'hui, tu n'es pas en retard. Tu t'entraînes.",
}

CANDS = {
    "ko": ["ko-KR-SunHiNeural", "ko-KR-HyunsuMultilingualNeural"],
    "en": ["en-US-EmmaMultilingualNeural", "en-US-AvaMultilingualNeural", "en-US-AvaNeural"],
    "zh-cn": ["zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural"],
    "fr": ["fr-FR-VivienneMultilingualNeural", "fr-FR-DeniseNeural"],
}

lines = []
for lang, text in SCRIPTS.items():
    for i, voice in enumerate(CANDS[lang], start=1):
        out = OUT / f"{lang}_{i}_{voice}.mp3"
        try:
            tts.synth(text, lang, out)
            size = out.stat().st_size
            lines.append(f"OK   {lang} #{i} {voice}  {size//1024}KB")
        except Exception as e:  # noqa: BLE001
            lines.append(f"FAIL {lang} #{i} {voice}  {e}")
(OUT / "_result.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
