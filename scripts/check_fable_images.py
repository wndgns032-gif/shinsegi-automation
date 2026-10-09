"""우화 이미지 품질 검수 — 장면별 자동 검사 + 실패 장면 재생성 (2026-10-07).

왜 필요한가 (실측 근거):
  flux(stable) 는 동일 프롬프트라도 다른 동물을 그린다. 두더지 우화에서
  실제로 여우·사람이 섞여 나왔다. 프롬프트만으로는 100% 막을 수 없다.
  → **검출 후 해당 장면만 다른 seed 로 재생성**하는 루프를 둔다.

검사 항목 (전부 코드 판정 — 사람이 눈으로 볼 필요 없음):
  1. 해상도 — 모든 장면이 같은 크기인지 (다르면 톤이 튄다)
  2. 채도   — RGB 채널 편차(spread) < 임계값 → 흑백 유지
  3. 밝기   — 평균 휘도가 극단(너무 어둡거나 밝음)이면 자막이 안 읽힌다
  4. 파일 크기 — 지나치게 작으면 폴백/손상 이미지

사용법:
    python scripts/check_fable_images.py                 # 검사만
    python scripts/check_fable_images.py --regen         # 실패 장면 자동 재생성
    python scripts/check_fable_images.py --date 2026-10-07

주의: 재성성 한도는 쿼터 보호를 위해 장면당 2회. 그래도 실패하면 그대로 두고
      로그에 남긴다(파이프라인 중단 금지).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import fable  # noqa: E402
from src.fablevideo import IMG_H, IMG_W, _to_monochrome  # noqa: E402

# 검사 임계값
SAT_MAX = 8.0          # RGB 채널 평균 편차 — 흑백이면 < 8 (세피아톤6~7)
BRIGHT_MIN = 28.0# 평균 휘도 하한 (너무 어두우면 흰 자막이 묻힘)
BRIGHT_MAX = 225.0     # 평균 휘도 상한
SIZE_MIN_BYTES = 15000 # 손상/폴백 이미지
SIZE_TOLERANCE = 40    # 장면 간 크기 허용 편차(px)

# ─────────────────────────────────────────────────────────────
# 폴백(파스텔 그라디언트) 이미지 전용 감지 (2026-10-09 추가)
# ─────────────────────────────────────────────────────────────
# 문제: Pollinations 402 로 실패하면 _fallback_image() 가 파스텔 그라디언트를
#      만들어 넣는다. 이 이미지는黑白 변환 후에도 통과해 버려서
#      "영상인데 그림이 없는" 상태가 된다. (실측: 20장 중 18장이 폴백)
#      → 색상 통계로는 구분이 안 되므로 **디테일(선화·에지) 양**을 본다.
#      실화는 선·명암이丰富하지만 그라디언트는几乎是노이즈/패치가 적다.
FALLBACK_EDGE_MAX = 0.045  # 에지 밀도 상한 (0~1)
                          # 실측 2026-10-09: 실제 그림 0.113 / 폴백 0.011 (10배 차)
                          # → 0.045 로 두면 어느 쪽도 오판하지 않는다.
FALLBACK_UNIQ_MAX = 26      # 고유 그레이레벨 수 (실화 254 / 폴백 237 — 보조 지표)


def _detail_metrics(p: Path) -> tuple[float, int]:
    """(에지 밀도, 고유 그레이레벨 수) — 그림의'디테일 함량' 측정."""
    from PIL import ImageFilter
    im = Image.open(p).convert("L")
    # 에지(선화) 추출 후 평균 절댓값 → 선이 많을수록 높다
    edges = im.filter(ImageFilter.FIND_EDGES)
    edge = ImageStat.Stat(edges).mean[0] / 255.0
    # 그레이레벨 다양성: 인풋/아웃풋의 중앙값 차이가 '톤의 층'을 나타냄
    uniq = len(im.getcolors(maxcolors=512) or [])
    return edge, uniq


def _is_fallback(p: Path) -> str | None:
    """폴백 그라디언트면 이유 문자열, 정상 그림이면 None."""
    try:
        edge, uniq = _detail_metrics(p)
    except Exception:  # noqa: BLE001
        return None
    reasons = []
    if edge < FALLBACK_EDGE_MAX:
        reasons.append(f"선화 약함(edge={edge:.3f})")
    if uniq < FALLBACK_UNIQ_MAX:
        reasons.append(f"톤 단조(gray={uniq})")
    if not reasons:
        return None
    return " → ".join(reasons)


def _stats(p: Path) -> dict:
    im = Image.open(p).convert("RGB")
    r, g, b = ImageStat.Stat(im).mean
    return {
        "size": im.size,
        "sat": (abs(r - g) + abs(g - b) + abs(r - b)) / 3.0,
        "bright": (r + g + b) / 3.0,
        "bytes": p.stat().st_size,
    }


def inspect(images_dir: Path) -> tuple[list[dict], list[int]]:
    """전 장면 검사. 반환: (결과 리스트, 실패 장면 번호 리스트)."""
    files = sorted(images_dir.glob("scene*.jpg"),
                   key=lambda q: int("".join(c for c in q.stem if c.isdigit()) or 0))
    results: list[dict] = []
    fails: list[int] = []
    if not files:
        print(f"  [check] 이미지 없음: {images_dir}")
        return results, fails

    ref_w, ref_h = files[0].width if hasattr(files[0], "width") else None, None
    try:
        ref_size = Image.open(files[0]).size
    except Exception:  # noqa: BLE001
        ref_size = (IMG_W, IMG_H)

    for f in files:
        n = int("".join(c for c in f.stem if c.isdigit()) or 0)
        row: dict = {"scene": n, "ok": True, "issues": []}
        try:
            st = _stats(f)
            row.update({k: st[k] for k in ("sat", "bright", "bytes")})
            row["size"] = f"{st['size'][0]}x{st['size'][1]}"

            if abs(st["size"][0] - ref_size[0]) > SIZE_TOLERANCE or \
               abs(st["size"][1] - ref_size[1]) > SIZE_TOLERANCE:
                row["issues"].append(f"크기 편차 {row['size']} (기준 {ref_size[0]}x{ref_size[1]})")
            if st["bytes"] < SIZE_MIN_BYTES:
                row["issues"].append(f"파일 크기 작음 {st['bytes'] // 1024}KB")
            if st["sat"] > SAT_MAX:
                row["issues"].append(f"채도 높음 {st['sat']:.1f}")
            if st["bright"] < BRIGHT_MIN:
                row["issues"].append(f"너무 어두움 {st['bright']:.0f}")
            if st["bright"] > BRIGHT_MAX:
                row["issues"].append(f"너무 밝음 {st['bright']:.0f}")
            # ⭐ 2026-10-09: 폴백 그라디언트 이미지 (사진 없는 영상) 감지
            fb = _is_fallback(f)
            if fb:
                row["issues"].append(f"⚠ 폴백이미지 — 실제 그림 아님: {fb}")
        except Exception as e:  # noqa: BLE001
            row["issues"].append(f"열기 실패: {type(e).__name__}")
        row["ok"] = not row["issues"]
        if not row["ok"]:
            fails.append(n)
        results.append(row)
    return results, fails


def print_report(results: list[dict]) -> None:
    for r in results:
        mark = "OK  " if r["ok"] else "FAIL"
        detail = f"sat={r.get('sat', 0):5.2f} bright={r.get('bright', 0):6.1f} {r.get('size', '')}"
        line = f"  [{mark}] scene {r['scene']:2d}  {detail}"
        if r["issues"]:
            line += "  ← " + "; ".join(r["issues"])
        print(line)


def regenerate(images_dir: Path, scenes: list[int], story_path: Path,
               seed_base: int, per_scene: int = 3) -> list[int]:
    """실패 장면을 다른 seed 로 재생성. 성공한 장면 번호 리스트 반환(재실패 포함).

    2026-10-09 수정:
      - turbo 모델을 함께 시도 (실측에서 flux 보다 자주 성공)
      - 재생성 결과를 _is_fallback 으로 검증 (폴백 그라디언트를 성공으로 치면 안 됨)
      - 백오프를 늘려 쿼터 회복을 기다림
    """
    story = json.loads(story_path.read_text(encoding="utf-8"))
    still_bad: list[int] = []
    for n in scenes:
        idx = n - 1
        if idx < 0 or idx >= len(story["scenes"]):
            continue
        sc = story["scenes"][idx]
        base = sc.get("image_prompt", "")
        dest = images_dir / f"scene{n}.jpg"
        mark = images_dir / f"scene{n}.mono"
        ok = False
        for attempt in range(1, per_scene + 1):
            seed = seed_base + n * 137 + attempt * 9001
            model = "turbo" if attempt % 2 == 1 else "flux"
            url = ("https://image.pollinations.ai/prompt/"
                   + requests.utils.quote(base)
                   + f"?width={IMG_W}&height={IMG_H}&nologo=true"
                     f"&seed={seed}&model={model}")
            try:
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=150)
                if r.ok and "image" in r.headers.get("content-type", "") \
                        and len(r.content) > SIZE_MIN_BYTES:
                    dest.write_bytes(r.content)
                    _to_monochrome(dest)
                    mark.write_text("1", encoding="utf-8")
                    st = _stats(dest)
                    # ⭐ 채도 + 폴백 그라디언트 둘 다 검사한다
                    fb = _is_fallback(dest)
                    if st["sat"] <= SAT_MAX and not fb:
                        print(f"  [regen] scene {n} 재생성 OK "
                              f"(시도 {attempt}, {model}, sat={st['sat']:.1f})")
                        ok = True
                        break
                    reason = f"채도 초과 ({st['sat']:.1f})" if st["sat"] > SAT_MAX else f"폴백 ({fb})"
                    print(f"  [regen] scene {n} 재생성됐으나 {reason} → 재시도")
                    # 실패한 이미지는 남겨두지 않는다 (다음 판정이 오염됨)
                    dest.unlink(missing_ok=True)
                    mark.unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001
                print(f"  [regen] scene {n} 시도 {attempt} 오류 {type(e).__name__}")
            if attempt < per_scene:
                time.sleep(30)   # 402 쿼터 회복 대기 (2026-10-09 실측 반영)
        if not ok:
            print(f"  [regen] scene {n} 재생성 실패 — 폴백 그라디언트로 대체")
            still_bad.append(n)
    return still_bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--regen", action="store_true", help="실패 장면 자동 재생성")
    args = ap.parse_args()

    data_dir = ROOT / "data"
    date = args.date
    if not date:
        from src.quotes import KST
        from datetime import datetime
        date = datetime.now(KST).date().isoformat()

    images_dir = data_dir / "fables" / date / "images"
    story_path = data_dir / "fables" / date / "story.json"
    if not story_path.exists():
        print(f"  [check] story.json 없음: {story_path}")
        return 0

    print(f"=== 우화 이미지 검수 ({date}) ===")
    results, fails = inspect(images_dir)
    if not results:
        print("  (이미지 없음)")
        return 0
    print_report(results)
    print(f"  → {len(results) - len(fails)}/{len(results)} 통과")

    if fails and args.regen:
        print(f"\n=== 실패 {len(fails)}개 장면 재생성 ===")
        seed_base = int(date.replace("-", "")) % 10000
        still = regenerate(images_dir, fails, story_path, seed_base)
        print("\n=== 재생성 후 재검사 ===")
        results2, fails2 = inspect(images_dir)
        print_report(results2)
        print(f"  → 최종 {len(results2) - len(fails2)}/{len(results2)} 통과"
              + (f" (잔여 실패: {fails2})" if fails2 else " (전부 통과)"))
        return 0
    if fails:
        print(f"  실패 장면: {fails}  (--regen 으로 자동 재생성 가능)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())