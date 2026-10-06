"""자연스러운 무료 TTS 후보 샘플 생성 — Supertonic 3 / Kokoro / Edge.

결과: data/voice_samples/<engine>__<lang>__<voice>.mp3 + _result.txt
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# HF 미러(중국/한국 네트워크 대응)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

OUT = ROOT / "data" / "voice_samples"
OUT.mkdir(parents=True, exist_ok=True)

TEXTS = {
    "en": "It is not that you failed. You just found one more way that does not work.",
    "ko": "실패한 게 아니에요. 안 되는 방법을 하나 더 알아낸 거예요.",
    "zh-cn": "不是你失败了，你只是又找到了一种行不通的方法。",
    "fr": "Tu n'as pas échoué. Tu as trouvé une façon de plus qui ne marche pas.",
}

lines: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    lines.append(msg)


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def to_mp3(src: Path, dst: Path) -> Path:
    r = subprocess.run(
        [ffmpeg(), "-y", "-i", str(src), "-c:a", "libmp3lame", "-b:a", "128k", str(dst)],
        capture_output=True, text=True, errors="ignore",
    )
    if r.returncode != 0 or not dst.exists():
        raise RuntimeError(f"mp3 변환 실패: {r.stderr[-200:]}")
    return dst


def dur(path: Path) -> float:
    r = subprocess.run(
        [ffmpeg(), "-i", str(path)], capture_output=True, text=True, errors="ignore")
    import re
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr)
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def supertonic_samples() -> None:
    log("=== Supertonic 3 (로컬·무제한·31개 언어) ===")
    try:
        from supertonic import TTS
        t0 = time.time()
        tts = TTS(auto_download=True)
        log(f"  로드 {time.time()-t0:.1f}s / sample_rate={tts.sample_rate} / voices={tts.voice_style_names}")
    except Exception as e:  # noqa: BLE001
        log(f"  Supertonic 실패: {type(e).__name__}: {str(e)[:300]}")
        return

    plan = [
        ("ko", "F1"), ("ko", "F2"), ("ko", "F3"),
        ("en", "F1"), ("en", "F2"),
        ("fr", "F1"), ("fr", "F2"),
    ]
    for lang, voice in plan:
        code = {"zh-cn": "zh"}.get(lang, lang)
        try:
            style = tts.get_voice_style(voice)
            t0 = time.time()
            wav, d = tts.synthesize(TEXTS[lang], voice_style=style, lang=code,
                                    total_steps=12, speed=0.95)
            wav_path = OUT / f"supertonic__{lang}__{voice}.wav"
            tts.save_audio(wav, str(wav_path))
            mp3 = to_mp3(wav_path, OUT / f"supertonic__{lang}__{voice}.mp3")
            wav_path.unlink(missing_ok=True)
            log(f"  {lang}/{voice}: {dur(mp3):.1f}s ({time.time()-t0:.1f}s 소요) -> {mp3.name}")
        except Exception as e:  # noqa: BLE001
            log(f"  {lang}/{voice} 실패: {type(e).__name__}: {str(e)[:200]}")


def kokoro_samples() -> None:
    log("=== Kokoro-82M (로컬·무제한) ===")
    model = ROOT / "models" / "kokoro-v1.0.onnx"
    voices = ROOT / "models" / "voices-v1.0.bin"
    if not model.exists() or not voices.exists():
        log(f"  모델 미완료: {model.name}={model.exists()}, {voices.name}={voices.exists()}")
        return
    try:
        import soundfile as sf
        from kokoro_onnx import Kokoro
        k = Kokoro(str(model), str(voices))
        log(f"  보이스 {len(k.get_voices())}개")
    except Exception as e:  # noqa: BLE001
        log(f"  Kokoro 로드 실패: {type(e).__name__}: {str(e)[:300]}")
        return

    def phonemize(text: str, lang: str) -> str:
        if lang == "ko":
            from misaki.ko import KOG2P
            g = KOG2P()
            return g(text)
        if lang == "zh-cn":
            from misaki.zh import ZHG2P
            g = ZHG2P()
            return g(text)[0]
        # en / fr 은 espeak 기반
        return k.tokenizer.phonemize(text, "en-us" if lang == "en" else "fr-fr")

    plan = [("en", "af_heart"), ("en", "af_bella"), ("zh-cn", "zf_xiaoxiao"),
            ("zh-cn", "zf_xiaoni"), ("fr", "ff_siwis")]
    for lang, voice in plan:
        if voice not in k.get_voices():
            log(f"  {voice} 없음")
            continue
        try:
            ph = phonemize(TEXTS[lang], lang)
            t0 = time.time()
            audio, sr = k.create(ph, voice=voice, speed=0.92, is_phonemes=True,
                                 sentence_pause=0.35, clause_pause=0.12)
            wav = OUT / f"kokoro__{lang}__{voice}.wav"
            sf.write(str(wav), audio, sr)
            mp3 = to_mp3(wav, OUT / f"kokoro__{lang}__{voice}.mp3")
            wav.unlink(missing_ok=True)
            log(f"  {lang}/{voice}: {dur(mp3):.1f}s ({time.time()-t0:.1f}s 소요) -> {mp3.name}")
        except Exception as e:  # noqa: BLE001
            log(f"  {lang}/{voice} 실패: {type(e).__name__}: {str(e)[:200]}")


def edge_samples() -> None:
    log("=== Edge TTS (현재 사용 중, 비교용) ===")
    import asyncio
    import edge_tts
    plan = [("ko", "ko-KR-SunHiNeural"), ("zh-cn", "zh-CN-XiaoxiaoNeural"),
            ("fr", "fr-FR-VivienneMultilingualNeural"), ("en", "en-US-EmmaMultilingualNeural")]
    for lang, voice in plan:
        try:
            wav = OUT / f"edge__{lang}.mp3"
            async def run():
                c = edge_tts.Communicate(TEXTS[lang], voice, rate="-4%", pitch="-2Hz")
                await c.save(str(wav))
            asyncio.run(run())
            log(f"  {lang}/{voice}: {dur(wav):.1f}s -> {wav.name}")
        except Exception as e:  # noqa: BLE001
            log(f"  {lang} 실패: {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    supertonic_samples()
    kokoro_samples()
    edge_samples()
    (OUT / "_result.txt").write_text("\n".join(lines), encoding="utf-8")
    log("DONE")
