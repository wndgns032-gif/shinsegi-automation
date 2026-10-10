"""무료 실사 사진 소스 — Openverse / Picsum.

2026-10-10 실측 배경
----------------------
기존 Pollinations AI 생성이 저품질이던 근본 원인 2가지:
  1) **해상도 강제 캡**: 1920x1080 을 요청해도 1024x576 으로 반환됨 (실측).
     쇼츠 영상(1080x1920) 에 upscaling 필요 → 선명도 손실.
  2) AI 특유의 플라스틱 텍스처:.details 부족. 56KB짜리 이미지가 흔함.

그래서 **실사 사진**(Openverse, Flickr/Wikimedia CC 인증)을 쓰고
흑백 선화로 변환하는 전략으로 전환한다.
  - 해상도 1024~12288px 원본 그대로 활용 가능
  - 실제 촬영물이라 디테일/질감이 살아있음
  - 아래 photo_to_sketch() 로 통일된 선화 톤 변환 → 10장 일관성 유지

라이선스: Openverse 기본 필터는 `license_type=commercial` (CC-BY, CC-BY-SA,
CC0, Public Domain). 출처 표기(attribution)가 필요하므로 `credits.jsonl` 에
기록하고 워크플로 마지막에 크레딧을 캡션/설명에 붙인다.
"""
from __future__ import annotations

import io
import json
import random
import re
from pathlib import Path

import requests
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

OPENVERSE = "https://api.openverse.org/v1/images/"
PICSUM = "https://picsum.photos/seed/{seed}/{w}/{h}"
UA = {"User-Agent": "shinsegi-automation/1.0 (contact: shinsegi.media@outlook.kr)"}
TIMEOUT = 30

# 나스닥 TOP 10 기업별 검색 키워드 (영어 → Openverse 검색어)
# 실사 사진이 잘 나오는 경도: "aerial", "landscape", "architecture", "close-up"
COMPANY_QUERIES: dict[str, list[str]] = {
    "NVDA": ["computer chip macro", "silicon wafer technology", "data center server",
             "graphics processor circuit"],
    "AAPL": ["modern glass office building", "smartphone on desk", "minimal consumer electronics",
             "laptop workspace"],
    "MSFT": ["modern office interior", "software developer screen", "cloud computing concept",
             "corporate headquarters"],
    "GOOGL": ["data center corridor", "search engine abstract", "colorful office campus",
              "server room technology"],
    "AMZN": ["warehouse logistics automation", "delivery packages conveyor",
             "ecommerce fulfillment center", "shipping containers port"],
    "META": ["social network abstract", "modern tech campus", "virtual reality headset",
             "network connections concept"],
    "AVGO": ["semiconductor manufacturing", "circuit board macro", "fiber optic cables",
             "electronics factory"],
    "TSLA": ["electric car charging", "modern electric vehicle", "battery technology",
             "automotive factory robot"],
    "MU": ["memory chip close up", "computer memory module", "electronics component macro",
           "high tech manufacturing"],
    "AMD": ["computer processor close up", "gaming graphics card", "silicon wafer",
            "electronics circuit macro"],
    # 사업가 마인드용 추상 검색어
    "MINDSET": ["mountain summit path", "lone hiker fog forest", "old workshop tools",
                "handwritten notebook desk", "compass map vintage", "stone steps path",
                "open road horizon", "clock time abstract"],
}


def _clean_words(prompt: str) -> list[str]:
    """이미지 프롬프트에서 검색에 쓸 핵심 명사만 뽑는다.

    ⚠️ 실사 사진 검색에서는 **동물의 이름이 핵심**이다.
    프롬프트가 "hand-drawn line art" 같은 스타일 수식어로 가득하면
    검색어에 회로판·기계 같은 엉뚱한 것이 섞인다
    (2026-10-10 실측: 비버 우화인데 "stock image" → 회로판 이미지).
    → 명언 우화에서는 `characters` 의 종명(beaver, mole 등)을 우선 추출한다.
    """
    drop = re.compile(
        r"black and white|pencil drawing|pencil sketch|monochrome|graphite|sketch|"
        r"line art|hand-drawn|no color|no frame|no border|no text|cross-hatching|"
        r"etching|high detail|dramatic composition|shading|grayscale|woodcut|"
        r"engraving|full body visible|wide shot|side view|waist up|stock image|"
        r"pencil sketch portrait|quiet|soft light|close up",
        re.IGNORECASE)
    t = drop.sub(" ", prompt)
    t = re.sub(r"[^a-zA-Z0-9\s,']", " ", t)
    words = [w.strip().strip(",'") for w in t.split()]
    words = [w for w in words if len(w) > 2]
    words.sort(key=len, reverse=True)
    return words[:4] or ["nature landscape"]


# 동물 종명 → 실사 사진 검색 키워드 (Openverse 에서 결과가 실제로 나오는 것)
ANIMAL_QUERIES: dict[str, list[str]] = {
    "beaver":  ["beaver animal water", "beaver dam river", "beaver wildlife nature"],
    "mole":    ["mole animal burrow", "molehill meadow closeup", "mole wildlife"],
    "tortoise": ["tortoise shell closeup", "tortoise walking grass", "turtle reptile"],
    "rabbit":  ["rabbit animal grass", "hare wildlife meadow", "rabbit closeup nature"],
    "ant":     ["ant insect macro", "ants colony closeup", "ant nest soil"],
    "crab":    ["crab seashore closeup", "crab walking sand", "crab animal"],
    "squirrel": ["squirrel animal branch", "squirrel wildlife park", "squirrel closeup"],
    "owl":     ["owl bird closeup", "owl wildlife night", "owl feathers detail"],
    "turtle":  ["turtle reptile closeup", "turtle shell texture", "turtle nature"],
    "snail":   ["snail macro shell", "snail nature closeup", "snail wet leaf"],
    "fish":    ["fish underwater closeup", "school of fish", "fish scales detail"],
    "bird":    ["bird feathers macro", "bird wildlife branch", "bird closeup nature"],
    "elephant": ["elephant wildlife", "elephant trunk closeup", "elephant herd"],
    "fox":     ["fox wildlife forest", "fox closeup nature", "red fox snow"],
    "bear":    ["bear wildlife forest", "bear closeup nature", "brown bear mountains"],
    "wolf":    ["wolf wildlife snow", "wolf closeup forest", "wolf pack"],
    "owl ":    ["owl bird closeup", "owl wildlife", "owl feathers"],
}


def _animal_query(prompt: str) -> str | None:
    """프롬프트에서 동물 종명을 찾아 검색어로 만든다."""
    low = prompt.lower()
    for name, qs in ANIMAL_QUERIES.items():
        key = name.strip()
        if re.search(rf"\b{re.escape(key)}\b", low):
            return qs[0]
    return None


def openverse_search(query: str, n: int = 12,
                     min_w: int = 1024) -> list[dict]:
    """Openverse 이미지 검색 → 결과 리스트 (메타데이터 포함)."""
    try:
        r = requests.get(
            OPENVERSE,
            params={
                "q": query,
                "page_size": max(5, n),
                "license_type": "commercial",   # 상업적 사용 허용 라이선스만
                "mature": "false",
            },
            headers=UA, timeout=TIMEOUT)
        if not r.ok:
            return []
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for it in (r.json().get("results") or []):
        w, h = it.get("width") or 0, it.get("height") or 0
        url = it.get("url")
        if not url or w < min_w:
            continue
        out.append({
            "url": url,
            "w": w, "h": h,
            "title": (it.get("title") or "")[:80],
            "license": it.get("license") or "",
            "creator": (it.get("creator") or "")[:60],
            "source": it.get("source") or "",
            "foreign_landing_url": it.get("foreign_landing_url") or "",
        })
    return out


def fetch_photo(query: str, dest: Path, want_w: int = 1600,
                rng: random.Random | None = None,
                exclude_titles: set[str] | None = None) -> dict | None:
    """검색 → 다운로드 → dest 저장. 실패 시 None.

    여러 후보를 시도해서 **실제로 열리는 URL** 을 찾는다.
    (상위 검색 결과 중 원본 서버가 죽은 경우가 잦음)
    exclude_titles 로 이미 쓴 사진의 중복을 막는다.
    """
    rng = rng or random.Random()
    exclude_titles = exclude_titles or set()
    cands = openverse_search(query, n=16)
    if not cands:
        return None
    rng.shuffle(cands)
    for c in cands:
        if c["title"] in exclude_titles:
            continue
        try:
            ir = requests.get(c["url"], headers=UA, timeout=TIMEOUT)
            if not ir.ok or "image" not in ir.headers.get("content-type", ""):
                continue
            if len(ir.content) < 20000:      # 너무 작은 썸네일은 제외
                continue
            im = Image.open(io.BytesIO(ir.content))
            im.load()
            if im.width < 800:
                continue
            # 목표 크기로 리사이즈 (가로 기준, 세로는 비율 유지)
            if im.width > want_w:
                nh = round(im.height * want_w / im.width)
                im = im.resize((want_w, nh), Image.LANCZOS)
            im.convert("RGB").save(dest, "JPEG", quality=94)
            return {"query": query, "title": c["title"],
                    "license": c["license"], "creator": c["creator"],
                    "source": c["source"],
                    "landing": c["foreign_landing_url"]}
        except Exception:  # noqa: BLE001
            continue
    return None


def photo_to_sketch(src: Path, dest: Path, target_w: int = 1024,
                     target_h: int | None = None,
                     style: str = "pencil") -> None:
    """실사 사진 → 통일된 흑백 선화 톤 변환.

    target_h 를 주면 **그 비율로 가운데를 잘라낸다** (영상 9:16 대응).
    실사 촬영물이라 AI 생성 대비 선명도 손실 없이 변환된다.
    """
    im = Image.open(src).convert("RGB")

    # 1) 목표 비율로 크롭 후 리사이즈 (가로 기준, 세로 비율 유지)
    if target_h:
        want_ratio = target_w / target_h
        cur_ratio = im.width / im.height
        if cur_ratio > want_ratio:
            # 너무 넓다 → 좌우 잘라
            nw = round(im.height * want_ratio)
            x0 = (im.width - nw) // 2
            im = im.crop((x0, 0, x0 + nw, im.height))
        else:
            # 너무 높다 → 상하 잘라 (하단 55% 쪽 유지 — 지면이 있으므로)
            nh = round(im.width / want_ratio)
            y0 = int((im.height - nh) * 0.45)
            im = im.crop((0, y0, im.width, y0 + nh))
        im = im.resize((target_w, target_h), Image.LANCZOS)
    else:
        if im.width < im.height:
            nw, nh = target_w, round(im.height * target_w / im.width)
        else:
            nh = target_w
            nw = round(im.width * nh / im.height)
        im = im.resize((max(nw, 1), max(nh, 1)), Image.LANCZOS)

    # 2) 그레이스케일 + autocontrast (장면별 명도 차이 흡수)
    g = ImageOps.autocontrast(im.convert("L"), cutoff=1)

    if style == "pencil":
        # 자외선 펜스 스트로크: 중간 주파수를 강하게 살린다
        g = g.filter(ImageFilter.UnsharpMask(radius=2.2, percent=190, threshold=2))
        # 고주파 노이즈 제거 후 저주파 디테일 추가(연필 결)
        g = g.filter(ImageFilter.UnsharpMask(radius=6, percent=90, threshold=3))
        g = ImageEnhance.Contrast(g).enhance(1.28)
    elif style == "ink":
        g = g.filter(ImageFilter.UnsharpMask(radius=1.4, percent=240, threshold=1))
        g = ImageEnhance.Contrast(g).enhance(1.55)
    else:  # wash
        g = g.filter(ImageFilter.GaussianBlur(radius=0.8))
        g = ImageEnhance.Contrast(g).enhance(1.05)

    # 3) 하이라이트 클램프 — 흰 하늘이 자외선으로 날카롭게 번지는 것만 막는다.
    #    255 (순백) 만 종이색으로 내린다. 중간톤은 절대 건드리지 않아야
    #    이미지가 회색으로 바래지 않는다. (2026-10-10 실측 과적용 방지)
    g = g.point(lambda v: 250 if v > 250 else v)

    out = ImageOps.colorize(g, black="#14110d", white="#f4f0e6")
    out.save(dest, "JPEG", quality=93, optimize=True)


def search_for_scene(scene_prompt: str, company: str | None = None,
                     rng: random.Random | None = None,
                     dest: Path | None = None,
                     used_titles: set[str] | None = None) -> dict | None:
    """장면 프롬프트 + 선택된 기업 티커 → 사진 1장 + 크레딧 반환.

    dest 를 주면 그 경로에 원본 실사를 저장한다.
    used_titles 에 이미 쓴 사진 제목이 있으면 그것을 피한다(장면 간 중복 방지).
    """
    rng = rng or random.Random()
    dest = dest or _TMP_PHOTO
    used_titles = used_titles if used_titles is not None else set()

    # 1) ⭐ 동물 종명이 있으면 그걸 최우선으로 쓴다
    #    (우화 채널의 주역. 스타일 수식어만으로는 검색이 산으로 간다)
    animal = _animal_query(scene_prompt)
    queries: list[str] = []
    if animal:
        key = None
        low = scene_prompt.lower()
        for name in ANIMAL_QUERIES:
            if re.search(rf"\b{re.escape(name.strip())}\b", low):
                key = name
                break
        if key:
            queries += ANIMAL_QUERIES[key]
    # 2) 프롬프트에서 뽑은 키워드
    queries.append(" ".join(_clean_words(scene_prompt)))
    # 3) 기업 티커 전용 풀
    if company and company in COMPANY_QUERIES:
        queries += COMPANY_QUERIES[company]

    for q in queries:
        cred = fetch_photo(q, dest, want_w=1600, rng=rng,
                           exclude_titles=used_titles)
        if cred:
            used_titles.add(cred["title"])
            return {"credit": cred, "query": q}

    # 3) 전부 중복이었다. 재시도 단계를 3배로 늘려 서로 다른 사진 확보.
    #    (2단계로 두면 5장 중 1~2장이 폴백으로 빠지는 것이 실측 확인됨)
    big = [f"{w1} {w2}" for w1 in queries[:1]
           for w2 in ("detail", "close up", "wide view", "texture", "background")]
    big += [q for pool in COMPANY_QUERIES.values() for q in pool][:6]
    for q in big:
        cred = fetch_photo(q, dest, want_w=1600, rng=rng,
                           exclude_titles=used_titles)
        if cred:
            used_titles.add(cred["title"])
            return {"credit": cred, "query": q}

    # 4) 그래도 없으면 중복 허용 (최후 수단)
    for q in queries:
        cred = fetch_photo(q, dest, want_w=1600, rng=rng)
        if cred:
            return {"credit": cred, "query": q}
    return None


_TMP_PHOTO = Path(__file__).resolve().parent.parent / "data" / "_photo_tmp.jpg"


def record_credit(credits_path: Path, credit: dict) -> None:
    """크레딧을 JSONL 에 누적 (라이선스 출처 표기 의무)."""
    credits_path.parent.mkdir(parents=True, exist_ok=True)
    with credits_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(credit, ensure_ascii=False) + "\n")


def credits_text(credits_path: Path, limit: int = 12) -> str:
    """크레딧을 영상 설명용 텍스트로."""
    if not credits_path.exists():
        return ""
    seen: set[str] = set()
    rows: list[str] = []
    for line in credits_path.read_text(encoding="utf-8").splitlines():
        try:
            c = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        k = f"{c.get('title','')}|{c.get('creator','')}"
        if k in seen:
            continue
        seen.add(k)
        rows.append(f"{c.get('title','')} — {c.get('creator','')} "
                    f"({(c.get('license') or '').upper()})")
    if not rows:
        return ""
    head = "Images: " + " | ".join(rows[:limit])
    return head + (" …" if len(rows) > limit else "")