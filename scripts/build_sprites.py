"""템플릿에서 선생님/토끼 스프라이트(RGBA) 추출 — 풀와이드 숏폼 레이아웃용.

원리:
  · 템플릿 배경 = 크림 베이지(거의 균일). 배경색과의 색 거리로 전경 마스크 생성
  · scipy 라벨링으로 작은 잡음 덩어리 제거 → 구멍 메움 → 1px 침식 + 가우시안 페더
  · 스프라이트는 **원래 위치 그대로** 풀캔버스(1080x1350) RGBA로 저장
    → 합성 때 좌표 계산 없이 (0,0) 오버레이하면 원위치

산출물:
  assets/sprite_teacher.png  (x300~1080, y0~1015 영역)
  assets/sprite_rabbit.png   (x0~400,  y550~1350 영역, 좌측 꽃 포함)
  data/_sprite_check.png     (검증용: 회색 배경 + 스프라이트 합성)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

BASE = Path(__file__).resolve().parents[1]
TPL = BASE / "assets" / "template_card.png"

BG = np.array([238, 229, 209])   # 크림 베이지
STRONG = 100                     # 이 이상이면 확실한 전경 (배경 모델 만들 때 제외)
THRESH = {"teacher": 40, "rabbit": 25}   # 지역 배경 모델과의 색 거리 임계값
MIN_AREA = {"teacher": 1500, "rabbit": 600}  # 이보다 작은 덩어리는 배경 얼룩으로 간주
VIDEO_BAND = (500, 1260)         # 영상 밴드(여유 포함) — 이 안의 덩어리는 품질이 중요
SOLID_MIN = 0.6                  # 영상 밴드 안 덩어리의 최소 충실도(메운 후 원래 마스크 비율)

# (이름, x0, y0, x1, y1)
REGIONS = {
    "teacher": (300, 0, 1080, 1015),
    "rabbit": (0, 550, 400, 1350),
}

# 수동 제외 구역 (절대좌표) — 캐릭터가 닿지 않는 옅은 워시 얼룩 제거용.
# 프로브 확인: 뒤쪽 구두 끝 x=939, y=943~993 → x>960 & y>580 은 전부 배경 워시.
EXCLUDE = {
    "teacher": [(960, 580, 1080, 1015)],
    "rabbit": [],
}

# 실체화 강도 — 토끼는 흰 드레스 날이 배경색과 가까워 성김이 크므로 더 강하게 닫음
FINAL_CLOSE = {"teacher": 2, "rabbit": 5}
FINAL_ERODE = {"teacher": 1, "rabbit": 3}


def _bg_model(img: np.ndarray) -> np.ndarray:
    """지역 배경 모델 — 강한 전경을 가장 가까운 배경 픽셀로 치환 후 크게 블러.

    수채화 배경은 천천히 변하므로, 전경(캐릭터)을 제거한 뒤 블러하면
    '그 자리에 있었을 배경색'이 복원된다. 옅은 물감 얼룩(워시)도 배경에
    포함되므로 이 모델과 비교하면 얼룩은 전경으로 잡히지 않는다.
    """
    dist = np.abs(img.astype(int) - BG).sum(axis=2)
    strong = dist > STRONG
    strong = ndimage.binary_dilation(strong, iterations=5)  # 캐릭터 가장자리 번짐 차단
    _, inds = ndimage.distance_transform_edt(strong, return_indices=True)
    filled = img[tuple(inds)]
    blurred = Image.fromarray(filled).filter(ImageFilter.GaussianBlur(40))
    return np.asarray(blurred).astype(int)


def extract(img: np.ndarray, box: tuple[int, int, int, int],
            excludes: list[tuple[int, int, int, int]], name: str) -> np.ndarray:
    """영역 내 전경을 RGBA(알파 0~255)로 반환. img는 HxWx3."""
    x0, y0, x1, y1 = box
    h, w = img.shape[:2]
    thresh = THRESH.get(name, 40)
    min_area = MIN_AREA.get(name, 1500)
    final_close = FINAL_CLOSE.get(name, 2)
    final_erode = FINAL_ERODE.get(name, 1)
    bgm = _bg_model(img)
    region = img[y0:y1, x0:x1].astype(int)
    dist = np.abs(region - bgm[y0:y1, x0:x1]).sum(axis=2)
    raw = dist > thresh           # 클로징 전 원본 마스크 (충실도 계산용)
    for ex0, ey0, ex1, ey1 in excludes:
        raw[max(ey0 - y0, 0):ey1 - y0, max(ex0 - x0, 0):ex1 - x0] = False
    # 라벨링 전 최소한의 클로징만 (강하게 닫으면 배경 얼룩이 캐릭터와 한 덩어리가 됨)
    pre = ndimage.binary_closing(raw, iterations=1)

    # 라벨링 → 큰 덩어리만 유지
    lab, n = ndimage.label(pre)
    keep = np.zeros_like(pre)
    vy0, vy1 = VIDEO_BAND
    for i in range(1, n + 1):
        comp = lab == i
        area = int(comp.sum())
        if area < min_area:
            continue
        filled = ndimage.binary_fill_holes(comp)
        ys = np.nonzero(comp.any(axis=1))[0]
        comp_y0, comp_y1 = y0 + ys.min(), y0 + ys.max()
        in_band = comp_y0 < vy1 and comp_y1 > vy0
        if in_band:
            # 영상 위에 놓이는 덩어리: 반쯤 먹힌 배경 얼룩(성김)은 버림.
            # 충실도 = 메운 면적 안에서 클로징 "전" 원본 마스크가 차지하는 비율
            solidity = float((raw & filled).sum()) / max(int(filled.sum()), 1)
            print(f"    comp y[{comp_y0},{comp_y1}] area={area} solidity={solidity:.2f}"
                  + (" DROP" if solidity < SOLID_MIN else ""))
            if solidity < SOLID_MIN:
                continue
        keep |= filled

    # 필터링이 끝난 뒤에 수채화 난이 안쪽 성김을 닫아 실체화
    keep = ndimage.binary_closing(keep, iterations=final_close)
    keep = ndimage.binary_fill_holes(keep)

    # 침식(클로징 팽창 + 배경 헤일로 상쇄) 후 페더
    keep = ndimage.binary_erosion(keep, iterations=final_erode)
    alpha = Image.fromarray((keep * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(1.2))
    alpha_np = np.asarray(alpha)

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[y0:y1, x0:x1, :3] = img[y0:y1, x0:x1]
    rgba[y0:y1, x0:x1, 3] = alpha_np
    return rgba


def main() -> None:
    img = np.asarray(Image.open(TPL).convert("RGB"))
    h, w = img.shape[:2]
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for name, box in REGIONS.items():
        print(f"[{name}]")
        rgba = extract(img, box, EXCLUDE.get(name, []), name)
        out = BASE / "assets" / f"sprite_{name}.png"
        Image.fromarray(rgba).save(out)
        print(f"{name}: {out.name} saved")
        canvas.alpha_composite(Image.fromarray(rgba))

    # 검증: 회색 배경 위 합성 (가장자리 품질 확인용)
    check = Image.new("RGBA", (w, h), (120, 120, 120, 255))
    check.alpha_composite(canvas)
    check.convert("RGB").save(BASE / "data" / "_sprite_check.png")
    print("check: data/_sprite_check.png")


if __name__ == "__main__":
    sys.exit(main())
