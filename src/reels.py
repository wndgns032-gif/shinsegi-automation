"""카드 → 나레이션 리일스(mp4) 변환. 전부 로컬·무료.

파이프라인:
  reels_script (딥시크 생성, 차분한 낭독용 구어체)
    → src.tts: 최신 세대 여성 신경망 음성 + 문장별 호흡(무료·무제한)
    → 카드 PNG를 오디오 길이에 맞춰 슬라이드쇼로 합성 (ffmpeg)
    → 1080x1350 (9:16) mp4 = IG Reels 규격
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import tts


def voice_for(lang: str) -> str:
    """호환용 — 실제 음성 프로필은 src.tts 가 관리한다."""
    return tts.voice_for(lang)


def synthesize_voice(text: str, lang: str, out_path: Path, rate: str | None = None) -> Path:
    """낭독 대본을 여성 음성 mp3로 합성한다 (문장 사이 호흡 포함)."""
    return tts.synth(text, lang, out_path, rate=rate)


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def _audio_duration(path: Path) -> float:
    """ffmpeg 로 오디오 길이(초) 측정."""
    r = subprocess.run(
        [_ffmpeg_exe(), "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, errors="ignore",
    )
    m = re.findall(r"time=(\d+):(\d+):(\d+\.?\d*)", r.stderr)
    if not m:
        return 10.0
    h, mm, ss = m[-1]
    return int(h) * 3600 + int(mm) * 60 + float(ss)


def build_reels(card_paths: list[Path], audio_path: Path, out_path: Path,
                min_per_card: float = 2.0, max_per_card: float = 4.5) -> Path:
    """카드 PNG + 나레이션 mp3 → 1080x1350 mp4.

    카드 1장당 노출 시간 = 오디오 길이 / 카드 수 (min~max 범위로 보정).
    """
    if not card_paths:
        raise ValueError("카드가 없습니다")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg_exe()

    total = _audio_duration(audio_path)
    per = max(min_per_card, min(max_per_card, total / len(card_paths)))

    # concat demuxer 는 리스트 파일 위치를 기준으로 상대경로를 해석하므로 절대경로로 쓴다
    abs_cards = [Path(p).resolve() for p in card_paths]
    list_file = out_path.parent / "concat.txt"
    lines = []
    for p in abs_cards:
        lines.append(f"file '{p.as_posix()}'")
        lines.append(f"duration {per:.3f}")
    # concat demuxer: 마지막 파일은 duration 없이 한 번 더 (마지막 프레임 유지)
    lines.append(f"file '{abs_cards[-1].as_posix()}'")
    list_file.write_text("\n".join(lines), encoding="utf-8")

    cmd = [
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-i", str(audio_path),
        "-vf", "scale=1080:1350:force_original_aspect_ratio=decrease,"
               "pad=1080:1350:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    if r.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"ffmpeg 실패: {r.stderr[-500:]}")
    return out_path


def make_reels(script: str, lang: str, card_paths: list[Path], out_dir: Path) -> Path:
    """대본 → 음성 → 영상 한 번에."""
    out_dir.mkdir(parents=True, exist_ok=True)
    audio = synthesize_voice(script, lang, out_dir / f"voice_{lang}.mp3")
    return build_reels(card_paths, audio, out_dir / f"reels_{lang}.mp4")
