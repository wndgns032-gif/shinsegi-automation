"""IG 카드 렌더러 — 고정 지브리 템플릿, 1080x1350.

규칙: assets/template_card.png 는 **절대 변형하지 않는다.**
매 카드는 템플릿 원본을 그대로 로드한 뒤, 가운데 텍스트 영역과
고정 위치 배지(상단 태그·하단 페이지 번호)만 PIL로 얹는다.
템플릿 파일이 없으면 파이프라인을 중단시킨다(임시 배경으로 대체 금지 — 템플릿 고정 보장).

1장 = 명언 카드: 명언 본문 + 구분선 + 화자(인물) 를 세이지 그린으로 표기.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = BASE_DIR / "assets" / "template_card.png"

W, H = 1080, 1350
# 텍스트 안전 영역 (우상단 선생님·좌하단 토끼 소녀·꽃 장식을 침범하지 않는 가운데 공간)
TEXT_BOX = (270, 320, 980, 1150)
INK = (74, 62, 48)          # 따뜻한 잉크 브라운
QUOTE_INK = (58, 50, 40)    # 명언 본문 (조금 더 진하게)
PANEL = (255, 252, 244, 208)  # 반투명 크림 패널
SAGE = (122, 148, 124)      # 세이지 그린 배지
FONT_CANDIDATES = {
    "ko": [
        # Windows
        "C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf",
        # Linux (apt: fonts-nanum)
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ],
    "zh-cn": [
        # Windows
        "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
        # Linux (apt: fonts-noto-cjk)
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ],
    "default": [
        # Windows
        "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
}
# 상단 배지 문구 (언어별) — 명언 카드뉴스
TAGS = {
    "en": "DAILY WISDOM",
    "ko": "오늘의 명언",
    "zh-cn": "今日名言",
    "fr": "CITATION DU JOUR",
}
TAG_TEXT = TAGS["en"]


def _font(lang: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES.get(lang, FONT_CANDIDATES["default"]):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    """픽셀 너비 기준 줄바꿈. 공백 없는 CJK 문장은 글자 단위로 자른다."""
    lines: list[str] = []
    for para in text.split("\n"):
        tokens = para.split(" ") if " " in para else list(para)
        sep = " " if " " in para else ""
        line = ""
        for tok in tokens:
            trial = (line + sep + tok) if line else tok
            if draw.textlength(trial, font=font) <= max_w:
                line = trial
            else:
                if line:
                    lines.append(line)
                line = tok
        lines.append(line)
    return [l for l in lines if l.strip()]


def _fit_lines(draw: ImageDraw.ImageDraw, text: str, lang: str, max_w: int, max_h: int,
               hi: int = 58, lo: int = 36):
    """세로 영역에 맞을 때까지 폰트 크기를 줄여가며 줄 목록을 만든다."""
    for size in range(hi, lo, -2):
        font = _font(lang, size)
        line_h = int(size * 1.5)
        lines = _wrap(draw, text, font, max_w)
        if lines and line_h * len(lines) <= max_h:
            return font, line_h, lines
    font = _font(lang, lo + 2)
    return font, int((lo + 2) * 1.5), _wrap(draw, text, font, max_w)


def _draw_quote_card(meas, od, text, author, lang, box):
    """1장 = 명언 + 구분선 + 화자. 패널 높이를 반환해 배지와 겹치지 않게 한다."""
    bx0, by0, bx1, by1 = box
    max_w, max_h = bx1 - bx0, by1 - by0
    gap, attr_size = 48, 40
    attr_h = int(attr_size * 1.4)

    font, line_h, lines = _fit_lines(meas, text, lang, max_w, max_h - gap - attr_h,
                                     hi=70, lo=40)
    block_h = line_h * len(lines) + gap + attr_h
    pad_x, pad_y = 44, 36
    top = by0 + (max_h - block_h) / 2
    od.rounded_rectangle([bx0 - pad_x, top - pad_y, bx1 + pad_x, top + block_h + pad_y],
                         radius=36, fill=PANEL)

    cx = (bx0 + bx1) / 2
    y = top
    for line in lines:
        lw = meas.textlength(line, font=font)
        od.text((cx - lw / 2, y), line, font=font, fill=QUOTE_INK)
        y += line_h

    # 구분선 (짧은 세이지 라인)
    od.rounded_rectangle([cx - 70, y + gap * 0.35, cx + 70, y + gap * 0.35 + 5],
                         radius=3, fill=(*SAGE, 210))

    attr_font = _font(lang, attr_size)
    attr = f"— {author}"
    aw = meas.textlength(attr, font=attr_font)
    od.text((cx - aw / 2, y + gap), attr, font=attr_font, fill=SAGE)
    return block_h


def render_cards(texts: list[str], out_dir: Path, lang: str, tag: str | None = None,
                 author: str | None = None) -> list[Path]:
    """고정 템플릿 위에 텍스트만 합성해 카드를 렌더링한다.

    author 가 주어지면 1장을 '명언 + 화자' 레이아웃으로 그린다.
    """
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"고정 템플릿 없음: {TEMPLATE_PATH} — 임시 배경 대체는 금지(템플릿 고정 원칙). "
            "assets/template_card.png 를 복구한 뒤 다시 실행하라."
        )
    template = Image.open(TEMPLATE_PATH).convert("RGB")
    if template.size != (W, H):
        raise ValueError(f"템플릿 크기 비정상: {template.size} (기대 {W}x{H})")

    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(texts)
    tag = tag or TAGS.get(lang, TAG_TEXT)
    author = (author or "").strip()
    paths: list[Path] = []

    for i, text in enumerate(texts, start=1):
        img = template.copy()
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)

        meas = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        bx0, by0, bx1, by1 = TEXT_BOX
        max_w = bx1 - bx0
        max_h = by1 - by0

        if i == 1 and author:
            _draw_quote_card(meas, od, text, author, lang, TEXT_BOX)
        else:
            # 1) 본문: 자동 폰트 맞춤 → 패널 → 텍스트
            font, line_h, lines = _fit_lines(meas, text, lang, max_w, max_h)
            block_h = line_h * len(lines)
            pad_x, pad_y = 44, 36
            top = by0 + (max_h - block_h) / 2
            od.rounded_rectangle([bx0 - pad_x, top - pad_y, bx1 + pad_x, top + block_h + pad_y],
                                 radius=36, fill=PANEL)

            cx = (bx0 + bx1) / 2
            y = top
            for line in lines:
                lw = meas.textlength(line, font=font)
                od.text((cx - lw / 2, y), line, font=font, fill=INK)
                y += line_h

        # 2) 상단 좌측 태그 배지 (고정 위치)
        tag_font = _font(lang, 34)
        tw = meas.textlength(tag, font=tag_font)
        od.rounded_rectangle([64, 74, 64 + tw + 56, 136], radius=31, fill=(*SAGE, 235))
        od.text((64 + 28, 88), tag, font=tag_font, fill=(255, 255, 255, 255))

        # 3) 하단 우측 페이지 배지 (고정 위치)
        page_font = _font(lang, 32)
        page = f"{i} / {total}"
        pw = meas.textlength(page, font=page_font)
        od.rounded_rectangle([W - 64 - pw - 56, H - 136, W - 64, H - 74], radius=31, fill=(*SAGE, 235))
        od.text((W - 64 - pw - 28, H - 122), page, font=page_font, fill=(255, 255, 255, 255))

        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        path = out_dir / f"card_{i}.png"
        img.save(path, "PNG")
        paths.append(path)
    return paths
