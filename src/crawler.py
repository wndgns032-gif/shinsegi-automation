"""커뮤니티 크롤러 + 조회수 1위 선정 로직."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


@dataclass
class Post:
    id: str
    source: str
    title: str
    url: str
    views: int | None
    published_at: datetime | None = None
    content: str = ""
    comments: list[str] = field(default_factory=list)


def load_sources(config_path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_all(cfg: dict) -> list[Post]:
    posts: list[Post] = []
    for src in cfg.get("sources", []):
        if not src.get("enabled", True):
            continue
        try:
            if src["type"] == "mock":
                posts.extend(_fetch_mock(src))
            elif src["type"] == "css":
                posts.extend(_fetch_css(src, cfg.get("hours_window", 24)))
        except Exception as e:  # noqa: BLE001 - 한 소스 실패가 전체 사이클을 죽이지 않게
            print(f"[crawler] 소스 수집 실패: {src.get('name')} - {e}")
    return posts


def _fetch_mock(src: dict) -> list[Post]:
    now = datetime.now(KST)
    samples = [
        ("m1", "퇴사각 잡히는 순간", 15230, "상사가 회의에서 내 기획을 자기 아이디어처럼 발표했다. 참다못해 자리에서 정정했더니 분위기가 싸해졌다."),
        ("m2", "신입이 대기업 그만두겠답니다", 8941, "입사 3개월차 신입이 야근 문화 못 견디겠다며 퇴사 선언. 팀장이 붙잡는 중."),
        ("m3", "연봉 협상에서 300 올린 후기", 0, ""),  # 조회수 표시 없음 케이스 -> 제외되어야 함
    ]
    comments = [
        "나도 똑같은 일 겪었는데 그냥 참았음",
        "정정한 거 잘했음. 가만히 있으면 계속 당함",
        "상사가 좀 이상하네. 이직 준비필",
        "근데 자리에서 바로 말하면 역효과 나지 않음?",
    ]
    posts = []
    for pid, title, views, content in samples:
        posts.append(Post(
            id=pid, source=src["name"], title=title,
            url=f"mock://{src['name']}/{pid}",
            views=views if views > 0 else None,
            published_at=now - timedelta(hours=3),
            content=content or title,
            comments=comments if pid == "m1" else comments[:2],
        ))
    return posts


def _fetch_css(src: dict, hours_window: int) -> list[Post]:
    resp = requests.get(src["list_url"], headers=UA, timeout=30)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding  # euc-kr 사이트 대응
    soup = BeautifulSoup(resp.text, "html.parser")
    cutoff = datetime.now(KST) - timedelta(hours=hours_window)
    posts = []
    for i, item in enumerate(soup.select(src["item_selector"])):
        # 공지/고정/광고 행 제외
        skip_class = src.get("row_skip_class")
        if skip_class and skip_class in " ".join(item.get("class") or []):
            continue
        fa = src.get("row_filter_attr") or {}
        if fa and item.get(fa.get("name")) == fa.get("exclude"):
            continue

        title_el = item.select_one(src["title_selector"])
        link_el = item.select_one(src.get("link_selector", src["title_selector"]))
        if not title_el or not link_el:
            continue
        href = (link_el.get("href") or "").strip()
        if not href or href.lower().startswith("javascript"):
            continue
        url = urljoin(resp.url, href)

        published = _parse_time(item.select_one(src["time_selector"])) if src.get("time_selector") else None
        if published and published < cutoff:
            continue
        views_el = item.select_one(src["views_selector"]) if src.get("views_selector") else None
        posts.append(Post(
            id=url or f"{src['name']}-{i}",
            source=src["name"],
            title=title_el.get_text(strip=True),
            url=url,
            views=parse_views(views_el.get_text(strip=True)) if views_el else None,
            published_at=published,
        ))
    return posts


def fetch_detail(post: Post, cfg: dict) -> Post:
    """선정된 게시물의 본문·댓글을 채운다. mock 소스는 이미 채워져 있다."""
    if post.content or not post.url.startswith("http"):
        return post
    src = next((s for s in cfg.get("sources", []) if s["name"] == post.source), None)
    if not src or "detail" not in src:
        post.content = post.content or post.title
        return post
    resp = requests.get(post.url, headers=UA, timeout=30)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")
    det = src["detail"]

    content_sel = det.get("content_selector")
    if content_sel:
        # 셀렉터가 여러 요소에 매칭되면 본문이 가장 긴 것을 선택
        bodies = soup.select(content_sel)
        post.content = max((b.get_text("\n", strip=True) for b in bodies), key=len, default="")
    if not post.content:
        post.content = post.title

    comment_sel = det.get("comment_selector") or ""
    max_c = det.get("max_comments", 0)
    if comment_sel and max_c:
        post.comments = [
            c.get_text(" ", strip=True)
            for c in soup.select(comment_sel)[:max_c]
            if c.get_text(strip=True)
        ]
    return post


def parse_views(text: str) -> int | None:
    """'조회수 1,234' 같은 문자열에서 숫자만 추출. 숫자 없으면 None(=선정 제외)."""
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def _parse_time(time_el) -> datetime | None:
    """다양한 커뮤니티 시간 형식 파싱. 'HH:MM'만 있으면 오늘로 간주. 실패 시 None(필터 통과)."""
    if time_el is None:
        return None
    raw = (time_el.get("title") or time_el.get_text(strip=True)).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y.%m.%d %H:%M", "%Y-%m-%d", "%Y.%m.%d", "%y.%m.%d", "%m.%d %H:%M"):
        try:
            return datetime.strptime(raw[: len(datetime.now().strftime(fmt))], fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if m:  # 시간만 표시 = 오늘 글
        now = datetime.now(KST)
        return now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    return None


def pick_post(posts: list[Post], used_ids: set[str]) -> Post | None:
    """원시 조회수 1위 선정. 조회수 없는 글 제외. 당일 이미 사용한 글은 다음 순위로."""
    candidates = [p for p in posts if p.views is not None]
    candidates.sort(key=lambda p: p.views, reverse=True)
    for p in candidates:
        if p.id not in used_ids:
            return p
    return None


def ranked_candidates(posts: list[Post], used_ids: set[str]) -> list[Post]:
    """조회수 내림차순 후보 목록 (사용 글 제외)."""
    candidates = [p for p in posts if p.views is not None and p.id not in used_ids]
    candidates.sort(key=lambda p: p.views, reverse=True)
    return candidates
