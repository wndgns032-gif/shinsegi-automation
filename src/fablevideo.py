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
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter

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
OUTRO_TAIL = 0.7                  # 아웃트로 끝 여유(초)

# 낭독 배속 (2026-10-04 로이 피드밚: 1.2배속) — TTS 후 ffmpeg atempo 로 처리
VOICE_SPEED = float(os.getenv("FABLE_VOICE_SPEED", "1.2"))

ORANGE_ASS = "&H4DA9FF&"          # #FFA94D (ASS 는 BGR)
GOLD_ASS = "&HB0D8E8&"            # #E8D8B0 — 아웃트로 화자 색

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
    k = i % 6
    if k == 0:      # 중앙 푸시인
        z, x, y = "min(1+0.00040*on,1.14)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif k == 1:    # 풀아웃
        z, x, y = "max(1.14-0.00040*on,1.001)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif k == 2:    # 위→아래 팬 (내려다보는 느낌)
        z = "1.12"
        x, y = "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(on/{f})".format(f=frames)
    elif k == 3:    # 아래→위 팬 (올려다보는 느낌)
        z = "1.12"
        x, y = "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/{f})".format(f=frames)
    elif k == 4:    # 대각선 우상향
        z = "min(1+0.00035*on,1.12)"
        x, y = ("(iw-iw/zoom)*(on/{f})".format(f=frames),
                "(ih-ih/zoom)*(1-on/{f})".format(f=frames))
    else:           # 대각선 좌하향
        z = "min(1+0.00035*on,1.12)"
        x, y = ("(iw-iw/zoom)*(1-on/{f})".format(f=frames),
                "(ih-ih/zoom)*(on/{f})".format(f=frames))
    return (f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:"
            f"s={W}x{H}:fps={FPS}")


def _film_fx() -> str:
    """필름 마감 체인 (ffmpeg 내장 — 무료)."""
    return ("unsharp=5:5:0.45:5:5:0.0,"
            "eq=contrast=1.04:saturation=1.07:brightness=0.008,"
            "vignette=0.4,"
            "noise=alls=2.5:allf=t")


# ─────────────────────────────────────────────────────────────
# 1) 장면 이미지 — Pollinations (무료·키 불필요) + 로컬 폴백
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
               + requests.utils.quote(p)
               + f"?width={IMG_W}&height={IMG_H}&nologo=true&seed={seed_base + i * 37 + 1000}&model=flux")
        ok = False
        backoffs = (10, 30, 60, 90)   # 402/429 = 익명 쿼터 — 시간 지나면 회복
        for attempt, backoff in enumerate(backoffs, start=1):
            try:
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=150)
                ct = r.headers.get("content-type", "")
                if r.ok and "image" in ct and len(r.content) > 20000:
                    dest.write_bytes(r.content)
                    print(f"  [fable] 이미지 {i + 1}/{len(prompts)} OK ({len(r.content) // 1024}KB)")
                    ok = True
                    break
                print(f"  [fable] 이미지 {i + 1} 시도{attempt} 실패 HTTP {r.status_code}")
                if r.status_code not in (402, 429, 500, 503):
                    break
            except Exception as e:  # noqa: BLE001
                print(f"  [fable] 이미지 {i + 1} 시도{attempt} 오류 {type(e).__name__}")
            if attempt < len(backoffs):
                time.sleep(backoff)
        if not ok:
            _fallback_image(dest, i)
            print(f"  [fable] 이미지 {i + 1} 로컬 폴백 (Pollinations 쿼터)")
        paths.append(dest)
        time.sleep(1)  # 무료 레이트리밋 예의
    return paths


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
    """훅 2줄을 PIL로 측정해 표시 줄로 나눈다. 반환: (표시줄, 폰트크기, 바높이)."""
    img = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(img)
    src = hook["lines"][lang]
    size = 58 if lang in ("ko", "zh-cn") else 54
    out: list[str] = []
    while size >= 42:
        font = cards._font(lang, size)
        out = []
        for ln in src:
            out.extend(cards._wrap(d, ln, font, 950))
        if len(out) <= 3:
            break
        size -= 4
    line_h = 78
    bar_h = 60 + len(out) * line_h + 36
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
    """카드 폰트 크기 — 기본 76, max_lines 줄 안에 안 들어가면 12%씩 축소."""
    fs = 76
    while fs > 48 and len(_wrap_card_text(text, fs)) > max_lines:
        fs = max(48, int(fs * 0.88))
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
    font = _ASS_FONTS.get(lang, "Arial")
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
        f"Style: CAP,{font},74,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,"
        "-1,0,0,0,100,100,0,0,1,3.6,1.0,2,80,80,120,129",
        # QUOTE: 화면 중앙 (alignment 5) — 명언/교훈 카드
        f"Style: QUOTE,{font},76,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,"
        "-1,0,0,0,100,100,0,0,1,4.2,1.4,5,90,90,0,129",
        # CTA: 하단 중앙 주황 (alignment 2)
        f"Style: CTA,{font},44,&H004DA9FF,&H004DA9FF,&H00000000,&H00000000,"
        "-1,0,0,0,100,100,0,0,1,2.0,0.6,2,70,70,150,129",
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
    audios: list[Path] = []
    for i, sc in enumerate(scenes):
        raw = work / f"voiceraw_{i + 1}.mp3"
        mp3 = work / f"voice_{i + 1}.mp3"
        if not raw.exists():
            tts.synth(sc["narration"][lang], lang, raw)
        if not mp3.exists():
            if abs(VOICE_SPEED - 1.0) < 0.01:
                mp3.write_bytes(raw.read_bytes())
            else:
                _run([ffmpeg, "-y", "-i", str(raw),
                      "-filter:a", f"atempo={VOICE_SPEED:.3f}",
                      "-c:a", "libmp3lame", "-b:a", "128k", str(mp3)],
                     f"atempo{i + 1}")
        audios.append(mp3)
    durs = [_audio_duration(a) + SCENE_PAD for a in audios]
    durs[0] += HOOK_LEAD           # 훅: 텍스트 인지 시간
    durs[-1] += OUTRO_TAIL         # 아웃트로: 여운

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
    fontsdir = "C\\:/Windows/Fonts"
    ass_ref = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
    vf = (f"{_film_fx()},"
          f"drawbox=x=0:y=0:w=iw:h={bar_h}:color=black:t=fill,"
          f"subtitles='{ass_ref}':fontsdir='{fontsdir}'")
    # 원자적 기록 — 프로세스 사망 시 반쯤 쓴 mp4 가 '이미 렌더됨' 마커로 오인되는 사고 방지
    tmp = work / f"final_{lang}.tmp.mp4"
    if tmp.exists():
        tmp.unlink()
    bgm.mix(joined, tmp, total, music, video_vf=vf)
    os.replace(tmp, final)
    print(f"  [fable] {lang}: {total:.1f}s, 장면 {n}개, 훅 바 {bar_h}px")
    return final


def make_fable(lang: str, story: dict, data_dir: Path) -> Path:
    """한 언어 전체 — 이미지(공용 캐시) → 렌더. 최종 mp4 경로 반환."""
    from .fable import story_dir
    sdir = story_dir(data_dir, story["date"])
    images = sdir / "images"
    prompts = [sc["image_prompt"] for sc in story["scenes"]]
    seed_base = int(story["date"].replace("-", "")) % 10000
    image_paths = gen_images(prompts, images, seed_base=seed_base)
    return render_language(lang, story, image_paths, sdir)
