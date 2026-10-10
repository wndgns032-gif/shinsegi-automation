"""우화 숏폼 렌더러 v6 — 1080x1920 세로 쇼츠 (2026-10-05 전면 재구축).

참고 영상(youtube.com/shorts/V2UtKas1xAA) 스타일:
  상단 고정 훅 바(검정 + 흰 글씨 + 주황 강조어) → 풀블리드 일러스트 + 켄번스
  → 하단 자막(흰 글씨 검정 테) → 마지막 장면에 명언 카드 + CTA → BGM 상시 + 덕킹.

전 과정 무료: Pollinations 이미지 / 로컬 TTS / ffmpeg 켄번스·크로스페이드 /
numpy 합성 BGM. 장면 이미지는 언어 무관이라 1세트를 4개 언어가 공유하고
낭독·자막·훅 바만 언어별로 만든다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from . import bgm, cards, tts

LANGS = ["en", "ko", "zh-cn", "fr"]

W, H = 1080, 1920                 # 최종 출력
FPS = 30
RENDER_W, RENDER_H = 2160, 3840    # 켄번스 소스 배율 (2x)
IMG_W, IMG_H = 1152, 2048          # Pollinations 요청 크기 (9:16)
XFADE = 0.55                      # 장면 전환 크로스페이드(초)
WATERMARK_CROP = 0.92             # 하단 워터마크 잘라내기 (상위 92%)
SCENE_PAD = 0.35                  # 장면당 낭독 뒤 여유(초)
HOOK_LEAD = 0.9                   # 훅 장면 앞 여유(초) — 텍스트 인지 시간
# 2026-10-08 로이 요청: 쇼츠 길이는 40초 이상 1분 이하로 맞춘다.
#   짧으면 장면 여유를 늘리고, 길면 낭독을 살짝 빠르게(atempo) 압축한다.
MIN_TOTAL = 40.0
MAX_TOTAL = 60.0
OUTRO_TAIL = 0.7                  # 아웃트로 끝 여유(초)

# 낭독 배속 (2026-10-04 로이 피드밚: 1.2배속) — TTS 후 ffmpeg atempo 로 처리
VOICE_SPEED = float(os.getenv("FABLE_VOICE_SPEED", "1.2"))

ORANGE_ASS = "&H4DA9FF&"          # #FFA94D (ASS 는 BGR)
GOLD_ASS = "&HB0D8E8&"            # #E8D8B0 — 아웃트로 화자 색

_ASS_FONTS = {
    "ko": ["Malgun Gothic", "Noto Sans CJK KR", "Nanum Gothic"],
    "zh-cn": ["Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Zen Hei"],
    "en": ["Georgia", "DejaVu Serif", "Liberation Serif"],
    "fr": ["Georgia", "DejaVu Serif", "Liberation Serif"],
}


def _fontsdir() -> str:
    """Linux runner 와 Windows 양쪽 폰트 경로 — 없으면 빈 문자열(fontconfig 에 위임)."""
    cands = [
        "/usr/share/fonts",                # Linux 표준
        "/usr/local/share/fonts",          # Linux 로컬 설치
        "C:/Windows/Fonts",                # Windows
    ]
    import os as _os
    for c in cands:
        if _os.path.isdir(c):
            return c.replace("\\", "/")
    return ""


def _ffpath(p: str) -> str:
    """ffmpeg 필터 인자용 경로 이스케이프 (2026-10-07 추가).

    `subtitles=` / `fontsdir=` 같은 필터 옵션 안에서는 ':' 가 구분자로 파싱되므로
    Windows 드라이브 문자까지 이스케이프(\\:)해야 한다. 안 하면
    `Error opening output file ... Invalid argument` 로 전체 렌더가 실패한다.
    역슬래시도 ffmpeg 의 escape 문자이므로 함께 정리한다.
    """
    return str(p).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _ass_font(lang: str) -> str:
    """언어별 첫 번째 설치 폰트를 찾아 반환 — 못 찾으면 언어 기본값."""
    try:
        import fontconfig  # type: ignore
    except Exception:  # noqa: BLE001
        pass
    return _ASS_FONTS.get(lang, ["DejaVu Sans"])[0]


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def _run(args: list[str], label: str) -> None:
    r = subprocess.run(args, capture_output=True, text=True, errors="ignore")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg [{label}] 실패: {r.stderr[-400:]}")


def _audio_duration(path: Path) -> float:
    r = subprocess.run(
        [_ffmpeg_exe(), "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, errors="ignore")
    m = re.findall(r"time=(\d+):(\d+):(\d+\.?\d*)", r.stderr)
    if not m:
        return 6.0
    h, mm, ss = m[-1]
    return int(h) * 3600 + int(mm) * 60 + float(ss)


# ─────────────────────────────────────────────────────────────
# 켄번스 — 세로 화면용 6종 로테이션
# ─────────────────────────────────────────────────────────────
def _motion(i: int, frames: int) -> str:
    """장면 카메라 무빙 — Ken Burns.

    2026-10-08: 로이 요청 "애니메이션 느낌" 적용.
    실사 영상처럼 보이지 않게 하려면:
      - 줌 범위를 좁게 (예전 1.14 → 1.10) — 과한 줌은 '짧은 영상 티'
      - 속도를 느리게 (0.00040 → 0.00028)
      - 이동은 한 방향으로 부드럽게 (컷 단위 점프를 줄임)
    """
    k = i % 6
    if k == 0:      # 천천히 푸시인 (또박또박 확대)
        z, x, y = "min(1+0.00028*on,1.10)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif k == 1:    # 천천히 풀아웃
        z, x, y = "max(1.10-0.00028*on,1.001)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif k == 2:    # 위→아래 천천히 팬
        z = "1.09"
        x, y = "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(on/{f})".format(f=frames)
    elif k == 3:    # 아래→위 천천히 팬
        z = "1.09"
        x, y = "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/{f})".format(f=frames)
    elif k == 4:    # 아주 느린 대각선 우상향
        z = "min(1+0.00024*on,1.09)"
        x, y = ("(iw-iw/zoom)*(on/{f})".format(f=frames),
                "(ih-ih/zoom)*(1-on/{f})".format(f=frames))
    else:           # 아주 느린 대각선 좌하향
        z = "min(1+0.00024*on,1.09)"
        x, y = ("(iw-iw/zoom)*(1-on/{f})".format(f=frames),
                "(ih-ih/zoom)*(on/{f})".format(f=frames))
    # ⚠️ zoompan 은 d:x:y:z:s:d:fps 옵션만 받는다 (실측 2026-10-08).
    #    'dither' 같은 옵션을 넣으면 `filter 'zoompan': Option not found` 로 죽는다.
    return (f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:"
            f"s={W}x{H}:fps={FPS}")


def _film_fx() -> str:
    """필름 마감 체인 — 애니메이션 흑백 느낌 (ffmpeg 내장 · 무료).

    2026-10-07: 장면 이미지를 흑백 통일 → saturation 1.0.
    2026-10-08: 로이 요청 "애니메이션 흑백 느낌" 적용.

    애니메이션처럼 보이게 하는 핵심:
      1) curves — 하이라이트/섀도를 눌러 평평한 사진 대비를 제거 (만화 특유)
      2) lut-ish 톤 — 그림자 쪽에 약한 청록, 하이라이트에 약한 세피아
         (실사 재 촬영과 다른 '붓으로 그린' 인상)
      3)线条 강조 — unsharp 강하게 + convolution sharpen
      4) 필름 그레인 + 비네테 (기존)
    """
    return (
        # 선화: 가장자리 선을 날카롭게 (만화는 윤곽이 또렷하다)
        "unsharp=7:7:0.75:7:7:0.0,"
        # 톤 곡선: 하이라이트를 살리고 그림자를 눌러 그라데이션에 깊이를 만든다
        "curves=all='0/0.045 0.25/0.20 0.5/0.52 0.75/0.84 1/0.965',"
        # 채도 미세 감소 + 대비 (만화는 채도가 낮고 명암이 강하다)
        "eq=contrast=1.14:saturation=0.92:brightness=0.012:gamma=1.02,"
        # 그림자에 약한 냉색, 하이라이트에 약한 온색 — 종이 질감 느낌
        "colorbalance=rs=-0.02:gs=0:bs=0.045:rm=0.018:gm=0.006:bm=-0.012:"
        "rh=0.022:gh=0.010:bh=-0.020,"
        # 필름 마감
        "vignette=0.42,"
        "noise=alls=3.2:allf=t"
    )


# ─────────────────────────────────────────────────────────────
# 1) 장면 이미지 — Pollinations (무료·키 불필요) + 로컬 폴백
# ─────────────────────────────────────────────────────────────
def _to_monochrome(path: Path) -> None:
    """장면 이미지를 흑백으로 통일 (2026-10-07 로이 지시: "흑백 느낌으로 통일").

    프롬프트만으로는 모델이 장면마다 다른 색/밝기를 뽑아내므로, **최종 보장을 위해
    렌더 직전에 PIL로 반드시 그레이스케일 변환한다.** 전체 10장면이 같은 톤이 되고,
    텍스트(자막·명언카드)와 그림 사이의 대비도 일정해져 가독성이 올라간다.

    1) 액자/매트 여백 제거 — 모델이 'vintage etching' 을 요구하면 액자·테두리·점형 여백을
       자꾸 그린다. 가장자리 9%씩 잘라내면 사라진다.
    2) 완전 그레이스케일
    3) autocontrast — 장면별 명도 차이 흡수(어두운 장면/밝은 장면 격차 축소)
    4) 대비 소폭 강화 — 평평한 회색 방지
    5) 아주 미세한 세피아 톤 — 기계적 그레이가 아니라 "양피지 같은" 인쇄물 질감

    ⚠️ **1번 크롭은 멱등(idempotent)하지 않다** — 호출할 때마다 9%씩 계속 줄어든다.
       Pollinations 로 **새로 받은 이미지에만** 적용할 것.
       이미 처리된 캐시 이미지에 재적용 금지(해상도 손실).
       `gen_images()` 는 캐시 히트 분기에서 이 함수를 호출하지 않도록 주의할 것.
    """
    try:
        img = Image.open(path).convert("RGB")
        # ── 액자/테두리 제거 (중앙 영역만 유지) ──
        # 모델이 그리는 액자는 대부분 가장자리 6~10% + 상하 매트. 9%씩 잘라내면 사라진다.
        w, h = img.size
        mx, my = int(w * 0.09), int(h * 0.09)
        if mx > 4 and my > 4:
            img = img.crop((mx, my, w - mx, h - my))
        img = ImageOps.grayscale(img)
        img = ImageOps.autocontrast(img, cutoff=1)
        img = ImageEnhance.Contrast(img).enhance(1.08)
        # 세피아 미세 톤 (R > G > B) — 살짝 따뜻한 흑백
        # (grayscale() 결과는 L 모드라 split()이 1채널 → RGB 변환 후 분리해야 한다)
        img = img.convert("RGB")
        r, g, b = img.split()
        r = r.point(lambda v: min(255, v + 6))
        b = b.point(lambda v: max(0, v - 6))
        img = Image.merge("RGB", (r, g, b))
        img.save(path, "JPEG", quality=90)
    except Exception as e:  # noqa: BLE001
        print(f"  [fable] 흑백 변환 실패 (원본 유지): {type(e).__name__}")


def _fetch_one(i: int, p: str, out_dir: Path, total: int,
               seed_base: int) -> Path:
    """이미지 1장 생성 — 캐시 확인 → Pollinations 조회 → 실패 시 로컬 폴백.

    ⚠️ 2026-10-09 실측 근본 원인:
       Pollinations 익명 쿼터는 **IP 당 동시 1건만** 통과시킨다.
       동시 4개 요청 → 1개 200 + 3개 402 (2바이트) 로 확인됨.
       즉 "빠르게 하려고 병렬화"가 오히려 75% 실패를 만든 것이었다.

       → 순차 호출로 바꾸고, 실패 시 **다른 모델(turbo/flux schnell)** 로 재시도한다.
       → 402 는 쿼터이므로 5 분 정도 쉬면 회복된다.
    """
    dest = out_dir / f"scene{i + 1}.jpg"
    mark = out_dir / f"scene{i + 1}.mono"
    if dest.exists() and dest.stat().st_size > 20000:
        if not mark.exists():
            _to_monochrome(dest)
            mark.write_text("1", encoding="utf-8")
        print(f"  [fable] 이미지 {i + 1}/{total} 캐시")
        return dest

    # 모델 후보 순서 — 앞의 것이 실패하면 다음으로 넘긴다.
    # (flux 가 품질 좋지만 turbo 도 결과가 좋아서 순환 사용)
    # 4회 시도 × 20초 백오프 = 최대 60초. 10장이면 최악에도 10분 안이다.
    models = ("turbo", "flux", "turbo", "flux")
    ok = False
    for attempt, model in enumerate(models, start=1):
        url = ("https://image.pollinations.ai/prompt/"
               + requests.utils.quote(p)
               + f"?width={IMG_W}&height={IMG_H}&nologo=true"
                 f"&seed={seed_base + i * 37 + 1000}&model={model}")
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=150)
            ct = r.headers.get("content-type", "")
            if r.ok and "image" in ct and len(r.content) > 20000:
                dest.write_bytes(r.content)
                _to_monochrome(dest)  # ← 흑백 통일 (프롬프트 무시 대비)
                mark.write_text("1", encoding="utf-8")
                print(f"  [fable] 이미지 {i + 1}/{total} OK "
                      f"({len(r.content) // 1024}KB, {model}, 흑백)")
                ok = True
                break
            print(f"  [fable] 이미지 {i + 1} 시도{attempt}({model}) "
                  f"실패 HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            print(f"  [fable] 이미지 {i + 1} 시도{attempt}({model}) "
                  f"오류 {type(e).__name__}")
        # ⚠️ 2026-10-09 실측 쿼터 회복 속도:
        #   성공 직후 연속 요청 → 402 (1.1초 만에 실패)
        #   20초 대기 후 → 200 복구
        #   즉 402 는 '쿼터 소진' 이고 **20초만 기다리면 회복**된다.
        #   모델을 바꿔도 쿼터는 회복되지 않으므로 시간만 쓴다.
        if attempt < len(models):
            time.sleep(20)
    if not ok:
        _fallback_image(dest, i)
        _to_monochrome(dest)  # 폴백도 흑백으로
        mark.write_text("1", encoding="utf-8")
        print(f"  [fable] 이미지 {i + 1} 로컬 폴백 (Pollinations 쿼터, 흑백)")
    return dest


def gen_images(prompts: list[str], out_dir: Path, seed_base: int = 0,
               stock: bool = False, company: str | None = None) -> list[Path]:
    """장면 이미지 생성 — **순차 호출**(2026-10-09 수정).

    ⚠️ 병렬화는 Pollinations 쿼터를 탔고, 오히려 이미지를 망쳤다.
       실측(2026-10-09): 동시 4개 요청 → 1개 200 + 3개 402(2바이트).
       즉 동시 1건만 통과하고 나머지는 전부 폴백 이미지로 대체됐다.
       → 10장이 대부분 '로컬 폴백(파스텔 그라디언트)' 로 나온 원인.

    stock=True 면 **무료 실사 사진(Openverse) + 선화 변환** 경로를 쓴다.
      (2026-10-10 로이 요청: "좀 더 고퀄리티의 무료 사진")
      Pollinations AI 생성의 한계 — 해상도 1024x576 강제 캡 + 56KB 저품질.
      실사 사진은 원본 1024~12288px + 실제 질감이라 선명도가 훨씬 좋다.
      실패 시 Pollinations 로 자동 폴백한다(단일 실패점 방지).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    fallback_count = 0
    stock_count = 0
    credits_path = out_dir.parent / "credits.jsonl"
    used_titles: set[str] = set()
    for i, p in enumerate(prompts):
        dest = out_dir / f"scene{i + 1}.jpg"
        got = False
        if stock:
            try:
                from src import photostock as ps
                import random as _rnd
                tmp_photo = out_dir / f"_src{i + 1}.jpg"
                r = ps.search_for_scene(
                    p, company=company, rng=_rnd.Random(seed_base + i * 37),
                    dest=tmp_photo, used_titles=used_titles)
                if r:
                    ps.photo_to_sketch(tmp_photo, dest, target_w=IMG_W,
                                       target_h=IMG_H, style="pencil")
                    (out_dir / f"scene{i + 1}.mono").write_text("1", encoding="utf-8")
                    got = True
                    stock_count += 1
                    ps.record_credit(credits_path, r["credit"])
                    print(f"  [fable] 이미지 {i + 1} 실사 사진 선화 OK "
                          f"({r['query'][:26]}, {r['credit']['license'].upper()})")
                tmp_photo.unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001
                print(f"  [fable] 이미지 {i + 1} 실사 실패({type(e).__name__})"
                      f" → AI 생성으로 폴백")
                got = False
        if not got:
            try:
                dest = _fetch_one(i, p, out_dir, len(prompts), seed_base)
            except Exception as e:  # noqa: BLE001
                print(f"  [fable] 이미지 {i + 1} 예외: {type(e).__name__}")
                _fallback_image(dest, i)
                _to_monochrome(dest)
                (out_dir / f"scene{i + 1}.mono").write_text("1", encoding="utf-8")
        paths.append(dest)
        if _is_fallback_image(dest):
            fallback_count += 1

    if stock and stock_count:
        print(f"  [fable] 실사 사진 {stock_count}/{len(prompts)} 장 "
              f"(나머지는 AI 생성) — 크레딧: {credits_path.name}")
    # 폴백 과다 시 경고 — 로이가 실제로 겪은 사고의 시각화
    if fallback_count:
        print(f"  [fable] 이미지 {fallback_count}/{len(prompts)} 장이 폴백 그라디언트"
              f"입니다 — 영상에 그림이 안 보일 수 있습니다.")
        if fallback_count >= len(prompts) * 0.6:
            print(f"  [fable] 60% 이상 실패 — 이미지 소스 전체 장애.")
    return paths


def _is_fallback_image(dest: Path) -> bool:
    """폴백 그라디언트 이미지면 True.

    2026-10-09: edge<0.045 단일 조건 (실화 0.113 / 폴백 0.011)
    2026-10-10 보정1: 실사 사진(어두운 장면)이 edge 0.030~0.046 →
        정상 사진을 폴백으로 오판 (10장 중 3장)
    2026-10-10 보정2: distinct 그레이레벨 수는 JPEG 노이즈 때문에
        폴백도 247개 → 구별 불가. **라플라시안 분산**으로 대체.
        실측: 폴백 19~29 / 실사 104~4889 (17배 이상 분리)

    라플라시안(2차 미분)은 평활한 그라디언트에서 거의 0 이고
    실제 촬영물은 윤곽·질감 때문에 값이 크다.
    """
    try:
        from PIL import ImageFilter, ImageStat
        import numpy as np

        im = Image.open(dest).convert("L")
        edge = ImageStat.Stat(im.filter(ImageFilter.FIND_EDGES)).mean[0] / 255.0
        if edge >= 0.045:
            return False
        a = np.asarray(im, dtype=np.float32)
        if a.shape[0] < 8 or a.shape[1] < 8:
            return False
        lap = (a[:-2, 1:-1] + a[2:, 1:-1]
               + a[1:-1, :-2] + a[1:-1, 2:] - 4 * a[1:-1, 1:-1])
        return float(lap.var()) < 60.0
    except Exception:  # noqa: BLE001
        return False
        return False


def _fallback_image(dest: Path, idx: int) -> None:
    """Pollinations 실패 시 로컬 파스텔 그라디언트 — 파이프라인 무중단."""
    import random
    rng = random.Random(idx * 977 + 4321)
    palettes = [
        ((250, 235, 215), (212, 190, 170)),  # 따뜻한 모래
        ((215, 233, 240), (180, 200, 220)),  # 잔잔한 호수
        ((245, 228, 215), (222, 205, 195)),  # 석양
        ((228, 238, 225), (200, 215, 205)),  # 새싹
        ((240, 232, 245), (210, 200, 225)),  # 저녁 노을
    ]
    top, bottom = palettes[idx % len(palettes)]
    img = Image.new("RGB", (IMG_W, IMG_H))
    d = ImageDraw.Draw(img)
    for y in range(IMG_H):
        t = y / max(IMG_H - 1, 1)
        c = tuple(int(top[k] + (bottom[k] - top[k]) * t) for k in range(3))
        d.line([(0, y), (IMG_W, y)], fill=c)
    blob = Image.new("RGB", (IMG_W, IMG_H), top)
    bd = ImageDraw.Draw(blob)
    for _ in range(16):
        x, y = rng.randint(0, IMG_W), rng.randint(0, IMG_H)
        r = rng.randint(160, 520)
        col = tuple(min(255, max(0, v + rng.randint(-25, 25))) for v in bottom)
        bd.ellipse([x - r, y - r, x + r, y + r], fill=col)
    blob = blob.filter(ImageFilter.GaussianBlur(150))
    img = Image.blend(img, blob, 0.45)
    img = img.filter(ImageFilter.GaussianBlur(2))
    img.save(dest, "JPEG", quality=88)


# ─────────────────────────────────────────────────────────────
# 2) ASS 자막 — 훅 바 / 하단 자막 / 아웃트로 명언 카드
# ─────────────────────────────────────────────────────────────
def _ass_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
            .replace("\n", "\\N"))


def _ass_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    c = round((sec % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _hook_display_lines(lang: str, hook: dict) -> tuple[list[str], int, int]:
    """훅 2줄을 PIL로 측정해 표시 줄로 나눈다. 반환: (표시줄, 폰트크기, 바높이).

    2026-10-07: 프롬프트가 "각 줄은 완전한 문장(마침표 포함)"을 요구하므로
    story 의 hook.lines 에 구두점이 붙는다. 화면 상단 훅 바는 구두점 없이 보여야
    깔끔하므로 여기서 제거한다(음성용 narration 은 fable.py 가 이미 만들어둠).
    """
    img = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(img)
    src = [(str(x).strip().rstrip(".?!。．！ ").strip()) for x in hook["lines"][lang]]
    # 2026-10-08: 58 → 76 확대 (피드에서 안 읽혔다)
    size = 76 if lang in ("ko", "zh-cn") else 70
    out: list[str] = []
    while size >= 52:
        font = cards._font(lang, size)
        out = []
        for ln in src:
            out.extend(cards._wrap(d, ln, font, 950))
        if len(out) <= 3:
            break
        size -= 4
    line_h = 96
    bar_h = 72 + len(out) * line_h + 42
    return out, size, bar_h


def _mark_highlight(line: str, highlight: str) -> str:
    """줄 안의 강조어를 주황색 인라인 태그로 감싼다. 없으면 원문 그대로."""
    if highlight and highlight in line:
        before, after = line.split(highlight, 1)
        return (_ass_escape(before)
                + f"{{\\c{ORANGE_ASS}}}{_ass_escape(highlight)}{{\\c&HFFFFFF&}}"
                + _ass_escape(after))
    return _ass_escape(line)


def _char_w(ch: str) -> float:
    """ASS 폭 추정 단위(fs 배수) — CJK 전각=1.0, 라틴/공백=0.55."""
    return 1.0 if ord(ch) > 0x2E80 else 0.55


def _wrap_card_text(text: str, fs: int, max_px: float = 860.0) -> list[str]:
    """중앙 카드(명언·교훈) 텍스트를 화면 폭에 맞게 줄바꿈.
    WrapStyle 2 는 자동 줄바꿈이 없어 긴 문장이 좌우로 잘리므로 명시적 개행이 필요.
    CJK 는 쉼표·마침표·공백 근처에서, 라틴은 어절 사이에서 끊는다."""
    units = max_px / fs
    # 토큰화: CJK 1글자 = 1토큰, 라틴 어절·공백 = 1토큰
    toks: list[str] = []
    buf = ""
    for ch in text:
        if ord(ch) > 0x2E80:
            if buf:
                toks.append(buf)
                buf = ""
            toks.append(ch)
        elif ch == " ":
            if buf:
                toks.append(buf)
                buf = ""
            toks.append(" ")
        else:
            buf += ch
    if buf:
        toks.append(buf)

    def width(s: str) -> float:
        return sum(_char_w(c) for c in s)

    lines: list[str] = []
    cur = ""
    for t in toks:
        cand = cur + t
        if cur and width(cand) > units:
            # 자연스러운 끊기 지점(쉼표·마침표·공백)이 줄 끝 근처에 있으면 거기서 자른다
            cut = max(cur.rfind(p) for p in ("，", "。", "、", "！", "？", ",", ".", " ", "·", "—"))
            if 3 <= cut and cut >= len(cur) - 6:
                lines.append(cur[:cut + 1].strip())
                cur = cur[cut + 1:].lstrip() + t   # t 가 공백이면 새 줄 첫 단어 뒤 공백 역할
            else:
                lines.append(cur.strip())
                cur = "" if t == " " else t
        else:
            cur = cand
    if cur.strip():
        lines.append(cur.strip())
    return lines or [text]


def _card_font_size(text: str, max_lines: int = 3) -> int:
    """카드 폰트 크기 — 기본 96, max_lines 줄 안에 안 들어가면 12%씩 축소.

    2026-10-08: 76 → 96 으로 확대.
    피드 그리드(썸네일)에서 카드가 너무 작아 안 읽혔다.
    쇼츠 피드는 손가락 거리에서 보므로 폰트 크기가 임팩트를 만든다.
    """
    fs = 96
    while fs > 62 and len(_wrap_card_text(text, fs)) > max_lines:
        fs = max(62, int(fs * 0.88))
    return fs


def build_ass(lang: str, story: dict, starts: list[float], durs: list[float]) -> tuple[str, int]:
    """전체 자막 파일 내용 + 훅 바 높이 반환. 이벤트:
      HOOK  — 상단 고정 바. 1장면(quote)에서는 '오늘의 명언 · 화자' 라벨,
              훅 장면부터는 훅 2줄 (흰 글씨 + 주황 강조어)
      QUOTE — 1장면(quote) 중앙 명언 카드 (명언 원문 + 화자)
      CAP   — 하단 자막 (hook/fable/real 장면)
      QUOTE — 아웃트로 중앙 교훈(moral) 카드
      CTA   — 아웃트로 하단 주황 CTA
    """
    font = _ass_font(lang)
    hook_lines, hook_size, bar_h = _hook_display_lines(lang, story["hook"])
    n = len(story["scenes"])
    total = starts[-1] + durs[-1]

    head = [
        "[Script Info]", "ScriptType: v4.00+",
        f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # HOOK: 상단 중앙 (alignment 8) — 검정 바 위 흰 글씨
        f"Style: HOOK,{font},{hook_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
        "-1,0,0,0,100,100,0,0,1,2.2,0,8,60,60,0,129",
        # CAP: 하단 중앙 (alignment 2) — 흰 글씨 검정 테두리
        # 2026-10-08: 74 → 92 확대 (피드에서 읽히지 않던 크기)
        f"Style: CAP,{font},92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,"
        "-1,0,0,0,100,100,0,0,1,4.4,1.2,2,80,80,110,129",
        # QUOTE: 화면 중앙 (alignment 5) — 명언/교훈 카드
        # 2026-10-08: 76 → 96 확대 (실제 크기는 _card_font_size 가 결정)
        f"Style: QUOTE,{font},96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,"
        "-1,0,0,0,100,100,0,0,1,5.0,1.6,5,90,90,0,129",
        # CTA: 하단 중앙 주황 (alignment 2)
        f"Style: CTA,{font},56,&H004DA9FF,&H004DA9FF,&H00000000,&H00000000,"
        "-1,0,0,0,100,100,0,0,1,2.4,0.6,2,70,70,140,129",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events: list[str] = []
    hl = str(story["hook"].get("highlight", {}).get(lang, "") or "")
    acts = [sc["act"] for sc in story["scenes"]]
    quote_first = bool(acts) and acts[0] == "quote"

    if quote_first:
        # ── 1장면(quote): 바 라벨 + 중앙 명언 카드 — 실제 명인의 말로 영상을 연다 ──
        qe = starts[0] + durs[0] - 0.35
        author = story["quote"]["author"].get(lang, "")
        label = cards.TAGS.get(lang, cards.TAGS["en"])
        if author:
            label = f"{label} · {author}"
        events.append(f"Dialogue: 0,{_ass_time(0)},{_ass_time(qe)},HOOK,,0,0,96,,"
                      f"{{\\fad(300,250)}}{_ass_escape(label)}")
        # 명언 원문은 화면 폭에 맞게 줄바꿈 (WrapStyle 2 는 자동 개행 없음 → 클리핑 방지)
        qraw = story["quote"]["text"].get(lang, "")
        qfs = _card_font_size(qraw)
        qtext = "\\N".join(_ass_escape(l) for l in _wrap_card_text(qraw, qfs))
        if author:
            qtext += f"\\N\\N{{\\fs44\\i1\\c{GOLD_ASS}}}— {_ass_escape(author)}{{\\fs{qfs}\\i0\\c&HFFFFFF&}}"
        events.append(f"Dialogue: 1,{_ass_time(0.2)},{_ass_time(qe)},QUOTE,,0,0,0,,"
                      f"{{\\fs{qfs}\\fad(500,350)}}{qtext}")
        hook_start = starts[1] + 0.10
    else:
        hook_start = 0.0

    # ── 훅 바 글자: 훅 장면부터 끝까지 고정 ──
    for k, ln in enumerate(hook_lines):
        mv = 60 + k * 78
        events.append(f"Dialogue: 0,{_ass_time(hook_start)},{_ass_time(total)},HOOK,,0,0,{mv},,"
                      f"{_mark_highlight(ln, hl)}")

    # ── 하단 자막: hook/fable/real 장면 (quote·outro 는 카드가 글자 담당) ──
    for i in range(n):
        if acts[i] not in ("hook", "fable", "real"):
            continue
        s = starts[i] + 0.30
        e = starts[i] + durs[i] - 0.15 - (XFADE if i < n - 1 else 0.5)
        if e - s < 0.6:
            e = s + 0.6
        events.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},CAP,,0,0,0,,"
                      f"{_ass_escape(story['scenes'][i]['subtitle'][lang])}")

    # ── 아웃트로: 교훈 카드(중앙) + CTA(하단) ──
    os_, oe = starts[n - 1] + 0.25, starts[n - 1] + durs[n - 1] - 0.2
    moral = str(story.get("moral", {}).get(lang, "") or "")
    mraw = moral if moral else story["quote"]["text"].get(lang, "")
    mfs = _card_font_size(mraw)
    mtext = ("\\N".join(_ass_escape(l) for l in _wrap_card_text(mraw, mfs)))
    events.append(f"Dialogue: 1,{_ass_time(os_)},{_ass_time(oe)},QUOTE,,0,0,0,,"
                  f"{{\\fs{mfs}\\fad(600,300)}}{mtext}")
    events.append(f"Dialogue: 1,{_ass_time(os_)},{_ass_time(oe)},CTA,,0,0,0,,"
                  f"{{\\fad(600,200)}}{_ass_escape(story['cta'][lang])}")

    return "\r\n".join(head + events), bar_h


# ─────────────────────────────────────────────────────────────
# 3) 언어별 렌더 — TTS + 켄번스 + 크로스페이드 + 자막 + BGM
# ─────────────────────────────────────────────────────────────
def render_language(lang: str, story: dict, image_paths: list[Path],
                    out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / f"work_{lang}"
    work.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg_exe()
    scenes = story["scenes"]

    # 1) 장면별 낭독 (TTS) → 배속 적용 (atempo — 피치 유지)
    #    로이 요청(2026-10-08): 영상 길이 **40초 이상 1분 이하**.
    #    → 낭독 총 길이를 목표 구간에 맞게 atempo 로 압축/복잡调控한 뒤,
    #      그래도 짧으면 장면 여유(SCENE_PAD)를 늘려 40초를 채운다.
    audios: list[Path] = []
    raws: list[Path] = []
    for i, sc in enumerate(scenes):
        raw = work / f"voiceraw_{i + 1}.mp3"
        if not raw.exists():
            tts.synth(sc["narration"][lang], lang, raw)
        raws.append(raw)

    # 1-1) 길이 조절 — 1분 초과면 낭독을 살짝 빠르게, 40초 미만이면 여유를 넓힘
    overhead = (HOOK_LEAD + OUTRO_TAIL + SCENE_PAD * len(scenes)
                - XFADE * (len(scenes) - 1))
    raw_total = sum(_audio_duration(r) for r in raws)
    tempo = VOICE_SPEED
    if raw_total + overhead > MAX_TOTAL:
        # 1분 안에 들어가도록 속도up (자연스러운 범위는1.0~1.35, 그 이상은 강제하지 않음)
        need = raw_total + overhead - MAX_TOTAL
        tempo = min(1.35, max(VOICE_SPEED, VOICE_SPEED + need / max(raw_total, 1.0)))

    for i, (sc, raw) in enumerate(zip(scenes, raws)):
        mp3 = work / f"voice_{i + 1}.mp3"
        if not mp3.exists():
            if abs(tempo - 1.0) < 0.01:
                mp3.write_bytes(raw.read_bytes())
            else:
                _run([ffmpeg, "-y", "-i", str(raw),
                      "-filter:a", f"atempo={tempo:.3f}",
                      "-c:a", "libmp3lame", "-b:a", "128k", str(mp3)],
                     f"atempo{i + 1}")
        audios.append(mp3)

    durs = [_audio_duration(a) + SCENE_PAD for a in audios]
    durs[0] += HOOK_LEAD           # 훅: 텍스트 인지 시간
    durs[-1] += OUTRO_TAIL         # 아웃트로: 여운

    # 1-2) 40초 미만이면 장면 여유를 균등 분배해 채운다 (무음 구간 없이 화면 유지)
    est = sum(durs) - XFADE * (len(scenes) - 1)
    if est < MIN_TOTAL:
        add = (MIN_TOTAL - est) / len(durs)
        durs = [d + add for d in durs]
        print(f"  [fable-video] {lang}: {est:.1f}초 → {MIN_TOTAL:.0f}초로 확장 "
              f"(장면당 +{add:.2f}초)")
    elif est > MAX_TOTAL:
        print(f"  [fable-video] {lang}: {est:.1f}초 — 1분 초과(atempo {tempo:.2f} 적용됨)")
    else:
        print(f"  [fable-video] {lang}: {est:.1f}초 (목표 40~60초 적정)")

    # 2) 장면별 세그먼트 — 워터마크 크롭 → 9:16 보정 → 켄번스
    ratio = W / H
    segs: list[Path] = []
    for i, (img, mp3, dur) in enumerate(zip(image_paths, audios, durs)):
        frames = max(int(dur * FPS), FPS)
        seg = work / f"seg{i + 1}.mp4"
        if seg.exists() and seg.stat().st_size > 50000:
            segs.append(seg)            # 캐시 재사용 (부분 실패 재시도 빠르게)
            continue
        with Image.open(img) as im:      # 실제 반환 해상도 확인 (왜곡 방지)
            iw, ih = im.size
        ch = int(ih * WATERMARK_CROP)
        ch2 = min(ch, int(iw / ratio))
        cw = min(iw, int(ch2 * ratio))
        x_off = (iw - cw) // 2
        vf = (f"crop={cw}:{ch2}:{x_off}:0,"
              f"scale={RENDER_W}:{RENDER_H}:force_original_aspect_ratio=increase,"
              f"crop={RENDER_W}:{RENDER_H},"
              f"{_motion(i, frames)},format=yuv420p")
        _run([ffmpeg, "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(img),
              "-i", str(mp3), "-filter_complex",
              f"[0:v]{vf}[v];[1:a]apad=whole_dur={dur:.2f}[a]",
              "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
              "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(seg)],
             f"seg{i + 1}")
        segs.append(seg)

    # 3) 결합 — 크로스페이드 (xfade/acrossfade 동일 길이 → A/V 동기 유지)
    n = len(segs)
    starts = [0.0]
    for d in durs[:-1]:
        starts.append(starts[-1] + d - XFADE)
    total = sum(durs) - XFADE * (n - 1)

    cmd = [ffmpeg, "-y"]
    for s in segs:
        cmd += ["-i", str(s)]
    vprev, aprev = "[0:v]", "[0:a]"
    fc: list[str] = []
    for i in range(1, n):
        vout, aout = f"[vx{i}]", f"[ax{i}]"
        fc.append(f"{vprev}[{i}:v]xfade=transition=dissolve:duration={XFADE}:"
                  f"offset={starts[i]:.3f}{vout}")
        fc.append(f"{aprev}[{i}:a]acrossfade=d={XFADE}:c1=tri:c2=tri{aout}")
        vprev, aprev = vout, aout
    fc.append(f"{vprev}fade=t=in:st=0:d=0.45,"
              f"fade=t=out:st={max(total - 0.8, 0.1):.3f}:d=0.8,format=yuv420p[vfin]")
    fc.append(f"{aprev}afade=t=in:st=0:d=0.35,"
              f"afade=t=out:st={max(total - 0.8, 0.1):.3f}:d=0.8[afin]")
    joined = work / "joined.mp4"
    _run(cmd + ["-filter_complex", ";".join(fc),
                "-map", "[vfin]", "-map", "[afin]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(joined)],
         "xfade-join")

    # 4) 자막 + 훅 바 + 필름 마감 + BGM (덕킹 믹스)
    ass_text, bar_h = build_ass(lang, story, starts, durs)
    ass_path = work / "subs.ass"
    ass_path.write_text(ass_text, encoding="utf-8")

    music = bgm.track_for(seed=story["date"])
    if music:
        print(f"  [fable] BGM: {music.name} (볼륨 {bgm.volume():.2f}, 낭독 시 자동 덕킹)")
    final = out_dir / f"fable_{lang}.mp4"
    # Linux runner 와 Windows 모두에서 동작 — fontsdir 생략 시 ffmpeg 가 fontconfig 로 시스템 폰트 검색
    # (2026-10-07 버그픽스) 드라이브 콜론까지 이스케이프해야 한다.
    #   subtitles='C\:/path/x.ass':fontsdir='C:/Windows/Fonts'  →  "Error ... Invalid argument"
    #   ':' 가 필터 옵션 구분자로 파싱돼 깨진다. 반드시 '\:' 로 바꾼다.
    ass_ref = _ffpath(str(ass_path.resolve()))
    fontsdir = _fontsdir()
    fonts_arg = f":fontsdir='{_ffpath(fontsdir)}'" if fontsdir else ""
    vf = (f"{_film_fx()},"
          f"drawbox=x=0:y=0:w=iw:h={bar_h}:color=black:t=fill,"
          f"subtitles='{ass_ref}'{fonts_arg}")
    # 원자적 기록 — 프로세스 사망 시 반쯤 쓴 mp4 가 '이미 렌더됨' 마커로 오인되는 사고 방지
    tmp = work / f"final_{lang}.tmp.mp4"
    if tmp.exists():
        tmp.unlink()
    bgm.mix(joined, tmp, total, music, video_vf=vf)
    os.replace(tmp, final)
    print(f"  [fable] {lang}: {total:.1f}s, 장면 {n}개, 훅 바 {bar_h}px")
    return final


def _verify_images(images_dir: Path, story: dict, seed_base: int) -> None:
    """생성된 장면 이미지 자동 검수 + 실패 장면 재생성 (2026-10-07).

    flux 는 같은 프롬프트라도 다른 동물을 그린다(실측: 두더지 우화에 여우·사람 혼입).
    프롬프트만으로는 막을 수 없으므로 **검출 후 해당 장면만 다른 seed 로 재생성**한다.
    검수 스크립트(check_fable_images)를 재사용하되, 어떤 실패든 파이프라인은 계속된다.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.check_fable_images import inspect, regenerate
    except Exception as e:  # noqa: BLE001
        print(f"  [check] 검수 모듈 로드 실패 — 건너뜀 ({type(e).__name__})")
        return
    try:
        results, fails = inspect(images_dir)
        if not results:
            return
        if not fails:
            print(f"  [check] 이미지 검수 {len(results)}/{len(results)} 통과")
            return
        print(f"  [check] 검수 실패 {len(fails)}개 (scene {fails}) → 재생성 시도")
        story_path = images_dir.parent / "story.json"
        still = regenerate(images_dir, fails, story_path, seed_base)
        results2, fails2 = inspect(images_dir)
        msg = f"  [check] 재생성 후 {len(results2) - len(fails2)}/{len(results2)} 통과"
        if fails2:
            msg += f" (잔여 실패 {fails2} — 기존 이미지 유지)"
        print(msg)
    except Exception as e:  # noqa: BLE001
        print(f"  [check] 검수 오류 — 렌더 계속 ({type(e).__name__}: {e})")


def make_fable(lang: str, story: dict, data_dir: Path) -> Path:
    """한 언어 전체 — 이미지(공용 캐시) → 렌더. 최종 mp4 경로 반환."""
    from .fable import story_dir
    sdir = story_dir(data_dir, story["date"])
    images = sdir / "images"
    prompts = [sc["image_prompt"] for sc in story["scenes"]]
    seed_base = int(story["date"].replace("-", "")) % 10000
    # 첫 언어(ko)일 때만 이미지 생성 — 4개 언어가 1벌을 공유한다.
    # 이미 있으면 캐시 히트라 다 건너뛴다.
    first_lang = lang == LANGS[0]
    if first_lang or not images.exists():
        # 실사 사진 경로 사용 여부 (2026-10-10 로이 요청, 기본 on)
        use_stock = os.getenv("FABLE_IMG_STOCK", "on").lower() != "off"
        company = (story.get("stock_company")
                   or os.getenv("FABLE_STOCK_COMPANY") or None)
        image_paths = gen_images(prompts, images, seed_base=seed_base,
                                 stock=use_stock, company=company)
        _verify_images(images, story, seed_base)
    else:
        image_paths = [images / f"scene{i + 1}.jpg" for i in range(len(prompts))]

    # ⚠️ 2026-10-09 실측 버그: 재생성이 실패하면 이미지 파일이 사라진 채로 남아
    #   렌더 단계가 FileNotFoundError 로 죽었다.
    #   → 렌더 전에 **반드시 존재·크기 확인**하고, 없으면 폴백을 만든다.
    for i, p in enumerate(image_paths):
        if p.exists() and p.stat().st_size > 20_000:
            continue
        print(f"  [fable] {lang}: scene{i + 1} 이미지 없음/손상 → 폴백 생성")
        _fallback_image(p, i)
        _to_monochrome(p)
        (p.parent / f"{p.stem}.mono").write_text("1", encoding="utf-8")
    return render_language(lang, story, image_paths, sdir)
