"""숏폼 배경음악(BGM) — 100% 무료·저작권 없음 (2026-09-22 추가).

음원 우선순위:
  1) assets/bgm/  에 사용자가 넣어둔 mp3/wav  (CC0/PUB 도메인 등 자유 음원)
  2) assets/bgm_sources.json 의 원격 자유 음원 URL (내려받아 data/bgm/ 에 캐시)
  3) **로컬 합성** — numpy 로 직접 만드는 로피/앰비언트 루프
     → 외부 저작권이 아예 없는 순수 생성 음원이라 가장 안전하고, 네트워크도 필요 없다.

믹스는 낭독이 또렷하게 들리도록 **사이드체인 덕킹**을 건다
(낭독이 나올 때 BGM 이 자동으로 숨을 죽임, ffmpeg sidechaincompress).

환경변수:
  SHORTFORM_BGM=on|off     (기본 on)
  SHORTFORM_BGM_VOL=0.18   (낭독=1.0 기준 BGM 볼륨)
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = ROOT / "assets" / "bgm"
SOURCES_JSON = ROOT / "assets" / "bgm_sources.json"
CACHE_DIR = ROOT / "data" / "bgm"

SR = 44100
TARGET_SEC = 36.0            # 합성 루프 길이(초) — 영상보다 길게 만들어 자연스럽게 루프


# ────────────────────────────── 공개 API ──────────────────────────────
def enabled() -> bool:
    return os.getenv("SHORTFORM_BGM", "on").strip().lower() not in ("0", "off", "false", "no")


def volume() -> float:
    try:
        return float(os.getenv("SHORTFORM_BGM_VOL", "0.18"))
    except ValueError:
        return 0.18


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


# ────────────────────────────── 음원 선택 ──────────────────────────────
def _local_files() -> list[Path]:
    if not LOCAL_DIR.exists():
        return []
    out = []
    for p in sorted(LOCAL_DIR.iterdir()):
        if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg") and p.stat().st_size > 50000:
            out.append(p)
    return out


def _remote_sources() -> list[str]:
    if not SOURCES_JSON.exists():
        return []
    try:
        data = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("urls", [])
        return [u for u in data if isinstance(u, str) and u.startswith("http")]
    except Exception:  # noqa: BLE001
        return []


def track(seed: int | str = 0) -> Path | None:
    """이 영상에 쓸 BGM 파일 경로. 없으면(None) 조용히 BGM 생략."""
    if not enabled():
        return None

    key = hashlib.md5(str(seed).encode("utf-8")).hexdigest()
    idx = int(key[:8], 16)

    files = _local_files()
    if files:
        return files[idx % len(files)]

    urls = _remote_sources()
    if urls:
        u = urls[idx % len(urls)]
        dest = CACHE_DIR / (hashlib.md5(u.encode("utf-8")).hexdigest()[:12] + ".mp3")
        if dest.exists() and dest.stat().st_size > 50000:
            return dest
        try:
            import requests
            r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
            if r.ok and len(r.content) > 50000:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                return dest
        except Exception:  # noqa: BLE001
            pass

    # 3) 로컬 합성 (저작권 문제 원천 차단)
    #    기본은 v0 고정(사용자 지정 2026-09-22). SHORTFORM_BGM_VARIANT 로 0/1/2 변경 가능.
    try:
        variant = int(os.getenv("SHORTFORM_BGM_VARIANT", "0")) % 3
    except ValueError:
        variant = 0
    dest = CACHE_DIR / f"synth_v{variant}.wav"
    if dest.exists() and dest.stat().st_size > 100000:
        return dest
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        synth_loop(dest, variant=variant)
        return dest
    except Exception as e:  # noqa: BLE001
        print(f"  [bgm] 합성 실패 → BGM 생략 ({type(e).__name__}: {str(e)[:80]})")
        return None


def track_for(seed: int | str = 0) -> Path | None:
    """fable v6용 트랙 선택 — 순서: 로컬 파일 → 원격 자유 음원 → 합성.

    2026-10-04: 참고 영상 BGM(진격의 거인 Call of Silence)을 재현하려 했으나
        저작권·Content ID 위험이 있어 합성(v6)으로 대체했었다.
    2026-10-08 로이 요청: "가사 뺴고 음악만, 인기 많은 무료 BGM 으로"
        → **Pixabay License 원음**을 쓴다. 무료·상업 사용·출처 표기 불필요.
        실제 곡이 로컬 합성보다 훨씬 고급스럽다.

    ⚠️ 2026-10-09 로이 확인 질문에 대한 정답:
        **현재 쓰이는 BGM 은 'Call of Silence' 가 아니다.**
        Call of Silence 은 Hiroyuki Sawano 작/ Gemie 가사짜리 copyrighted 곡이라
        (Universal Music Publishing + Pony Canyon) 무료 라이선스 버전이 없다.
        가사까지 있어 YouTube Content ID 에 걸리면 수익이 차단되거나 영상이 삭제된다.
        → 합법적으로 할 수 있는 건 '분위기 모방' 뿐이며, 그건 아래 폴백(v6 합성)이 담당한다.

    길이: mix() 가 '-stream_loop -1' 로 무한 반복하므로 BGM 이 짧아도 자동으로 이어진다.

    assets/bgm/ 에 파일을 직접 넣으면 그것을 우선한다(기존 동작 유지).
    """
    if not enabled():
        return None
    files = _local_files()
    if files:
        key = hashlib.md5(str(seed).encode("utf-8")).hexdigest()
        idx = int(key[:8], 16)
        return files[idx % len(files)]

    # 2) 원격 자유 음원 (Pixabay 등) — 검증된 URL 만 들어있다
    remote = _remote_track(seed)
    if remote is not None:
        return remote

    # 3) 로컬 합성 (마지막 폴백)
    try:
        variant = int(os.getenv("FABLE_BGM_VARIANT", "6"))
    except ValueError:
        variant = 6
    dest = CACHE_DIR / f"synth_v{variant}.wav"
    if dest.exists() and dest.stat().st_size > 100000:
        return dest
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        synth_loop(dest, variant=variant)
        return dest
    except Exception as e:  # noqa: BLE001
        print(f"  [bgm] 합성 실패 → BGM 생략 ({type(e).__name__}: {str(e)[:80]})")
        return None


def _remote_track(seed: int | str = 0) -> Path | None:
    """assets/bgm_sources.json 의 URL 중 하나를 내려받아 캐시한다.

    2026-10-08: Pixabay 는 웹 페이지를 봇 차단(403)하므로 검색으로 URL 을 찾지 않는다.
    → **실제 다운로드로 검증된 URL 만** json 에 넣어둔다.
    실패하면 조용히 None 을 돌려줘서 다음 폴백(합성)으로 넘어간다.
    """
    urls = _remote_sources()
    if not urls:
        return None
    key = hashlib.md5(str(seed).encode("utf-8")).hexdigest()
    idx = int(key[:8], 16)
    u = urls[idx % len(urls)]
    dest = CACHE_DIR / (hashlib.md5(u.encode("utf-8")).hexdigest()[:12] + ".mp3")
    if dest.exists() and dest.stat().st_size > 50000:
        return dest
    try:
        import requests
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
        if r.ok and len(r.content) > 50000:
            dest.write_bytes(r.content)
            return dest
        print(f"  [bgm] 원격 음원 실패 HTTP {r.status_code} → 합성으로 폴백")
    except Exception as e:  # noqa: BLE001
        print(f"  [bgm] 원격 음원 오류 ({type(e).__name__}) → 합성으로 폴백")
    return None


# ────────────────────────────── 믹스 ──────────────────────────────
def mix(src: Path, dst: Path, duration: float, bgm: Path | None,
        video_vf: str | None = None) -> Path:
    """src(영상+낭독) + bgm → dst.

    bgm 이 없어도 video_vf 가 있으면 영상 필터만 적용해 재인코딩한다(오디오는 copy).
    """
    ffmpeg = _ffmpeg_exe()
    if bgm is None or not Path(bgm).exists():
        if video_vf:
            cmd = [ffmpeg, "-y", "-i", str(src), "-vf", video_vf,
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                   "-c:a", "copy", "-movflags", "+faststart", str(dst)]
            r = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
            if r.returncode == 0:
                return dst
            raise RuntimeError(f"ffmpeg [film+subs] 실패: {r.stderr[-400:]}")
        if src.resolve() != dst.resolve():
            dst.write_bytes(src.read_bytes())
        return dst

    t = max(duration, 1.0)
    fade_out_st = max(t - 1.6, 0.1)
    vol = volume()
    out_st = t - 0.05

    vpart = f"[0:v]{video_vf}[vout]" if video_vf else "[0:v]null[vout]"
    # ⭐ 2026-10-10 로이 피드백 ("사진 퀄리티와 TTS 소리가 달라"):
    #   참고 채널(인생지혜) 대비 우리 피크 볼륨이 0.071 → 12배 작았다.
    #   원인은 로컬 TTS(Supertonic/Kokoro) 출력이 조용하고,
    #   BGM(0.18) 앞에 묻혀 낭독이 들리지 않았다.
    # → loudnorm 으로 **낭독 트랙을 EBU R128 기준(-16 LUFS)으로 정규화**한다.
    #   normalize=0 (amix) 이라 BGM 볼륨은 그대로 두고 voice 만 올린다.
    fc = (
        f"[0:a]aformat=fltp,aresample={SR},"
        f"loudnorm=I=-16:TP=-1.5:LRA=11,asplit=2[vo][sc];"
        f"[1:a]aformat=fltp,aresample={SR},atrim=0:{t:.2f},"
        f"volume={vol:.3f},highpass=f=110,lowpass=f=7200,"
        f"afade=t=in:st=0:d=1.2,afade=t=out:st={fade_out_st:.2f}:d=1.6[bg];"
        f"[bg][sc]sidechaincompress=threshold=0.030:ratio=8:attack=20:"
        f"release=350:makeup=1[bgd];"
        f"[vo][bgd]amix=inputs=2:duration=first:normalize=0,"
        f"loudnorm=I=-14:TP=-1.0:LRA=11[aout]"
    )
    cmd = [_ffmpeg_exe(), "-y", "-i", str(src), "-stream_loop", "-1", "-i", str(bgm),
           "-filter_complex", f"{vpart};{fc}",
           "-map", "[vout]", "-map", "[aout]",
           "-t", f"{t:.2f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
           "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-ac", "2",
           "-movflags", "+faststart", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    if r.returncode != 0:
        print(f"  [bgm] 믹스 실패 → BGM 없이 진행 ({r.stderr[-160:]})")
        if src.resolve() != dst.resolve():
            dst.write_bytes(src.read_bytes())
    return dst


# ────────────────────────────── 로컬 합성 (저작권 0) ──────────────────────────────
def _f(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def _place(buf: np.ndarray, sig: np.ndarray, start: int) -> None:
    i = int(start)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i]


def _adsr(n: int, attack: float, decay: float, hold: float, release: float) -> np.ndarray:
    """길이 n 샘플의 ADSR 엔벨로프(항상 정확히 n 길이로 맞춘다)."""
    a, d, h, r = (int(x * SR) for x in (attack, decay, hold, release))
    a, d, h, r = max(a, 1), max(d, 1), max(h, 0), max(r, 1)
    total = a + d + h + r
    env = np.zeros(total, dtype=np.float32)
    env[:a] = np.linspace(0, 1, a, dtype=np.float32)
    dec = np.exp(-np.linspace(0, 5.0, d, dtype=np.float32)) * (1 - 0.55) + 0.55
    env[a:a + d] = dec
    if h:
        env[a + d:a + d + h] = dec[-1]
    env[a + d + h:] = dec[-1] * np.exp(-np.linspace(0, 5.0, r, dtype=np.float32))
    if total > n:                       # 요청 길이보다 길면 자른다
        env = env[:n]
    elif total < n:                     # 짧으면 0으로 패딩(자연 감쇠)
        env = np.pad(env, (0, n - total))
    return env


def _tone(freqs: list[float], dur: float, attack: float, decay: float,
          hold: float, release: float, harm: float = 0.35) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    env = _adsr(n, attack, decay, hold, release)
    if len(env) < n:
        env = np.pad(env, (0, n - len(env)))
    sig = np.zeros(n, dtype=np.float32)
    for k, f in enumerate(freqs):
        amp = 1.0 / (1.0 + 0.55 * k)
        sig += amp * np.sin(2 * np.pi * f * t)
        if harm > 0:  # 배음(2·3배)을 아주 조금 → 톤에 따뜻함
            sig += amp * harm * 0.35 * np.sin(2 * np.pi * f * 2 * t)
            sig += amp * harm * 0.15 * np.sin(2 * np.pi * f * 3 * t)
    sig *= env[:n]
    return sig / (1.0 + harm)


def _noise(n: int, bright: bool = True) -> np.ndarray:
    x = np.random.default_rng().standard_normal(n).astype(np.float32)
    if bright:  # 1차 차분 ≈ 하이패스 → 셰이커/브러시 질감
        x = np.diff(x, prepend=0.0)
    return x


def _reverb(x: np.ndarray, amount: float = 0.28, tau: float = 0.32) -> np.ndarray:
    if amount <= 0:
        return x
    ir_len = int(tau * 4 * SR)
    t = np.arange(ir_len, dtype=np.float32) / SR
    ir = np.random.default_rng(7).standard_normal(ir_len).astype(np.float32) * np.exp(-t / tau)
    ir = ir / (np.abs(ir).max() + 1e-9)
    n = len(x) + ir_len
    out = np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(ir, n), n)[: len(x)]
    return (x + amount * out).astype(np.float32)


def _kick(dur: float = 0.28) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    f = 110 * np.exp(-t * 22) + 46
    phase = 2 * np.pi * np.cumsum(f) / SR
    env = np.exp(-t * 11, dtype=np.float32)
    return (np.sin(phase) * env * 0.9).astype(np.float32)


def synth_loop(out_path: Path, variant: int = 0) -> Path:
    """잔잔하지만 템포가 살아있는 로피-앰비언트 루프를 합성해 wav 로 저장.

    variant 0~5 = 템포·키·패턴·무드가 다른 6가지. 전부 numpy 로 직접 생성하므로
    저작권·원저작자 개념이 발생하지 않는다.
    0~2(lofi): 킥·셰이커 있는 기존 무드 — v5 카드 파이프라인용.
    3~5(cin): 킥 없는 시네마틱 패드 중심 — v6 우화 쇼츠 낭독용 (2026-10-05).
    """
    presets = [
        # (bpm, 진행(4마디, 미디 루트), 코드 타입, 키 보정, 무드)
        (108, [57, 52, 54, 50], ["maj", "maj", "min", "maj"], 0, "lofi"),   # A–E–F#m–D (밝고 경쾌)
        (96, [55, 50, 53, 48], ["maj", "maj", "min", "maj"], -1, "lofi"),   # G–D–Em–C (차분)
        (116, [59, 54, 57, 52], ["min", "maj", "maj", "maj"], 1, "lofi"),   # Bm–F#m–A–E (경쾌+몽환)
        # v6 fable용 시네마틱 — 킥 없음·느린 패드 어택·작은 아르페지오
        (84, [48, 43, 45, 41], ["maj", "maj", "min", "maj"], 0, "cin"),    # C–G–Am–F (감성)
        (76, [50, 47, 45, 43], ["maj", "min", "min", "maj"], 0, "cin"),    # D–Bm–Am–G (애틋)
        (92, [41, 48, 45, 43], ["maj", "maj", "min", "maj"], 0, "cin"),    # F–C–Am–G (희망)
        # 2026-10-04 참고 영상(youtube.com/shorts/V2UtKas1xAA) BGM 재현 — 로이 지시.
        # 분석: A minor · ~92bpm · 피아노계 앰비언트(스펙트럼 중심 2kHz, 고음역 살아있음).
        # Am–F–C–G 진행 + 아르페지오를 조금 더 또렷하게.
        (92, [57, 53, 60, 55], ["min", "maj", "maj", "maj"], 0, "ref"),
    ]
    bpm, roots, kinds, shift, mood = presets[variant % len(presets)]
    cin = mood in ("cin", "ref")
    beat = 60.0 / bpm
    bar = 4 * beat
    bars = max(int(TARGET_SEC / bar), 8)
    total = int(bars * bar * SR) + int(1.2 * SR)      # 마지막 여운(루프 클릭 방지)
    L = np.zeros(total, dtype=np.float32)
    R = np.zeros(total, dtype=np.float32)

    def chord(root: int, kind: str) -> list[int]:
        return [root, root + (3 if kind == "min" else 4), root + 7, root + 12]

    for b in range(bars):
        t0 = int(b * bar * SR)
        root = roots[b % 4] + shift
        notes = chord(root, kinds[b % 4])

        # 1) 패드 (코드, 느린 어택, 좌우 살짝 디튠 → 넓은 스테레오)
        pad_n = int(bar * 0.98 * SR)
        pad_atk = {"lofi": 0.22, "cin": 0.40, "ref": 0.30}[mood]
        for k, nt in enumerate(notes[:3]):
            f0 = _f(nt + 12)
            for ch, det in ((0, -0.06), (1, 0.06)):
                sig = _tone([f0 * (1 + det / 100), f0 * 2 * (1 + det / 100)],
                            pad_n / SR, attack=pad_atk, decay=0.35,
                            hold=pad_n / SR - 0.95, release=0.38, harm=0.25)
                _place(L if ch == 0 else R, sig * (0.085 - 0.012 * k), t0)

        # 2) 베이스 (1·3박, 살짝 싱코페이션)
        for pos in (0.0, 2.0, 3.5):
            sig = _tone([_f(root - 12)], 0.55, attack=0.008, decay=0.20,
                        hold=0.05, release=0.28, harm=0.18)
            amp = 0.13 if cin else 0.16
            _place(L, sig * amp, t0 + int(pos * beat * SR))
            _place(R, sig * amp, t0 + int(pos * beat * SR))

        # 3) 아르페지오 플럭 (8분음표, 좌우 교대 패닝) — ref 는 참고영상처럼 조금 더 또렷하게
        pattern = [0, 1, 2, 3, 2, 1, 2, 3]
        arp_amp = {"lofi": 0.115, "cin": 0.082, "ref": 0.105}[mood]
        for i, st in enumerate(pattern):
            pos = i * beat / 2
            nt = notes[st] + (12 if i % 4 == 3 else 0)
            sig = _tone([_f(nt)], 0.42, attack=0.004, decay=0.30,
                        hold=0.0, release=0.12, harm=0.45)
            pan = 0.72 if i % 2 == 0 else 0.28
            _place(L, sig * pan * arp_amp, t0 + int(pos * SR))
            _place(R, sig * (1 - pan) * arp_amp, t0 + int(pos * SR))

        # 4) 소프트 킥 (1·3박) — cin 무드에서는 생략 (낭독 방해 방지)
        if not cin:
            for pos in (0.0, 2.0):
                k = _kick()
                _place(L, k * 0.16, t0 + int(pos * beat * SR))
                _place(R, k * 0.16, t0 + int(pos * beat * SR))

        # 5) 셰이커/브러시 (8분 뒤박) — cin/ref 은 아주 작게
        shake_amp = 0.02 if cin else 0.05
        for i in range(1, 8, 2):
            n = int(0.05 * SR)
            x = _noise(n) * np.exp(-np.linspace(0, 6, n, dtype=np.float32)) * shake_amp
            pan = 0.35 if (i // 2) % 2 == 0 else 0.65
            _place(L, x * pan, t0 + int(i * beat / 2 * SR))
            _place(R, x * (1 - pan), t0 + int(i * beat / 2 * SR))

    # 리버브 센드 + 마스터
    L = _reverb(L, amount=0.30)
    R = _reverb(R, amount=0.30)
    stereo = np.stack([L, R], axis=1)
    peak = float(np.abs(stereo).max()) or 1.0
    stereo = stereo / peak * 0.86
    # 루프 경계는 자연 감쇠 + 아주 짧은 페이드로 클릭 제거
    fade = int(0.05 * SR)
    stereo[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)[:, None]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return out_path


if __name__ == "__main__":
    import sys
    v = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    p = synth_loop(CACHE_DIR / f"_preview_v{v}.wav", variant=v)
    print("wrote", p, p.stat().st_size // 1024, "KB")
