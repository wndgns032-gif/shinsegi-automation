"""AI 애니메이션 만화 이미지 생성 — 참고 채널(인생지혜) 스타일.

2026-10-11 신설. 로이가 참고 채널 스크린샷을 지목하고
"흑백 만화 일러스트로 해줄 수 있냐"고 요청.

## 참고 채널 정밀 분석 (2026-10-11 실측)
- 이미지: **일러스트 애니메이션** (japanese animation film still)
  - 채도중앙 0.133~0.169 (우리는 실사 선화 0.024)
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
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat

POLLINATIONS = "https://image.pollinations.ai/prompt/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
TIMEOUT = 150
ANIM_W, ANIM_H = 768, 1365         # 9:16 세로 — 렌더 규격(1152x2048)과 같은 비율.
# ⚠️ 이전엔 768x768(정사각)로 요청한 뒤 세로로 잘라내서,
#    양옆이 날아가고 인물 얼굴만 남았다. 세로로 요청해야 wide 구도가 산다.


# ─────────────────────────────────────────────────────────────
# 스타일 프롬프트
# ─────────────────────────────────────────────────────────────

# 참고 채널의 시각 언어 — 매 장면 이 접미사를 붙인다
# ⚠️ 2026-10-11 실측 수정 — 이전 suffix 의 문제 3가지
#   1) "wide shot" 과 "medium shot" 이 **동시에** 들어가 서로 상쇄됐다
#      → flux 가 medium(얼굴 클로즈업) 쪽을 골라 전 장면이 얼굴만 나왔다
#   2) "16:9" 를 요청했는데 렌더는 1152x2048(9:16) → 가로 그림을 세로로
#      잘라내니 양옆이 날아가고 인물만 남았다
#   3) 토큰이 55단어로 너무 길어 **장면 내용이 프롬프트에서 밀렸다**
#      (skill 실측: 스타일 토큰 60단어 → flux 가 장면을 버림)
#   → 세로 구도로 통일하고, 토큰을 20단어 수준으로 줄였다.
ANIME_SUFFIX = (
    "japanese anime film still, bold clean outlines, flat cel shading, "
    # ⚠️ 2026-10-11 4차 실측: **10장 중 5~6장이 '빈 실내' 로 나왔다.**
    #    실측 프레임: 문 없는 복도, 사람 없는 방, 빈 골목.
    #    우화인데 사람이 없으니 이야기가 성립하지 않는다(조회수에 직격).
    #    원인은 flux 가 "one person seen from behind" 를 **선택적**으로 해석 —
    #    "environment fills the frame" 이랑 만나면 그냥 배경만 그린다.
    #    → 인물 강제 표현은 build_anime_prompt() 앞쪽(_FIG)으로 옮겼고,
    #      여기서는 스타일만 남긴다(중복은 프롬프트를 불필요하게 길게 만든다).
    "environment fills the frame, vertical composition"
)

# 금지 사항 — flux 는 'not X' 를 'X' 로 읽으므로 부정형 금지
ANIME_NEGATIVE_GUARD = ""

# ⚠️ 2026-10-11 실측 2차: 장면 묘사가 살아났는데도 **10장 중 5장이 얼굴 클로즈업**.
#    원인은 LLM 이 쓴 묘사 자체에 초상 유발 표현이 섞였기 때문
#    ("over the shoulder", "his face", "close-up" ... flux 는 이걸 인물 중심으로 해석).
#    → 코드에서 결정적으로 제거한다. 프롬프트 지시만으로는 새는 걸 막을 수 없다.
_PORTRAIT_WORDS = (
    "close-up", "closeup", "close up", "portrait", "headshot", "bust shot",
    "face", "facial", "over the shoulder", "over-the-shoulder",
    "looking at the camera", "looking into the camera",
    "his eyes", "her eyes", "his hands", "her hands",
    "upper body", "medium shot", "chest up",
)


def _strip_portrait(text: str) -> str:
    """초상 클로즈업을 유발하는 토큰 제거(대소문자 무시, 콤마 단위)."""
    kept = []
    for chunk in (text or "").split(","):
        low = chunk.lower()
        if any(w in low for w in _PORTRAIT_WORDS):
            continue
        kept.append(chunk.strip())
    return ", ".join(c for c in kept if c)


def build_anime_prompt(scene_desc: str, mood: str = "quiet",
                       character: str = "") -> str:
    """장면 설명 → 애니메이션 이미지 프롬프트.

    scene_desc: "a man sitting alone on a park bench at dusk"
    mood: quiet / warm / tense / bright
    character: 주인공 묘사(선택)
    """
    moods = {
        "quiet":  "soft evening light",
        "warm":   "warm golden hour light",
        "tense":  "overcast sky, cold tones",
        "bright": "bright clear daylight",
        "night":  "night, street lamp glow",
    }
    m = moods.get(mood, moods["quiet"])
    # ⚠️ 이전엔 [:5] 였다. 스타일 토큰이 앞에 붙어 오면 장면이 통째로 잘렸다.
    #    (2026-10-11 실측 — 열 장면이 전부 같은 얼굴이 된 원인)
    #    이제 image_prompt 는 순수 묘사지만, 방어적으로 여유를 둔다.
    # 초상 유발 토큰을 먼저 걷어낸다 (2026-10-11 2차 실측)
    clean = _strip_portrait(scene_desc)
    parts = [s.strip() for s in clean.split(",") if s.strip()][:10]
    body = ", ".join(parts)
    # ⚠️ 2026-10-11: 캐릭터를 **뒤로** 옮겼다.
    # skill 실측 — 캐릭터를 앞에 넣으면 flux 가 클로즈업으로 고정된다.
    # 장면 묘사가 먼저, 인물은 뒤에.
    char = f", {character}" if character else ""
    # ⚠️ 2026-10-11 3차 실측: "장소 먼저 + 인물 뒤" 만으로는 부족했다.
    #    flux 는 "sitting at a desk" 같은 동작구를 보면 인물로 줌인한다.
    #    → **거리 지시를 맨 앞에** 둔다(앞 토큰의 가중치가 가장 세다).
    # ⚠️ 2026-10-11 5차 실측 — 인물이 **있긴 하지만 너무 커서** 다시 클로즈업이 됐다.
    #    실측: 복도/방 장면에서 사람이 화면 중앙을 Almost 꽉 채웠다.
    #    flux 는 "figure" 를 보면 자동으로 줌인하므로 거리 표현이 반드시 필요하다.
    #    → 비율을 직접 명시("occupies only 10% of the frame height")한다.
    #    단 "tiny" 만 쓰면 잘려나가므로 수치를 함께 준다.
    _FIG = ("small distant silhouetted figure seen from behind, full body, "
            "occupying only 10% of the frame height, "
            "standing far away in the lower third of the frame")
    if character:
        # 캐릭터가 있으면 장소 묘사는 뒤로 물리고 인물을 앞에 둔다
        return (f"wide angle long shot, {_FIG}, {character}, {body}, "
                f"{m}, {ANIME_SUFFIX}")
    return f"wide angle long shot, {_FIG}, {body}, {m}, {ANIME_SUFFIX}"


# ─────────────────────────────────────────────────────────────
# 생성
# ─────────────────────────────────────────────────────────────

def _get(prompt: str, seed: int, model: str = "flux",
         w: int = ANIM_W, h: int = ANIM_H) -> Image.Image | None:
    # ⚠️ 2026-10-11 실측: 익명 호출은 402(쿼터)를 자주 뱉는다.
    #   Pollinations 는 `referrer` 를 주면 요청을 프론트엔드로 인정해
    #   한도를 완화한다. 토큰이 있으면 그것도 함께 붙인다(선택).
    tok = os.getenv("POLLINATIONS_TOKEN", "").strip()
    ref = os.getenv("POLLINATIONS_REFERRER", "shinsegi-automation").strip()
    url = (f"{POLLINATIONS}{requests.utils.quote(prompt)}"
           f"?width={w}&height={h}&nologo=true&seed={seed}&model={model}"
           f"&referrer={requests.utils.quote(ref)}")
    if tok:
        url += f"&token={requests.utils.quote(tok)}"
    hdr = dict(UA)
    hdr["Referer"] = f"https://{ref}.local/"
    try:
        r = requests.get(url, headers=hdr, timeout=TIMEOUT)
        if not r.ok or "image" not in r.headers.get("content-type", ""):
            return None
        if len(r.content) < 12000:
            return None
        im = Image.open(io.BytesIO(r.content))
        im.load()
        return im.convert("RGB")
    except Exception:  # noqa: BLE001
        return None


def crop_to_ratio(im: Image.Image, ratio: float = 0.779,
                  out_size: tuple[int, int] | None = None) -> Image.Image:
    """참고 채널의 이미지 영역 종횡비(0.779)에 맞춰 크롭.

    out_size 를 주면 최종 크기까지 통일한다.
    ⚠️ 2026-10-11: 크기를 통일하지 않으면 check_fable_images 의
       "크기 편차" 검사에 걸려 전 장면이 탈락했다.
    """
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
    if out_size:
        im = im.resize(out_size, Image.LANCZOS)
    return im


def crop_watermark(im: Image.Image) -> Image.Image:
    """Pollinations 하단 워터마크 제거 — 하단 12% 크롭."""
    w, h = im.size
    return im.crop((0, 0, w, int(h * 0.88)))


def gen_anime_scene(scene_desc: str, dest: Path, seed: int = 0,
                    mood: str = "quiet", character: str = "",
                    tries: int = 5, sleep_s: float = 26.0) -> bool:
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
        # 렌더 규격(1152x2048)으로 통일 — 검수 "크기 편차" 방지
        im = crop_to_ratio(im, out_size=(1152, 2048))
        im.save(dest, "JPEG", quality=92, optimize=True)
        return True
    return False


def anime_to_manga(im_path: Path, dest: Path) -> None:
    """애니메이션 → 흑백 만화 변환 (로이 요청: "흑백 만화 일러스트로").

    ⚠️ 실측 실패(2026-10-11): 이전 버전은 대비/블렌드만 강화해서
    **컬러가 그대로 남았다**(장면1 이 컬러 그대로 나옴).
    → 반드시 "완전 그레이스케일 → 대비 → 선 강조 → 시피아" 순서로 간다.

    애니메이션을 그대로 두면 참고 채널과 다른 색채.
    흑백 + 선 강조로 **만화책 느낌**을 만든다.
    """
    im = Image.open(im_path).convert("RGB")

    # 1) 완전 그레이스케일 — L 변환 (이걸 빼면 컬러가 남는다)
    g = im.convert("L")

    # 2) autocontrast (cutoff 2 — 너무 강하게 먹지 않게)
    g = ImageOps.autocontrast(g, cutoff=2)

    # 3) 대비 강화 — 평면한 애니메이션에 입체감을 준다
    g = ImageEnhance.Contrast(g).enhance(1.38)

    # 3-1) 노출 보정 (2026-10-11 3차 실측)
    #   flux 는 야경·실내 장면을 매우 어둡게 뽑는다(측정: 평균 59~87, 검은픽셀 44~62%).
    #   참고 채널 프레임은 훨씬 밝다. 어두우면 쇼츠에서 이탈한다.
    #   → 기준 밝기(105)에 못 미치면 끌어올린다. 상한 1.45배(노이즈 증폭 방지).
    _mean = ImageStat.Stat(g).mean[0]
    if _mean < 105:
        g = ImageEnhance.Brightness(g).enhance(min(1.45, 105.0 / max(_mean, 30.0)))
        g = ImageOps.autocontrast(g, cutoff=1)

    # 4) 선(잉크선) 강조 — 자외선 2단. 만화의 윤곽선을 만든다.
    g = g.filter(ImageFilter.UnsharpMask(radius=1.5, percent=280, threshold=1))
    g = g.filter(ImageFilter.UnsharpMask(radius=4.0, percent=150, threshold=2))

    # 5) 시피아(따뜻한 종이색) 톤 — 흑백만화의 인쇄 질감
    out = ImageOps.colorize(g, black="#141109", white="#faf7f0")
    out.save(dest, "JPEG", quality=93, optimize=True)
