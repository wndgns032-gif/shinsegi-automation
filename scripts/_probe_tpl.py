"""템플릿 빈 공간 정밀 측정 — 캐릭터(전경) 픽셀을 피해
중앙 밴드에서 가장 큰 가로 사각형을 찾는다."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from PIL import Image  # noqa: E402

REP = BASE / "_probe_report.txt"
lines: list[str] = []


def out(s: str) -> None:
    lines.append(s)


img = Image.open(BASE / "assets" / "template_card.png").convert("RGB")
W, H = img.size
px = img.load()

# 배경(크림) 색 — 좌상단 구석에서 샘플
bg = px[540, 130]  # 화면 중앙 상단 근처 배경
out(f"template {W}x{H}, bg sample {bg}")


def is_fg(x: int, y: int) -> bool:
    r, g, b = px[x, y]
    return abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > 90


# 1) 행별 전경 너비 프로파일 (중앙 밴드 y 500~1200)
for y in range(500, 1201, 50):
    row_fg = [x for x in range(0, W, 4) if is_fg(x, y)]
    # 연속 구간 요약
    segs = []
    if row_fg:
        start = prev = row_fg[0]
        for x in row_fg[1:]:
            if x - prev > 20:
                segs.append((start, prev))
                start = x
            prev = x
        segs.append((start, prev))
    out(f"y={y}: fg segments (x4 step) = {segs}")

# 2) 후보 사각형 검사 — 전경 픽셀 수와 침범 위치
candidates = [
    ("current", 300, 748, 820, 1040),
    ("A 520x365", 290, 725, 810, 1090),
    ("B 530x368", 285, 725, 815, 1093),
    ("C 540x360", 280, 730, 820, 1090),
    ("D tall", 295, 700, 815, 1090),
    ("E wide-up", 250, 620, 860, 950),
]
for name, x0, y0, x1, y1 in candidates:
    hits = 0
    worst = []
    step = 2
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            if is_fg(x, y):
                hits += 1
                if len(worst) < 8:
                    worst.append((x, y))
    total = ((x1 - x0) // step) * ((y1 - y0) // step)
    out(f"[{name}] rect=({x0},{y0})-({x1},{y1}) size={x1-x0}x{y1-y0} fg_ratio={hits/total:.4f} first_hits={worst}")

# 3) 지정 열(x)에서 전경이 시작/끝나는 y — 왼쪽·오른쪽 경계 탐색
for x in (280, 290, 300, 810, 820, 830, 850):
    ys = [y for y in range(650, 1150, 2) if is_fg(x, y)]
    if ys:
        runs = []
        s = p = ys[0]
        for y in ys[1:]:
            if y - p > 10:
                runs.append((s, p))
                s = y
            p = y
        runs.append((s, p))
        out(f"x={x}: fg runs (y) = {runs}")
    else:
        out(f"x={x}: clear from y650 to y1150")

REP.write_text("\n".join(lines), encoding="utf-8")
