"""자연스러운 AI 음성 합성 — 로컬·무제한 엔진 우선, 클라우드(edge) 폴백.

왜 바꿨나
---------
기존 Microsoft Edge 음성은 "낭독하는 기계" 느낌이 났다. 그래서 **로컬에서 무제한으로
돌아가는 최신 모델** 두 개를 붙였다. 글자 수 제한·요금·키가 아예 없다.

  · Kokoro-82M    (Apache 2.0, 82M, 24kHz) — 영어/중국어/프랑스어에 강함
  · Supertonic-3  (MIT/OpenRAIL-M, 99M, 44.1kHz, 31개 언어) — **한국어 포함**

엔진은 언어별로 가장 자연스러운 쪽을 우선 쓰고, 실패하면 다음 엔진으로 자동 폴백한다.
(모델 파일이 없거나 설치가 안 된 경우에도 edge-tts 로 안전하게 떨어진다)

자연스럽게 만드는 3요소
-----------------------
1) **음성 세대** — 최신 신경망 음성(전부 여성)
2) **속도** — 낭독용으로 살짝 느리게(0.92~0.95배)
3) **호흡** — 문장 사이 300ms 정적(엔진별 파라미터로 주입)
"""
from __future__ import annotations

import asyncio
import shutil
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
KOKORO_MODEL = MODELS / "kokoro-v1.0.onnx"
KOKORO_VOICES = MODELS / "voices-v1.0.bin"
SUPERTONIC_DIR = MODELS / "supertonic-3"

# ── 음성 프로필: 언어별 (엔진, 음성) 폴백 체인 ──────────────────────────────
# engine: kokoro | supertonic | edge
VOICE_PROFILES: dict[str, list[dict]] = {
    # 한국어: 무료 로컬에서 한국어가 되는 건 Supertonic-3 뿐이다 (여성 F1~F5)
    "ko": [
        {"engine": "supertonic", "voice": "F2", "lang": "ko", "speed": 0.95},
        {"engine": "edge", "voice": "ko-KR-SunHiNeural", "rate": "-4%", "pitch": "-2Hz"},
    ],
    "en": [
        {"engine": "kokoro", "voice": "af_heart", "lang": "en-us", "speed": 0.92},
        {"engine": "supertonic", "voice": "F1", "lang": "en", "speed": 0.95},
        {"engine": "edge", "voice": "en-US-EmmaMultilingualNeural", "rate": "-4%", "pitch": "-2Hz"},
    ],
    "zh-cn": [
        {"engine": "kokoro", "voice": "zf_xiaoxiao", "lang": "zh", "speed": 0.92},
        {"engine": "edge", "voice": "zh-CN-XiaoxiaoNeural", "rate": "-4%", "pitch": "-2Hz"},
    ],
    "fr": [
        {"engine": "supertonic", "voice": "F1", "lang": "fr", "speed": 0.95},
        {"engine": "kokoro", "voice": "ff_siwis", "lang": "fr-fr", "speed": 0.92},
        {"engine": "edge", "voice": "fr-FR-VivienneMultilingualNeural", "rate": "-4%", "pitch": "-2Hz"},
    ],
}

# 교체 후보 (사용자가 골라 바꿀 수 있게 상수로 보관)
ALT_VOICES: dict[str, list[str]] = {
    "ko": ["F1", "F2", "F3", "F4", "F5"],          # Supertonic 여성 5종
    "en": ["af_heart", "af_bella", "af_sarah", "af_nicole", "af_aoede", "bf_emma"],
    "zh-cn": ["zf_xiaoxiao", "zf_xiaoni", "zf_xiaobei", "zf_xiaoyi"],
    "fr": ["F1", "F2", "F3", "ff_siwis"],
}

_ALIAS = {"zh_cn": "zh-cn", "zh-CN": "zh-cn", "zh": "zh-cn"}
_SENT_END = "。．.．!?！？"
# 문장 사이 정적 길이. 로이 요청(2026-10-10): "한 문장이 끝나고 0.5초 뒤에 다음 문장".
# 기존 300ms 는 여운이 부족했고, 실측 무음 편차(80~780ms)가 컸다.
# 앞뒤 무음은 _silence_edges() 로 실측 제거하므로 여기 남는 값 = 최종 간격.
# 실측 결과 500ms 설정 시 600~700ms 가 나왔음(측정 임계가 잔여 잡음 포함) →
# 요청값 0.5초에 맞춰 380ms 로 보정. (2026-10-10 실측 반영)
_PAD_MS = 380
# 엔진이 합성 결과 앞뒤에 붙이는 고정 무음 — 언어별 실측값(2026-10-10).
#   Supertonic 계열(ko/fr) : 앞 0.46~0.68초 + 뒤 0.64~0.76초 → 길다
#   Kokoro 계열(en/zh)   : 앞 0.04초     + 뒤 0.08~0.14초   → 거의 없다
# 이걸 그대로 두면 문장 간격이 500ms + 엔진값(1.1~1.4초) = 2초까지 벌어진다.
# → 언어별로 잘라낸 뒤 pad(500ms) 만 남겨 간격을 정확히 맞춘다.
_TRIM_HEAD = {"supertonic": 0.62, "kokoro": 0.05, "edge": 0.0}
_TRIM_TAIL = {"supertonic": 0.68, "kokoro": 0.12, "edge": 0.0}

_kokoro = None
_supertonic = None


def profile_for(lang: str) -> list[dict]:
    key = _ALIAS.get(lang, lang)
    if key not in VOICE_PROFILES:
        raise ValueError(f"지원하지 않는 언어: {lang}")
    return VOICE_PROFILES[key]


def voice_for(lang: str) -> str:
    """현재 1순위 음성 라벨 (로그/호환용)."""
    p = profile_for(lang)[0]
    return f"{p['engine']}:{p['voice']}"


def split_sentences(text: str) -> list[str]:
    """문장 종결자 기준 분리. 너무 짧은 조각은 앞 문장에 붙인다."""
    parts: list[str] = []
    buf = ""
    for ch in text.strip():
        buf += ch
        if ch in _SENT_END or ch == "\n":
            parts.append(buf.strip())
            buf = ""
    if buf.strip():
        parts.append(buf.strip())

    merged: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if merged and len(p) < 12:
            merged[-1] = f"{merged[-1]} {p}"
        else:
            merged.append(p)
    return merged or [text.strip()]


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def _to_mp3(src: Path, out: Path) -> Path:
    if src.suffix.lower() == ".mp3" and src != out:
        src.replace(out)
        return out
    r = subprocess.run(
        [_ffmpeg_exe(), "-y", "-i", str(src), "-c:a", "libmp3lame", "-b:a", "128k", str(out)],
        capture_output=True, text=True, errors="ignore",
    )
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"mp3 변환 실패: {r.stderr[-300:]}")
    return out


# ── 엔진별 합성 ────────────────────────────────────────────────────────────
def _get_kokoro():
    global _kokoro
    if _kokoro is None:
        if not (KOKORO_MODEL.exists() and KOKORO_VOICES.exists()):
            raise RuntimeError("Kokoro 모델 파일 없음")
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
    return _kokoro


def _kokoro_phonemes(k, text: str, lang: str) -> str:
    """언어별 G2P — ko/zh 는 misaki, en/fr 은 espeak 계열.

    쉼표·마침표는 반드시 ASCII(. , ! ?)로 정규화한다 — Kokoro 어휘에는
    아스키 문장부호만 있고, 이 문자들이 문장 사이 호흡(pause) 기준이 된다.
    """
    if lang == "ko":
        from misaki.ko import KOG2P
        res = KOG2P()(text)
        ph = res[0] if isinstance(res, tuple) else res
    elif lang == "zh":
        from misaki.zh import ZHG2P
        res = ZHG2P()(text)
        ph = res[0] if isinstance(res, tuple) else res
    else:
        code = "en-us" if lang == "en-us" else lang
        ph = k.tokenizer.phonemize(text, code)
    for a, b in (("，", ","), ("。", "."), ("！", "!"), ("？", "?"),
                 ("、", ","), ("：", ","), ("；", ",")):
        ph = ph.replace(a, b)
    return ph


def _synth_kokoro(text: str, prof: dict, out: Path) -> Path:
    import soundfile as sf

    k = _get_kokoro()
    if prof["voice"] not in k.get_voices():
        raise RuntimeError(f"Kokoro 보이스 없음: {prof['voice']}")
    ph = _kokoro_phonemes(k, text, prof["lang"])
    audio, sr = k.create(
        ph, voice=prof["voice"], speed=prof.get("speed", 0.92), is_phonemes=True,
        sentence_pause=0.35, clause_pause=0.12,  # 문장 사이 호흡
    )
    wav = out.with_suffix(".wav")
    sf.write(str(wav), audio, sr)
    return _to_mp3(wav, out)


def _get_supertonic():
    global _supertonic
    if _supertonic is None:
        if not (SUPERTONIC_DIR / "onnx" / "tts.json").exists():
            raise RuntimeError("Supertonic 모델 파일 없음")
        import os
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from supertonic import TTS
        _supertonic = TTS(model="supertonic-3", model_dir=str(SUPERTONIC_DIR),
                          auto_download=False)
    return _supertonic


def _synth_supertonic(text: str, prof: dict, out: Path) -> Path:
    tts = _get_supertonic()
    style = tts.get_voice_style(prof["voice"])
    wav_arr, _ = tts.synthesize(
        text, voice_style=style, lang=prof["lang"],
        total_steps=12,                      # 8 기본 → 12로 올려 발음 안정감
        speed=prof.get("speed", 0.95),
        silence_duration=0.35,               # 문단 사이 호흡
    )
    wav = out.with_suffix(".wav")
    tts.save_audio(wav_arr, str(wav))
    return _to_mp3(wav, out)


def _synth_edge(text: str, prof: dict, out: Path, paced: bool = True) -> Path:
    import edge_tts

    rate = prof.get("rate", "-4%")
    pitch = prof.get("pitch", "-2Hz")
    voice = prof["voice"]
    out.parent.mkdir(parents=True, exist_ok=True)

    sentences = split_sentences(text) if paced else [text.strip()]
    if len(sentences) == 1:
        async def _one():
            await edge_tts.Communicate(sentences[0], voice, rate=rate, pitch=pitch).save(str(out))
        asyncio.run(_one())
        return out

    tmp_dir = out.parent / "_parts"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    try:
        for i, s in enumerate(sentences):
            p = tmp_dir / f"p{i}.mp3"

            async def _run(s=s, p=p):
                await edge_tts.Communicate(s, voice, rate=rate, pitch=pitch).save(str(p))
            asyncio.run(_run())
            parts.append(p)
        return _concat_with_pauses(parts, out)
    except Exception:  # noqa: BLE001
        async def _fallback():
            await edge_tts.Communicate(text.strip(), voice, rate=rate, pitch=pitch).save(str(out))
        asyncio.run(_fallback())
        return out


def _ffprobe_exe() -> str | None:
    """ffprobe 경로. 없으면 None (기능이 그때는 조용히 비활성)."""
    ff = Path(_ffmpeg_exe())
    cand = ff.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if cand.exists():
        return str(cand)
    try:
        import imageio_ffmpeg
        c2 = Path(imageio_ffmpeg.get_ffmpeg_exe())
        c2 = c2.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if c2.exists():
            return str(c2)
    except Exception:  # noqa: BLE001
        pass
    found = shutil.which("ffprobe")
    return found


def _audio_duration(path: Path) -> float:
    """오디오 파일 길이(초). 못 구하면 0.0."""
    fp = _ffprobe_exe()
    try:
        if fp:
            r = subprocess.run(
                [fp, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, errors="ignore")
            v = (r.stdout or "").strip()
            if v and v != "N/A":
                return float(v)
        r = subprocess.run([_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                           capture_output=True, text=True, errors="ignore")
        for line in r.stderr.splitlines():
            if "Duration:" in line:
                hms = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = hms.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:  # noqa: BLE001
        return 0.0
    return 0.0


def _silence_edges(path: Path) -> tuple[float, float]:
    """오디오 앞/뒤 무음 길이(초) 실측.

    엔진마다 붙이는 앞뒤 무음 길이가 다르고(Supertonic 앞 0.46~0.68초,
    Kokoro 0.04초) 문장 길이에도 영향을 받는다 → 고정 상수로는 맞지 않는다.
    25ms 블록의 최대 절댓값으로 '연속 무음' 구간을 찾는다.
    """
    dur = _audio_duration(path)
    if dur <= 0:
        return (0.0, 0.0)
    sr = 8000
    try:
        rr = subprocess.run(
            [_ffmpeg_exe(), "-hide_banner", "-v", "error", "-i", str(path),
             "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
            capture_output=True)
        raw = rr.stdout
    except Exception:  # noqa: BLE001
        return (0.0, 0.0)
    blk = int(sr * 0.025)
    n = len(raw) // (blk * 2)
    if n == 0:
        return (0.0, 0.0)
    import array
    peaks: list[int] = []
    for i in range(n):
        a = array.array("h")
        a.frombytes(raw[i * blk * 2:(i + 1) * blk * 2])
        peaks.append(max(abs(v) for v in a) if len(a) else 0)
    top = max(peaks)
    if top <= 0:
        return (dur, 0.0)
    thr = top * 0.02
    head = 0
    while head < n and peaks[head] < thr:
        head += 1
    tail = 0
    while tail < n and peaks[n - 1 - tail] < thr:
        tail += 1
    return (round(head * 0.025, 3), round(min(tail * 0.025, dur), 3))


def _concat_with_pauses(parts: list[Path], out: Path, pad_ms: int = _PAD_MS,
                        trim_parts: bool = False, prof: dict | None = None) -> Path:
    """문장 오디오를 pad_ms 만큼의 정적 사이에 두고 이어 붙인다 (edge 폴백용).

    trim_parts=True 면 각 조각의 앞/뒤 무음을 미리 잘라낸다.
    Supertonic/Kokoro 은 마침표에서 자체적으로~1.1초 쉰다. 그대로concat 하면
    정적 500ms 가 더해져 총 1.6초 간격이 되어 "잘린 느낌"이 든다.
    → 조각 끝의 무음을 silenceremove 로 제거해 pad 만 남긴다.
    """
    ffmpeg = _ffmpeg_exe()
    pad = pad_ms / 1000.0

    # 1단계: (선택) 각 조각의 앞/뒤 무음 제거 → 중간 wav 로
    #    Supertonic/Kokoro 은 합성 결과마다 앞 0.58초 + 뒤 0.50초 의
    #    고정 무음을 붙인다(2026-10-10 실측). 이걸 그대로 concat 하면
    #    정적 500ms + 무음 1.08초 = 1.6초 간격이 되어 "잘린 느낌"이 든다.
    #    → areverse/atrim 으로 앞뒤를 정확한 길이만큼 잘라낸다.
    #    (silenceremove 는 임계값 의존이라 잔여 무음이 남아 목표를 못 맞췄다)
    prepared = list(parts)
    if trim_parts:
        tmp = out.parent / "_trim"
        tmp.mkdir(parents=True, exist_ok=True)
        prepared = []
        for i, p in enumerate(parts):
            w = tmp / f"t{i}.wav"
            if not w.exists() or w.stat().st_size < 1000:
                dur = _audio_duration(p)
                # 앞뒤 무음을 **실측**해서 그것만 정확히 잘라낸다.
                # (엔진·언어·문장 길이마다 값이 달라 고정 상수로는 맞지 않는다)
                fh, ft = _silence_edges(p)
                head = min(max(fh - 0.02, 0.0), max(0.0, dur * 0.35))
                tail = min(max(ft - 0.02, 0.0), max(0.0, dur - head - 0.30))
                if tail > 0.01 and dur - head - tail > 0.15:
                    filt = f"atrim=start={head:.3f}:end={dur - tail:.3f},asetpts=N/SR/TB"
                elif head > 0.01:
                    filt = f"atrim=start={head:.3f},asetpts=N/SR/TB"
                else:
                    filt = "anull"
                rr = subprocess.run(
                    [ffmpeg, "-y", "-i", str(p), "-af", filt,
                     "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", str(w)],
                    capture_output=True, text=True, errors="ignore")
                if rr.returncode != 0 or not w.exists() or w.stat().st_size == 0:
                    print(f"  [tts] 조각 {i + 1} 앞뒤 자르기 실패 → 원본 그대로 사용")
                    prepared.append(p)
                    continue
            prepared.append(w)

    # 2단계: 정적 패드를 사이에 넣어 concat
    # (ffmpeg 는 -i 를 순서대로 읽으므로 lavfi 입력과 옵션이 섞이면 안 된다)
    inputs: list[str] = []
    labels: list[str] = []
    idx = 0
    for i, p in enumerate(prepared):
        inputs += ["-i", str(p)]
        labels.append(f"[{idx}:a]")
        idx += 1
        if i < len(prepared) - 1:
            inputs += ["-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d={pad:.3f}"]
            labels.append(f"[{idx}:a]")
            idx += 1
    filt = f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]"
    cmd = [ffmpeg, "-y", *inputs, "-filter_complex", filt,
           "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "128k", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"오디오 결합 실패: {r.stderr[-300:]}")
    return out


def synth(text: str, lang: str, out_path: Path, voice: str | None = None,
          rate: str | None = None, pitch: str | None = None,
          paced: bool = True) -> Path:
    """대본 → 자연스러운 여성 나레이션 mp3.

    프로필 체인을 따라 시도하고, 전부 실패하면 마지막 edge 프로필로 폴백한다.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    chain = [dict(p) for p in profile_for(lang)]
    # CI/클라우드 환경에서는 로컬 모델(Kokoro/Supertonic)을 강제로 건너뛴다
    # — 모델 파일이 없고 설치 시간도 아깝다. TTS_ENGINE=edge 면 edge 만 사용.
    if os.getenv("TTS_ENGINE", "").lower() == "edge":
        chain = [p for p in chain if p.get("engine") == "edge"] or chain[-1:]
    if voice:  # 특정 음성 지정 시 해당 음성을 체인 맨 앞에
        for p in chain:
            if p["voice"] == voice:
                chain.insert(0, dict(p))
                break
        else:
            chain.insert(0, {**chain[0], "voice": voice})
    if rate:
        for p in chain:
            p["rate"] = rate
    if pitch:
        for p in chain:
            p["pitch"] = pitch

    errors: list[str] = []
    for prof in chain:
        engine = prof["engine"]
        try:
            if engine == "kokoro":
                return _paced_synth(text, prof, out_path, _synth_kokoro, paced)
            if engine == "supertonic":
                return _paced_synth(text, prof, out_path, _synth_supertonic, paced)
            return _synth_edge(text, prof, out_path, paced=paced)
        except Exception as e:  # noqa: BLE001 - 다음 엔진으로 폴백
            errors.append(f"{engine}/{prof['voice']}: {type(e).__name__}: {str(e)[:120]}")
            print(f"  [tts] {engine} 실패 → 다음 엔진 시도 ({type(e).__name__}: {str(e)[:80]})")

    raise RuntimeError("TTS 전 엔진 실패: " + " | ".join(errors))


def _paced_synth(text: str, prof: dict, out: Path, engine_fn, paced: bool) -> Path:
    """로컬 엔진(Kokoro/Supertonic)을 문장 단위로 합성해 일정한 pause 를 넣는다.

    2026-10-10 실측: 한 번에 합성하면 문장 사이 무음이 80ms ~ 780ms 로 제각각이다.
    짧은 간격(80ms)에서는 앞 문장의 여운이 끊겨 "듣기 불편"이라는 지적이 나왔다.
    → 문장별로 따로 합성하고 `_PAD_MS` 만큼의 정적을 정확히 삽입한다.
    """
    sentences = split_sentences(text) if paced else [text.strip()]
    if len(sentences) <= 1:
        return engine_fn(text, prof, out)

    tmp_dir = out.parent / "_parts"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    try:
        for i, s in enumerate(sentences):
            p = tmp_dir / f"p{i}.mp3"
            if not p.exists() or p.stat().st_size < 1000:
                engine_fn(s, prof, p)
            parts.append(p)
        # 각 조각의 앞머리/뒤머리 무음은 컷한다 (없으면 concat 뒤 총 정적이
        # 500ms + 엔진 자체 마침표 쉼(~1.1초) = 1.6초 로 늘어 "잘 끊어 들린다").
        return _concat_with_pauses(parts, out, trim_parts=True, prof=prof)
    except Exception as e:  # noqa: BLE001
        # 문장별 합성이 실패하면 원문 통째로 한 번 더 시도 (파이프라인 중단 방지)
        print(f"  [tts] 문장별 합성 실패({type(e).__name__}) → 통째로 합성")
        return engine_fn(text, prof, out)
