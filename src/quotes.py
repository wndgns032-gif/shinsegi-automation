"""명언 은행 — 콘텐츠 재료 선정.

커뮤니티를 크롤링하지 않는다. config/quotes.yaml 의 검증된 명언 풀에서
사이클(테마)에 맞는 명언 한 줄을 고르고, 최근 사용 이력을 피해 로테이션한다.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

KST = timezone(timedelta(hours=9))
# ⚠️ 2026-10-11 로이 확정 — 언어 축소를 ko + en 2개로.
#   근거 (YouTube 공개 통계 실측, data/youtube_public_stats.json):
#     ko   48편  합계 26,844  중앙값 581  100회+ 43편(90%)
#     en    6편  합계    990  중앙값 250  100회+  4편(67%)
#     zh-cn 9편  합계    135  중앙값   2  100회+  0편( 0%)  ← 큐레이션 실패
#     fr    9편  합계     29  중앙값   0  100회+  0편( 0%)  ← 큐레이션 실패
#   ko+en 이 전체 조회수의 99.4%. zh-cn·fr 은 18편 올려서 164회.
#   하루 3편 × 2언어 = 6편. (2026-06-01 기준 videos.insert 独立버킷은 100회/일
#   이므로 6편은 제약 아님 — 축소는 순수하게 시장 성과 판단이다.)
#
#   되돌리기: 여기에 "zh-cn", "fr" 를 다시 넣으면 된다.
#   TTS 프로필(tts.py VOICE_PROFILES)과 채널 토큰(.env)은 그대로 살아 있어
#   재개 시 코드 수정 없이 되살아난다. 채널도 삭제되지 않고 동결된다.
LANGS = ["en", "ko"]
BANK = Path(__file__).resolve().parent.parent / "config" / "quotes.yaml"
HISTORY_NAME = "quotes_used.json"
NO_REPEAT_DAYS = 7  # 같은 명언은 7일 이내 재사용하지 않는다

THEME_LABELS = {
    "growth": "배움과 성장",
    "courage": "도전과 용기",
    "hardship": "고난과 역경",
    "attitude": "인생의 철학과 태도",
}


@dataclass
class Quote:
    """크롤러 Post 와 호환되는 최소 인터페이스(source/id/url/title/views/comments)."""
    id: str
    theme: str
    author: dict
    text: dict
    source: str = "quotes.yaml"
    views: int | None = None
    comments: list = field(default_factory=list)
    published_at: datetime | None = None

    @property
    def url(self) -> str:
        return f"quote://{self.id}"

    @property
    def title(self) -> str:
        return f"{self.author.get('ko', '')} — {self.text.get('ko', '')}"

    def author_of(self, lang: str) -> str:
        return str(self.author.get(lang, "") or "")

    def text_of(self, lang: str) -> str:
        return str(self.text.get(lang, "") or "")


def load_bank(path: Path = BANK) -> list[Quote]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for item in raw.get("quotes", []):
        miss = [l for l in LANGS if not item.get("text", {}).get(l) or not item.get("author", {}).get(l)]
        if miss:
            print(f"[quotes] {item.get('id')} 언어 누락({miss}) — 건너뜀")
            continue
        out.append(Quote(id=item["id"], theme=item["theme"],
                         author=item["author"], text=item["text"]))
    return out


def _history_path(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / HISTORY_NAME


def load_history(data_dir: Path) -> dict[str, str]:
    """{명언id: 마지막 사용일(YYYY-MM-DD)}"""
    p = _history_path(data_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_history(data_dir: Path, hist: dict[str, str]) -> None:
    _history_path(data_dir).write_text(
        json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_used(data_dir: Path, quote_id: str) -> None:
    hist = load_history(data_dir)
    hist[quote_id] = datetime.now(KST).date().isoformat()
    save_history(data_dir, hist)


def pick(theme: str, exclude: set[str] | None = None,
         data_dir: Path | None = None) -> Quote:
    """테마에 맞는 명언 1개 선정.

    최근 NO_REPEAT_DAYS 일 이내에 쓴 명언은 제외하고, 남은 것 중 무작위.
    전부 소진됐으면(테마 풀이 작을 때) 가장 오래된 것으로 폴백.
    """
    exclude = set(exclude or set())
    pool = [q for q in load_bank() if q.theme == theme]
    if not pool:
        raise ValueError(f"테마 '{theme}' 명언 없음 — quotes.yaml 확인")

    hist = load_history(data_dir) if data_dir else {}
    today = datetime.now(KST).date()
    cutoff = (today - timedelta(days=NO_REPEAT_DAYS)).isoformat()

    def recent(q: Quote) -> bool:
        return hist.get(q.id, "") >= cutoff

    fresh = [q for q in pool if q.id not in exclude and not recent(q)]
    if fresh:
        return random.choice(fresh)
    usable = [q for q in pool if q.id not in exclude]
    if usable:  # 최근에 썼지만 하루 안 겹침 조건은 통과 → 가장 오래된 것
        return min(usable, key=lambda q: hist.get(q.id, ""))
    return min(pool, key=lambda q: hist.get(q.id, ""))  # 최후 폴백


def themes_summary() -> str:
    counts: dict[str, int] = {}
    for q in load_bank():
        counts[q.theme] = counts.get(q.theme, 0) + 1
    return ", ".join(f"{THEME_LABELS.get(k, k)}({v})" for k, v in counts.items())
