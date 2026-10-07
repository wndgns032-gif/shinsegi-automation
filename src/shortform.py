"""숏폼 영상 파이프라인 — 템플릿 가운데 **풀와이드** 가로 영상 합성. 전 과정 무료.

구조 (사용자 확정, 2026-09-22 v5 — 토끼 좌측 상단 + 가장 뒤 레이어):
  고정 템플릿 위에
    · 상단: 명언 텍스트 + 화자 (정적, PIL)
    · 가운데 (0,520)-(1080,1240): **템플릿 전폭 가로형 AI 영상** (1080x720, 1.5:1)
      - 이미지: Pollinations (무료·키 불필요)
      - 낭독: src.tts 로컬 엔진 (무료·무제한)
      - 켄번스 + 자막 + 페이드 (ffmpeg)
    · 선생님: 템플릿 우측 — 영상 **뒤** (하체가 영상에 가려짐)
    · 토끼: 템플릿 **좌측 상단**으로 이동, 영상·텍스트보다 **뒤**
      → render_base 에서 베이스에 직접 합성(compose 오버레이 없음).
        옮기고 남은 원래 자리(밴드 아래로 보이던 다리)는 주변 배경색으로 메운다.
        다리 단면은 밴드 상단과 겹쳐 가려지게 배치한다.
  → 1080x1350 Reels mp4

장면 이미지는 언어 무관(텍스트 없는 무드샷)이라 사이클당 1세트만 만들고
4개 언어가 공유한다. 자막·낭독만 언어별로 만든다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter

from . import aivideo, bgm, cards, fablevideo, tts


def _fontsdir() -> str:
    """fablevideo._fontsdir 와 동일 — Linux/Windows 폰트 경로."""
    return fablevideo._fontsdir()


def _ffpath(p: str) -> str:
    """fablevideo._ffpath 와 동일 — ffmpeg 필터 인자용 경로 이스케이프."""
    return fablevideo._ffpath(p)

ROOT = Path(__file__).resolve().parent.parent
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

# 템플릿 위 가로 영상 위치/크기 — (x, y, w, h). 2026-09-21 v3 (사용자 지시):
#   세로 높이 +50% (480→720). 밴드 y 520~1240 는 명언 박스(y≤480)와
#   하단 꽃밭(y≥1120) 사이 중앙 정렬. 선생님은 영상 뒤(하체 가려짐),
#   토끼는 영상 앞(스프라이트 오버레이) — 사용자가 현 상태 확정.
VIDEO_RECT = (0, 520, 1080, 720)
# 상단 명언 텍스트 영역 (x0, y0, x1, y1) — 영상 위의 빈 공간
#   2026-09-22: 토끼가 좌측 상단으로 오면서 좌측 여백을 내줌(x0 150→225).
#   (우측 선생님 머리칼 x>600 회피, 고사리 잎 y<140 은 배경 장식)
QUOTE_BOX = (240, 90, 590, 480)
# 캐릭터 스프라이트 (scripts/build_sprites.py 로 템플릿에서 추출, 원위치 풀캔버스 RGBA)
#   선생님 스프라이트는 v3 에서 사용하지 않지만 재활용 가능성을 위해 에셋은 유지
SPRITE_TEACHER = ROOT / "assets" / "sprite_teacher.png"
SPRITE_RABBIT = ROOT / "assets" / "sprite_rabbit.png"
# 토끼 위치 (2026-09-22 사용자 지시: 좌측 상단 + **가장 뒤** 레이어)
#   베이스(템플릿)에 직접 합성하므로 명언 텍스트·영상 밴드보다 뒤에 깔린다.
#   템플릿 원본에서 토끼는 프레임 아래끝에 걸쳐 있어 다리가 잘려 있는데,
#   옮길 때 **밴드 상단과 아래끝을 맞춰** 그 단면이 영상에 가려지게 한다.
#   옮기고 남은 원래 자리(밴드 아래로 삐져나온 부분)는 주변 배경으로 메운다.
RABBIT_X = 10                     # 좌측 여백
RABBIT_OVERLAP = 26               # 밴드 안으로 겹치는 픽셀 (잘린 단면 은폐)
RABBIT_SCALE = float(os.getenv("SHORTFORM_RABBIT_SCALE", "0.55"))
_SAGE_HEX = "0x7A947C"           # cards.SAGE (122,148,124)

SCENE_COUNT = 5
IMG_W, IMG_H = 1152, 768          # Pollinations 요청 크기 (1.5:1) — 실제 반환 크기는 다를 수 있음
CLIP_W, CLIP_H = 2160, 1440       # 클립 렌더 크기 (최종 1080x720 로 다운스케일 → 선명)
FPS = 25
IMG_STYLE = (", soft watercolor illustration, studio ghibli style, warm muted colors, "
             "gentle atmospheric light, sharp focus, no text, no watermark, no logo")
_WATERMARK_CROP = 0.92            # Pollinations 하단 워터마크 잘라내기 (상위 92% 사용)

# v4 무료 시네마틱 모션 (2026-09-21) — 외부 결제·추가 다운로드 없이 ffmpeg 만으로
#   · 장면 간 크로스페이드(하드컷 제거)      → xfade + acrossfade
#   · 장면별 카메라 무빙 5종 로테이션        → zoompan 표현식
#   · 필름 마감(샤픈+색보정+비네트+그레인)   → unsharp/eq/vignette/noise
XFADE = 0.55                      # 장면 전환 크로스페이드 길이(초)

_ASS_FONTS = {
    "ko": "Malgun Gothic",
    "zh-cn": "Microsoft YaHei",
    "en": "Georgia",
    "fr": "Georgia",
}


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


def _motion(i: int, frames: int, ai: bool = False) -> str:
    """장면별 카메라 무빙 zoompan 표현식 (무료·로컬).

    정지 이미지라도 무빙 종류를 섞으면 단조로움이 사라진다.
    AI 클립은 이미 움직이므로 아주 약한 푸시만 얹는다.
    """
    if ai:
        return (f"zoompan=z='min(1+0.00025*on,1.06)':x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':d={frames}:s={CLIP_W}x{CLIP_H}:fps={FPS}")
    k = i % 5
    if k == 0:      # 중앙 푸시인
        z, x, y = "min(1+0.00040*on,1.14)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif k == 1:    # 풀아웃
        z, x, y = "max(1.14-0.00040*on,1.001)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif k == 2:    # 좌→우 팬
        z = "1.12"
        x, y = f"(iw-iw/zoom)*(on/{frames})", "(ih-ih/zoom)*0.45"
    elif k == 3:    # 우→좌 팬
        z = "1.12"
        x, y = f"(iw-iw/zoom)*(1-on/{frames})", "(ih-ih/zoom)*0.55"
    else:           # 대각선 푸시
        z = "min(1+0.00035*on,1.12)"
        x, y = (f"(iw-iw/zoom)*(0.30+0.55*on/{frames})",
                f"(ih-ih/zoom)*(0.70-0.50*on/{frames})")
    return (f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:"
            f"s={CLIP_W}x{CLIP_H}:fps={FPS}")


def _film_fx() -> str:
    """필름 마감 체인 (전부 ffmpeg 내장 — 무료)."""
    return ("unsharp=5:5:0.45:5:5:0.0,"        # 다운스케일 후 선명도 복원
            "eq=contrast=1.04:saturation=1.07:brightness=0.008,"
            "vignette=0.4,"                     # 은은한 비네트
            "noise=alls=2.5:allf=t")            # 미세 필름 그레인(시간축만 → 정지 노이즈 최소)


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
# 1) 장면 기획 — DeepSeek 1회 호출 (이미지 프롬프트 공용 + 언어별 자막/낭독)
# ─────────────────────────────────────────────────────────────
def plan_scenes(contents: dict, theme: str | None = None) -> dict:
    """명언 콘텐츠 → 스토리보드.

    반환: {"image_prompts": [영문 5개],
           "scenes": {lang: [{"subtitle": str, "narration": str} x 5]}}
    실패 시 reels_script 문장 분할로 폴과.
    """
    ko = contents.get("ko", {})
    quote = ko.get("ig_cards", [""])[0]
    author = ko.get("quote_author", "")
    scripts = {l: c.get("reels_script", "") for l, c in contents.items()}

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key:
        prompt = f"""당신은 세로 숏폼 영상의 스토리보드 작가다.

오늘의 명언: {quote} — {author}
테마: {theme or '인생의 배움'}

이 명언 콘텐츠를 {SCENE_COUNT}개 장면의 슬라이드쇼 영상으로 만든다.
장면 흐름: 1=명언 소개 / 2=일상 장면 / 3~4=배움 / 5=오늘의 한 가지 또는 질문.

각 언어(ko, en, zh-cn, fr)의 기존 낭독 대본을 {SCENE_COUNT}개 장면으로 나눠라.
- narration: 해당 언어 낭독 (한 장면 = 1~2문장, 7~9초 분량). 기존 대본의 문장을 재배치하되 문체 유지.
- subtitle: 화면 자막. 낭독의 핵심만 아주 짧게 (한국어/중국어 16자 이내, 영어/프랑스어 40자 이내).
- image_prompts: 장면 분위기에 맞는 영문 이미지 프롬프트 {SCENE_COUNT}개.
  텍스트 없는 무드샷(사물·풍경·손·실루엣 위주), 얼굴 클로즈업 금지.

반환은 순수 JSON 하나만:
{{"image_prompts": ["...", ...],
  "scenes": {{"ko": [{{"subtitle": "...", "narration": "..."}}, ...],
             "en": [...], "zh-cn": [...], "fr": [...]}}}}

## 언어별 기존 낭독 대본
{json.dumps(scripts, ensure_ascii=False, indent=1)}"""
        try:
            r = requests.post(
                DEEPSEEK_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.6, "max_tokens": 3000},
                timeout=120)
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            data = json.loads(m.group(0))
            if (isinstance(data.get("image_prompts"), list)
                    and len(data["image_prompts"]) >= SCENE_COUNT
                    and all(len(data["scenes"].get(l, [])) >= SCENE_COUNT
                            for l in ("ko", "en", "zh-cn", "fr"))):
                data["image_prompts"] = data["image_prompts"][:SCENE_COUNT]
                for l in data["scenes"]:
                    data["scenes"][l] = data["scenes"][l][:SCENE_COUNT]
                return data
        except Exception as e:  # noqa: BLE001
            print(f"  [shortform] 스토리보드 생성 실패 → 폴과 ({type(e).__name__}: {str(e)[:80]})")

    # 폴과: 대본 문장을 장면 수에 맞춰 균등 분할
    scenes: dict[str, list[dict]] = {}
    for lang, c in contents.items():
        sents = tts.split_sentences(c.get("reels_script", "") or "")
        if not sents:
            sents = c.get("ig_cards", [""])[:SCENE_COUNT]
        chunks: list[list[str]] = [[] for _ in range(SCENE_COUNT)]
        for i, s in enumerate(sents):
            chunks[min(i * SCENE_COUNT // max(len(sents), 1), SCENE_COUNT - 1)].append(s)
        lang_scenes = []
        for chunk in chunks:
            narration = " ".join(chunk) or (sents[0] if sents else "")
            sub = re.sub(r"\s+", " ", narration)
            limit = 16 if lang in ("ko", "zh-cn") else 40
            lang_scenes.append({"subtitle": sub[:limit], "narration": narration})
        scenes[lang] = lang_scenes
    prompts = [
        "a single open book on a wooden desk by a bright window",
        "a quiet morning street with warm sunlight and long shadows",
        "hands holding a warm cup of tea, soft bokeh background",
        "a small sprout growing through a crack in stone",
        "a calm lake at dusk reflecting golden sky",
    ]
    return {"image_prompts": prompts, "scenes": scenes}


# ─────────────────────────────────────────────────────────────
# 2) 이미지 생성 — Pollinations (묣료, 키 불필요, 순차·재시도)
# ─────────────────────────────────────────────────────────────
def gen_images(prompts: list[str], out_dir: Path, seed_base: int = 0) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, p in enumerate(prompts):
        dest = out_dir / f"scene{i + 1}.jpg"
        if dest.exists() and dest.stat().st_size > 20000:
            paths.append(dest)
            continue
        url = ("https://image.pollinations.ai/prompt/"
               + requests.utils.quote(p + IMG_STYLE)
               + f"?width={IMG_W}&height={IMG_H}&nologo=true&seed={seed_base + i * 37 + 1000}&model=flux")
        ok = False
        # 402/429 = 익명 쿼터 초과 (시간이 지나면 회복) → 긴 백오프 후 재시도
        backoffs = (10, 30, 60, 90)
        for attempt, backoff in enumerate(backoffs, start=1):
            try:
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
                ct = r.headers.get("content-type", "")
                if r.ok and "image" in ct and len(r.content) > 20000:
                    dest.write_bytes(r.content)
                    print(f"  [shortform] 이미지 {i + 1}/{len(prompts)} OK ({len(r.content) // 1024}KB)")
                    ok = True
                    break
                print(f"  [shortform] 이미지 {i + 1} 시도{attempt} 실패 HTTP {r.status_code}")
                if r.status_code not in (402, 429, 500, 503):
                    break  # 쿼터/서버 문제가 아니면 재시도 무의미
            except Exception as e:  # noqa: BLE001
                print(f"  [shortform] 이미지 {i + 1} 시도{attempt} 오류 {type(e).__name__}")
            if attempt < len(backoffs):
                time.sleep(backoff)
        if not ok:
            # 로컬 폴백 — 부드러운 파스텔 그라디언트 (파이프라인 무중단)
            _fallback_image(dest, i)
            print(f"  [shortform] 이미지 {i + 1} 로컬 폴백 생성 (Pollinations 쿼터)")
        paths.append(dest)
        time.sleep(1)  # 묣료 레이트리밋 예의
    return paths


def _fallback_image(dest: Path, idx: int) -> None:
    """Pollinations 실패 시 쓰는 로컬 배경 — 파스텔 그라디언트 + 부드러운 노이즈."""
    import random
    from PIL import Image, ImageDraw, ImageFilter
    rng = random.Random(idx * 977 + 1234)
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
    # 부드러운 색 얼룩 (물감 느낌)
    blob = Image.new("RGB", (IMG_W, IMG_H), top)
    bd = ImageDraw.Draw(blob)
    for _ in range(14):
        x, y = rng.randint(0, IMG_W), rng.randint(0, IMG_H)
        r = rng.randint(120, 420)
        col = tuple(min(255, max(0, v + rng.randint(-25, 25))) for v in bottom)
        bd.ellipse([x - r, y - r, x + r, y + r], fill=col)
    blob = blob.filter(ImageFilter.GaussianBlur(120))
    img = Image.blend(img, blob, 0.45)
    img = img.filter(ImageFilter.GaussianBlur(2))
    img.save(dest, "JPEG", quality=88)


# ─────────────────────────────────────────────────────────────
# 2b) AI 영상 클립 (선택 보강) — MiniMax H3 무료 스페이스
#     실패하면 None → 해당 장면은 기존 이미지 켄번스로 폴백 (파이프라인 무중단)
# ─────────────────────────────────────────────────────────────
def gen_ai_clips(prompts: list[str], out_dir: Path, seed_base: int = 0) -> list[Path | None]:
    """장면별 AI 클립 시도. 언어 무관이라 사이클당 1세트만 만들고 4개 언어가 공유.

    무료 ZeroGPU 스페이스는 **한 편당 생성이 10분 이상** 걸릴 수 있어
    기본값은 앞쪽 1개 장면(훅)만 AI 클립으로 뽑고 나머지는 무료 로컬 모션을 쓴다.
    (SHORTFORM_AI_CLIPS_MAX 로 조절, 실패 시 그 장면만 폴백)
    """
    if not aivideo.enabled():
        print("  [shortform] AI 클립: 꺼짐(SHORTFORM_AI_CLIPS/HF_TOKEN) — 로컬 모션으로 진행")
        return [None] * len(prompts)
    try:
        max_n = int(os.getenv("SHORTFORM_AI_CLIPS_MAX", "1"))
    except ValueError:
        max_n = 1
    out_dir.mkdir(parents=True, exist_ok=True)
    clips: list[Path | None] = [None] * len(prompts)
    for i, p in enumerate(prompts[:max(0, max_n)]):
        dest = out_dir / f"aiclip{i + 1}.mp4"
        if dest.exists() and dest.stat().st_size > 20000:
            clips[i] = dest
            continue
        clip, reason = aivideo.gen_clip(
            p + ", soft cinematic lighting, calm gentle motion, no text",
            dest, seed=seed_base + i * 137)
        if clip:
            print(f"  [shortform] AI 클립 {i + 1}/{len(prompts)} OK ({reason})")
            clips[i] = clip
        else:
            print(f"  [shortform] AI 클립 {i + 1} 실패 → 로컬 모션 폴백 ({reason[:180]})")
    if max_n < len(prompts):
        print(f"  [shortform] AI 클립: 앞 {max(0, max_n)}개 장면만 시도 (MAX={max_n})")
    return clips


# ─────────────────────────────────────────────────────────────
# 3) 언어별 가로 클립 — TTS + 켄번스(또는 AI 클립) + 자막
# ─────────────────────────────────────────────────────────────
def _ass_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
            .replace("\n", "\\N").replace(",", "،"))


def _ass_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    c = round((sec % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def build_clip(lang: str, scenes: list[dict], image_paths: list[Path], work_dir: Path,
               ai_clips: list[Path | None] | None = None) -> Path:
    """장면 자막/낭독 + 이미지(또는 AI 클립) → CLIP_W x CLIP_H 가로 클립 mp4.

    ai_clips[i] 가 있으면 그 장면은 **실제 움직이는 AI 영상**(루프+페이드)을 쓰고,
    없으면 기존 정지 이미지 켄번스를 쓴다. AI 클립의 자체 오디오는 버리고
    우리 TTS 낭독만 사용한다(자막·낭독 언어별 일관성 유지).
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg_exe()

    # 1) 장멸별 낭독 합성
    audios: list[Path] = []
    for i, sc in enumerate(scenes):
        mp3 = work_dir / f"voice_{i + 1}.mp3"
        if not mp3.exists():
            tts.synth(sc["narration"], lang, mp3)
        audios.append(mp3)
    durs = [_audio_duration(a) + 0.35 for a in audios]

    # 2) 장멸별 세그먼트 (워터마크 크롭 → 비율 보정 → 켄번스 → 페이드)
    #    Pollinations 이 요청 크기와 다른 해상도를 돌려주는 경우가 있어
    #    각 이미지의 실제 크기를 PIL로 읽어 크롭 좌표를 계산한다 (왜곡 방지).
    segs: list[Path] = []
    ratio = CLIP_W / CLIP_H
    ai_clips = ai_clips or [None] * len(scenes)
    for i, (img, mp3, dur) in enumerate(zip(image_paths, audios, durs)):
        frames = max(int(dur * FPS), FPS)
        seg = work_dir / f"seg{i + 1}.mp4"
        aic = ai_clips[i] if i < len(ai_clips) else None

        if aic is not None:
            # ── AI 클립 경로: 실제 움직이는 영상 (무한 루프 → 장면 길이에 맞춤)
            #    페이드는 넣지 않는다 — 장면 전환을 xfade 크로스페이드로 통일.
            vf = (f"scale={CLIP_W * 2}:{CLIP_H * 2}:force_original_aspect_ratio=increase,"
                  f"crop={CLIP_W * 2}:{CLIP_H * 2},"
                  f"{_motion(i, frames, ai=True)},format=yuv420p")
            _run([ffmpeg, "-y", "-stream_loop", "-1", "-i", str(aic),
                  "-i", str(mp3), "-filter_complex",
                  f"[0:v]{vf}[v];[1:a]apad=whole_dur={dur:.2f}[a]",
                  "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
                  "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(seg)],
                 f"seg{i + 1}(ai)")
            segs.append(seg)
            continue

        # ── 기본 경로: 정지 이미지 + 카메라 무빙
        #    Pollinations 이 요청 크기와 다른 해상도를 돌려주는 경우가 있어
        #    각 이미지의 실제 크기를 PIL로 읽어 크롭 좌표를 계산한다 (왜곡 방지).
        with Image.open(img) as im:
            iw, ih = im.size
        ch = int(ih * _WATERMARK_CROP)          # 워터마크 제거 높이
        cw = min(iw, int(ch * ratio))            # 타깃 비율로 중앙 크롭
        ch2 = min(ch, int(iw / ratio))
        x_off = (iw - cw) // 2
        vf = (f"crop={cw}:{ch2}:{x_off}:0,"
              f"scale={CLIP_W * 2}:{CLIP_H * 2},"
              f"{_motion(i, frames)},format=yuv420p")
        _run([ffmpeg, "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(img),
              "-i", str(mp3), "-filter_complex",
              f"[0:v]{vf}[v];[1:a]apad=whole_dur={dur:.2f}[a]",
              "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
              "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(seg)],
             f"seg{i + 1}")
        segs.append(seg)

    # 3) 결합 — 장면 간 크로스페이드 (하드컷 제거). 영상 xfade 와 오디오 acrossfade 가
    #    같은 길이만큼 줄어들므로 A/V 동기는 그대로 유지된다.
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
        voff = starts[i]
        vout, aout = f"[vx{i}]", f"[ax{i}]"
        fc.append(f"{vprev}[{i}:v]xfade=transition=dissolve:duration={XFADE}:"
                  f"offset={voff:.3f}{vout}")
        fc.append(f"{aprev}[{i}:a]acrossfade=d={XFADE}:c1=tri:c2=tri{aout}")
        vprev, aprev = vout, aout
    fc.append(f"{vprev}fade=t=in:st=0:d=0.45,"
              f"fade=t=out:st={max(total - 0.7, 0.1):.3f}:d=0.7,format=yuv420p[vfin]")
    fc.append(f"{aprev}afade=t=in:st=0:d=0.35,"
              f"afade=t=out:st={max(total - 0.7, 0.1):.3f}:d=0.7[afin]")
    joined = work_dir / "joined.mp4"
    _run(cmd + ["-filter_complex", ";".join(fc),
                "-map", "[vfin]", "-map", "[afin]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(joined)],
         "xfade-join")

    # 4) 자막 (ASS) — 크로스페이드로 줄어든 시간축에 맞춘다
    font = _ASS_FONTS.get(lang, "Arial")
    ass = [
        "[Script Info]", "ScriptType: v4.00+",
        f"PlayResX: {CLIP_W}", f"PlayResY: {CLIP_H}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: CAP,{font},90,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,-1,0,0,0,100,100,0,0,1,3.2,0,2,70,70,55,129", "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for i, sc in enumerate(scenes):
        s = starts[i] + (0.30 if i else 0.10)
        e = starts[i] + durs[i] - 0.15 - (XFADE if i < n - 1 else 0.5)
        if e - s < 0.6:
            e = s + 0.6
        ass.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},CAP,,0,0,0,,"
                   f"{_ass_escape(sc['subtitle'])}")
    ass_path = work_dir / "subs.ass"
    ass_path.write_text("\r\n".join(ass), encoding="utf-8")

    # 5) 필름 마감 + 자막 + **배경음악(덕킹 믹스)**
    #    BGM 은 assets/bgm/ 음원 → 없으면 로컬 합성(저작권 0) → 그래도 없으면 생략.
    clip = work_dir / f"clip_{lang}.mp4"
    # (2026-10-07 버그픽스) fontsdir 의 드라이브 콜론도 이스케이프해야 렌더가 안 깨진다.
    #   미이스케이프 시 "Error opening output file ... Invalid argument" → BGM/자막 없이 조용히 실패
    ass_ref = _ffpath(str(ass_path.resolve()))
    fontsdir = _fontsdir()
    fonts_arg = f":fontsdir='{_ffpath(fontsdir)}'" if fontsdir else ""
    vf = f"{_film_fx()},subtitles='{ass_ref}'{fonts_arg}"
    music = bgm.track(seed=str(work_dir)) if bgm.enabled() else None
    if music:
        print(f"  [shortform] BGM: {music.name} (볼륨 {bgm.volume():.2f}, 낭독 시 자동 덕킹)")
    bgm.mix(joined, clip, total, music, video_vf=vf)
    print(f"  [shortform] 클립 {lang}: {total:.1f}s, 크로스페이드 {XFADE}s x{n - 1}")
    return clip


# ─────────────────────────────────────────────────────────────
# 4) 정적 베이스 — 템플릿 + 상단 명언 텍스트 + 영상 테두리
# ─────────────────────────────────────────────────────────────
def rabbit_sprite() -> tuple[Image.Image, tuple[int, int]] | None:
    """토끼 스프라이트를 알파 기준으로 잘라 (이미지, 원본 bbox) 로 반환.

    추출 과정에서 남은 아주 옅은 물감 번짐(alpha<34)은 투명 처리해
    스프라이트 사각형 경계가 화면에 드러나지 않게 한다.
    """
    if not SPRITE_RABBIT.exists():
        return None
    sp = Image.open(SPRITE_RABBIT).convert("RGBA")
    r, g, b, a = sp.split()
    a = a.point(lambda v: 0 if v < 34 else min(255, int((v - 34) * 255 / 221)))
    bbox = a.getbbox()
    if not bbox:
        return None
    return Image.merge("RGBA", (r, g, b, a)).crop(bbox), bbox


def _erase_original_rabbit(img: Image.Image, bbox: tuple[int, int, int, int]) -> None:
    """템플릿 원래 자리의 토끼를 지운다 — 단, **영상 밴드 아래로 보이는 부분만**.

    밴드에 가려지는 부분(y < 밴드 하단)은 어차피 안 보이므로 건드리지 않는다.
    지운 자리는 **행별 주변 배경색**(같은 y 에서 토끼가 아닌 픽셀들의 평균)으로 채운 뒤
    살짝 블러해 수채화 톤을 유지한다. (단순 큰 블러는 토끼의 검은 스타킹 색이 번져
    회색 얼룩이 생기고, 좌우 미러 패치는 원본 이음새까지 복사돼 티가 났다.)
    """
    import numpy as np

    vy, vh = VIDEO_RECT[1], VIDEO_RECT[3]
    band_bottom = vy + vh                      # 영상 밴드가 덮는 마지막 y
    rx0, ry0, rx1, ry1 = bbox
    ry0 = max(ry0, band_bottom)                # 보이는 부분만
    if ry1 <= ry0:
        return

    sp = Image.open(SPRITE_RABBIT).convert("RGBA")
    mask_img = sp.getchannel("A").point(lambda v: 255 if v > 8 else 0)
    mask_img = mask_img.filter(ImageFilter.MaxFilter(9))       # 잔여 테두리까지 포함
    m = np.asarray(mask_img) > 127
    m[:ry0] = False                                            # 밴드에 가려지는 윗부분은 제외

    rgb = img.convert("RGB")
    arr = np.asarray(rgb).astype(np.float32)
    for y in range(ry0, ry1):
        row = m[y]
        if not row.any():
            continue
        keep = ~row
        src = arr[y][keep] if keep.any() else arr[y]
        arr[y][row] = src.mean(axis=0)

    filled = Image.fromarray(arr.astype("uint8"), "RGB")
    # 채운 자리만 부드럽게 (경계 페더)
    soft = filled.filter(ImageFilter.GaussianBlur(9))
    feather = Image.fromarray((m * 255).astype("uint8"), "L").filter(
        ImageFilter.GaussianBlur(5))
    img.paste(soft, (0, 0), feather)


def place_rabbit(img: Image.Image) -> None:
    """토끼를 좌측 상단으로 옮긴다. 베이스 단계에서 그리므로 **가장 뒤** 레이어가 된다."""
    got = rabbit_sprite()
    if not got:
        return
    rabbit, bbox = got
    _erase_original_rabbit(img, bbox)
    w, h = rabbit.size
    nw, nh = max(int(w * RABBIT_SCALE), 1), max(int(h * RABBIT_SCALE), 1)
    rabbit = rabbit.resize((nw, nh), Image.LANCZOS)
    # 아래끝을 영상 밴드 상단에 살짝 겹치게 두어 잘린 단면이 영상에 가려지게 한다
    y = VIDEO_RECT[1] + RABBIT_OVERLAP - nh
    img.alpha_composite(rabbit, (RABBIT_X, max(y, 0)))


def render_base(lang: str, quote: str, author: str, out_path: Path) -> Path:
    img = Image.open(cards.TEMPLATE_PATH).convert("RGBA")
    # 토끼를 먼저 깔고(가장 뒤) 그 위에 명언 텍스트를 그린다.
    place_rabbit(img)
    draw = ImageDraw.Draw(img)

    x0, y0, x1, y1 = QUOTE_BOX
    max_w = x1 - x0

    # 명언 본문 — 박스 안에서 자동 축소
    size = 46
    while size > 26:
        font = cards._font(lang, size)
        lines = cards._wrap(draw, quote, font, max_w)
        total_h = sum(draw.textbbox((0, 0), ln, font=font)[3] for ln in lines) + (len(lines) - 1) * int(size * 0.45)
        if total_h <= (y1 - y0) - 110 and len(lines) <= 5:
            break
        size -= 2
    font = cards._font(lang, size)
    lines = cards._wrap(draw, quote, font, max_w)
    line_h = int(size * 1.45)
    text_h = len(lines) * line_h

    cy = y0 + (y1 - y0 - text_h - 90) // 2  # 화자 영역(90px) 남기고 수직 중앙
    for ln in lines:
        w = draw.textlength(ln, font=font)
        draw.text((x0 + (max_w - w) / 2, cy), ln, font=font, fill=cards.QUOTE_INK)
        cy += line_h

    # 구분선 + 화자
    cy += 18
    lw = 64
    draw.line((x0 + (max_w - lw) / 2, cy, x0 + (max_w + lw) / 2, cy),
              fill=cards.SAGE, width=3)
    cy += 20
    if author:
        afont = cards._font(lang, 30)
        label = f"— {author}"
        w = draw.textlength(label, font=afont)
        draw.text((x0 + (max_w - w) / 2, cy), label, font=afont, fill=cards.SAGE)

    # 영상 밴드 테두리는 compose 단계에서 그린다 (스프라이트 아래·영상 위)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, "PNG")
    return out_path


# ─────────────────────────────────────────────────────────────
# 5) 합성 — 베이스 위에 가로 클립 + 캐릭터 스프라이트 오버레이
# ─────────────────────────────────────────────────────────────
def compose(base_png: Path, clip: Path, out_path: Path) -> Path:
    vx, vy, vw, vh = VIDEO_RECT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 캐릭터 스프라이트 오버레이는 없다 (2026-09-22):
    #   토끼는 render_base 에서 좌측 상단에, 선생님은 템플릿에 그대로 —
    #   둘 다 베이스에 있으므로 영상 밴드에 가려지는 '뒤' 레이어다.
    cmd = [_ffmpeg_exe(), "-y",
           "-loop", "1", "-i", str(base_png), "-i", str(clip)]
    # [1] 영상 스케일→오버레이 → 밴드 상하 세이지 라인
    fc = (f"[1:v]scale={vw}:{vh}[v];"
          f"[0:v][v]overlay={vx}:{vy}:shortest=1[bg0];"
          f"[bg0]drawbox=x=0:y={vy - 1}:w=iw:h=3:color={_SAGE_HEX}:t=fill[bg1];"
          f"[bg1]drawbox=x=0:y={vy + vh - 2}:w=iw:h=3:color={_SAGE_HEX}:t=fill[bg2]")
    last = "bg2"
    fc += f";[{last}]format=yuv420p[out]"
    cmd += ["-filter_complex", fc,
            "-map", "[out]", "-map", "1:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart", str(out_path)]
    _run(cmd, "compose")
    return out_path


# ─────────────────────────────────────────────────────────────
# 6) 한 언어 전체 — 베이스 + 클립 + 합성
# ─────────────────────────────────────────────────────────────
def make_shortform(lang: str, content: dict, scenes: list[dict],
                   image_paths: list[Path], out_dir: Path,
                   ai_clips: list[Path | None] | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cards_list = content.get("ig_cards", [""])
    quote = cards_list[0]
    author = content.get("quote_author", "")

    base = render_base(lang, quote, author, out_dir / f"base_{lang}.png")
    clip = build_clip(lang, scenes, image_paths, out_dir / f"work_{lang}",
                      ai_clips=ai_clips)
    return compose(base, clip, out_dir / f"shortform_{lang}.mp4")
