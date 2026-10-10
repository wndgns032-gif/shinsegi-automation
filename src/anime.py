"""AI 애니메이션 만화 이미지 생성 — 참고 채널(인생지혜) 스타일.

2026-10-11 신설. 로이가 참고 채널 스크린샷을 지목하고
"흑백 만화 일러스트로 해줄 수 있냐"고 요청.

## 참고 채널 정밀 분석 (2026-10-11 실측)
- 이미지: **일러스트 애니메이션** (japanese animation film still)
  - 채도중앙 0.133~0.169 (我们去 실사 선화 0.024)
  - 셀 셰이딩 + 클린 라인아트 + 그라데이션 하늘
- 레이아웃: 상단 검은바 7.8% / 이미지 72.2% / 하단 검은바 19.8%
- 자막: **노란 굵은 글씨 + 두꺼운 검정 외곽선** (흰색이 아님)
- 이미지 영역 종횡비 0.779 (정사각에 가까움)

## 왜 실사 사진이 안 되는가
실사 사진으로는 애니메이션만 한 장면을 만들 수 없다.
AI 생성이 유일한 경로이고, Pollinations(무료)가 애니메이션 스타일도 지원한다.

## 무료 한계 (2026-10-10 실측)
- 해상도 **768x768 강제 캡** (요청해도 무시)
- 파일 48KB — 저해상도
- → 흑백 선화 후 morphological 처리로 만화 느낌을 강화한다
  (선 굵게 + 평면화 + 종이 질감)
"""
from __future__ import annotations

import io
import os
import random
import time

import requests
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

POLLINATIONS = "https://image.pollinations.ai/prompt/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
TIMEOUT = 150
ANIM_W, ANIM_H = 768, 768          # 실측: Pollinations 강제 캡


# ─────────────────────────────────────────────────────────────
# 스타일 프롬프트
# ─────────────────────────────────────────────────────────────

# 참고 채널의 시각 언어 — 매 장면 이 접미사를 붙인다
ANIME_SUFFIX = (
    "japanese animation film still, hand painted cel animation, "
    "clean line art, flat color shading, cel shaded, "
    "soft gradient sky, detailed background, "
    "studio ghibli inspired, emotional, cinematic lighting, "
    "horizontal composition, 16:9"
)

# 금지 사항 — flux 는 'not X' 를 'X' 로 읽으므로 부정형 금지
ANIME_NEGATIVE_GUARD = ""


def build_anime_prompt(scene_desc: str, mood: str = "quiet",
                       character: str = "") -> str:
    """장면 설명 → 애니메이션 이미지 프롬프트.

    scene_desc: "a man sitting alone on a park bench at dusk"
    mood: quiet / warm / tense / bright
    character:主角 묘사(선택)
    """
    moods = {
        "quiet":  "peaceful quiet atmosphere, soft evening light, muted colors",
        "warm":   "warm golden hour lighting, nostalgic atmosphere",
        "tense":  "overcast dramatic sky, cold muted tones, heavy atmosphere",
        "bright": "bright daylight, cheerful clear sky, vivid colors",
        "night":  "night scene, deep blue sky, street lamp glow, quiet solitude",
    }
    m = moods.get(mood, moods["quiet"])
    parts = [s.strip() for s in (scene_desc or "").split(",") if s.strip()][:5]
    body = ", ".join(parts)
    char = f"{character}, " if character else ""
    return f"{char}{body}, {m}, {ANIME_SUFFIX}"


# ─────────────────────────────────────────────────────────────
# 생성
# ─────────────────────────────────────────────────────────────

def _get(prompt: str, seed: int, model: str = "flux",
         w: int = ANIM_W, h: int = ANIM_H) -> Image.Image | None:
    url = (f"{POLLINATIONS}{requests.utils.quote(prompt)}"
           f"?width={w}&height={h}&nologo=true&seed={seed}&model={model}")
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        if not r.ok or "image" not in r.headers.get("content-type", ""):
            return None
        if len(r.content) < 12000:
            return None
        im = Image.open(io.BytesIO(r.content))
        im.load()
        return im.convert("RGB")
    except Exception:  # noqa: BLE001
        return None


def crop_to_ratio(im: Image.Image, ratio: float = 0.779) -> Image.Image:
    """참고 채널의 이미지 영역 종횡비(0.779)에 맞춰 크롭."""
    w, h = im.size
    cur = w / h
    if cur > ratio:                    # 너무 넓다 → 좌우 자르기
        nw = int(h * ratio)
        x0 = (w - nw) // 2
        im = im.crop((x0, 0, x0 + nw, h))
    elif cur < ratio:                  # 너무 좁다 → 상하 자르기
        nh = int(w / ratio)
        y0 = int((h - nh) * 0.42)      # 위쪽 slightly (하단 여백 확보)
        im = im.crop((0, y0, w, y0 + nh))
    return im


def crop_watermark(im: Image.Image) -> Image.Image:
    """Pollinations 하단 워터마크 제거 — 하단 12% 크롭."""
    w, h = im.size
    return im.crop((0, 0, w, int(h * 0.88)))


def gen_anime_scene(scene_desc: str, dest: Path, seed: int = 0,
                    mood: str = "quiet", character: str = "",
                    tries: int = 3, sleep_s: float = 22.0) -> bool:
    """애니메이션 장면 1장 생성 → dest 저장. 성공 시 True."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    prompt = build_anime_prompt(scene_desc, mood, character)
    for attempt in range(tries):
        model = "flux" if attempt % 2 == 0 else "turbo"
        im = _get(prompt, seed + attempt * 977, model)
        if im is None:
            if attempt < tries - 1:
                time.sleep(sleep_s)
            continue
        im = crop_watermark(im)
        im = crop_to_ratio(im)
        im.save(dest, "JPEG", quality=92, optimize=True)
        return True
    return False


def anime_to_manga(im_path: Path, dest: Path) -> None:
    """애니메이션 → 흑백 만화 변환 (로이 요청: "흑백 만화 일러스트로").

    애니메이션을 그대로 두면 참고 채널과 다른 색채.
    흑백 + 선 강조로 **만화책 느낌**을 만든다.
    """
    im = Image.open(im_path).convert("RGB")
    g = ImageOps.autocontrast(im.convert("L"), cutoff=1)
    # 자외선으로 선(선화)을 강하게 — 만화의 잉크선 강조
    g = g.filter(ImageFilter.UnsharpMask(radius=2.0, percent=170, threshold=2))
    g = g.filter(ImageFilter.UnsharpMask(radius=5, percent=80, threshold=3))
    # 선을 또렷하게: 대비 + 살짝 posterize → 평면 색면(cel) 느낌
    g = ImageEnhance.Contrast(g).enhance(1.22)
    g = g.point(lambda v: min(255, int(v * 1.02)))
    # 시피아(따뜻한 종이색) 톤
    out = ImageOps.colorize(g, black="#181410", white="#faf6ec")
    out.save(dest, "JPEG", quality=93, optimize=True)


