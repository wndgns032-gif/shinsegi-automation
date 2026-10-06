"""샘플 mp3 길이·중복 확인."""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from src.tts import _ffmpeg_exe  # noqa: E402

d = BASE / "data" / "voice_samples"
ff = _ffmpeg_exe()


def dur(p: Path) -> float:
    r = subprocess.run([ff, "-i", str(p), "-f", "null", "-"],
                       capture_output=True, text=True, errors="ignore")
    m = re.findall(r"time=(\d+):(\d+):(\d+\.?\d*)", r.stderr)
    if not m:
        return 0.0
    h, mm, ss = m[-1]
    return int(h) * 3600 + int(mm) * 60 + float(ss)


for p in sorted(d.glob("*.mp3")):
    h = hashlib.md5(p.read_bytes()).hexdigest()[:8]
    print(f"{p.name:52s} {dur(p):6.2f}s  {h}")
