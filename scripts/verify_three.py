"""하루 3편 × 4개 언어 = 12개 영상 일괄 검수.

2026-10-11 신설. 로이 목표가 "하루 3편 4개 언어" 이므로, 슬롯 하나가
조용히 빠지는 사고를 눈으로 확인할 수 있게 한 장의 시트로 뽑는다.

사용:
    python scripts/verify_three.py --date 2026-10-11-v3
    python scripts/verify_three.py --date 2026-10-11-v3 --sheet out.jpg

검사 항목
  - mp4 존재 / 100KB 이상
  - 길이(초), 장면 수
  - **첫 프레임 밝기** — 검은 화면(썸네일 사고) 검출
  - 20초 지점 프레임의 흑백 편차(컬러가 남았는지)
  - 4개 언어 프레임을 가로로 붙인 대조 시트 생성
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from imageio_ffmpeg import get_ffmpeg_exe  # noqa: E402

KINDS = [("fable", ""), ("stocks", "-stocks"), ("biz", "-biz")]
LANGS = ["ko", "en", "zh-cn", "fr"]


def _probe(ff: str, mp4: Path) -> tuple[float, int, int]:
    """(길이초, 너비, 높이)."""
    out = subprocess.run(
        [ff, "-i", str(mp4)], capture_output=True, text=True,
        encoding="utf-8", errors="replace").stderr
    dur, w, h = 0.0, 0, 0
    for line in out.splitlines():
        if "Duration:" in line:
            t = line.split("Duration:")[1].split(",")[0].strip()
            try:
                hh, mm, ss = t.split(":")
                dur = int(hh) * 3600 + int(mm) * 60 + float(ss)
            except Exception:  # noqa: BLE001
                pass
        if "Video:" in line and "x" in line:
            for tok in line.split(","):
                tok = tok.strip()
                if "x" in tok and tok.split("x")[0].isdigit():
                    try:
                        w, h = (int(x) for x in tok.split(" ")[0].split("x")[:2])
                    except Exception:  # noqa: BLE001
                        pass
                    break
    return dur, w, h


def _frame_stats(ff: str, mp4: Path, at: float, dest: Path) -> dict:
    from PIL import Image
    import numpy as np
    subprocess.run([ff, "-y", "-ss", str(at), "-i", str(mp4),
                    "-frames:v", "1", str(dest)], capture_output=True)
    if not dest.exists():
        return {}
    im = Image.open(dest).convert("RGB")
    g = np.asarray(im.convert("L"), dtype=np.float32)
    arr = np.asarray(im, dtype=np.float32) / 255.0
    chroma = float(np.median(arr.max(axis=2) - arr.min(axis=2)))
    return {"mean": float(g.mean()),
            "dark_pct": float((g < 30).mean() * 100),
            "chroma": chroma,
            "im": im,
            "size": im.size}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", default="data/preview")
    ap.add_argument("--sheet", default="")
    args = ap.parse_args()

    ff = get_ffmpeg_exe()
    root = Path("data/fables")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, str, dict]] = []
    print(f"{'편':<10}{'lang':<8}{'길이':>7}{'크기':>12}{'해상도':>12}"
          f"{'첫프레임밝기':>12}{'검은%':>8}{'채도':>8}")
    print("-" * 80)
    for kind, suffix in KINDS:
        sdir = root / f"{args.date}{suffix}"
        for lang in LANGS:
            mp4 = sdir / f"fable_{lang}.mp4"
            if not mp4.exists():
                print(f"{kind:<10}{lang:<8}{'— 없음':>7}")
                rows.append((kind, lang, {}))
                continue
            kb = mp4.stat().st_size // 1024
            dur, w, h = _probe(ff, mp4)
            st = _frame_stats(ff, mp4, 0.4, out / f"_v_{kind}_{lang}_f0.jpg")
            st2 = _frame_stats(ff, mp4, 20.0, out / f"_v_{kind}_{lang}_f20.jpg")
            print(f"{kind:<10}{lang:<8}{dur:>6.1f}s{kb:>11}KB"
                  f"{f'{w}x{h}':>12}{st.get('mean', 0):>12.1f}"
                  f"{st.get('dark_pct', 0):>8.1f}{st2.get('chroma', 0):>8.3f}")
            rows.append((kind, lang, {**st, "dur": dur, "kb": kb,
                                      "im20": st2.get("im")}))

    # 대조 시트 — 행=3편, 열=4개 언어 (20초 프레임)
    try:
        from PIL import Image
        tw, th = 240, 427
        sheet = Image.new("RGB", (tw * 4, th * 3), (18, 18, 18))
        for r, (kind, _suffix) in enumerate(KINDS):
            for c, lang in enumerate(LANGS):
                hit = next((d for k, l, d in rows
                            if k == kind and l == lang and d.get("im20")), None)
                if hit:
                    sheet.paste(hit["im20"].resize((tw, th)), (c * tw, r * th))
        dest = Path(args.sheet) if args.sheet else out / f"three_{args.date}.jpg"
        sheet.save(dest, quality=90)
        print(f"\n대조 시트: {dest}")
    except Exception as e:  # noqa: BLE001
        print(f"시트 생성 실패: {e}")

    good = [d for _k, _l, d in rows if d]
    print(f"\n총 {len(good)}/12 개 생성")
    bad = [(k, l, d) for k, l, d in rows
           if not d or d.get("dark_pct", 0) > 60 or d.get("kb", 0) < 100]
    if bad:
        print("⚠️ 확인 필요:")
        for k, l, d in bad:
            print(f"   - {k}/{l}: {d if not d else '검은화면/용량이상'}")
    else:
        print("✅ 12개 전부 정상")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
