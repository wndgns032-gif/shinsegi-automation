"""발행 없이 '오늘의 콘텐츠'를 미리 만들어 본다 (품질 확인용).

사용: python scripts/preview.py [--cycle am] [--reels]
  - 명언 은행 선정 → 딥시크 생성 → 카드 렌더 → (옵션) 리일스 mp4 까지
  - 실제 발행은 하지 않고, 명언 로테이션 이력도 남기지 않는다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(BASE / ".env", override=True)

from src import generator, quotes  # noqa: E402
from src.cards import render_cards  # noqa: E402

DATA = BASE / "data"


def _arg(name: str) -> str | None:
    """--cycle am 같은 형태의 인자 값을 읽는다."""
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def main() -> None:
    want_reels = "--reels" in sys.argv
    cycle = _arg("--cycle") or "ev"  # am | pm | ev | night
    theme = generator.THEME_BY_CYCLE.get(cycle)
    quote = quotes.pick(theme, exclude=set(), data_dir=DATA)
    print(f"테마: {quotes.THEME_LABELS.get(theme, theme)}")
    print(f"명언: [{quote.id}] {quote.author_of('ko')} — {quote.text_of('ko')}\n")

    contents = generator.generate(quote, BASE / "config" / "prompts", theme=theme)
    stamp = datetime.now(quotes.KST).strftime("%Y-%m-%d_%H%M")
    root = DATA / "preview" / stamp
    root.mkdir(parents=True, exist_ok=True)

    for lang, c in contents.items():
        render_cards(c["ig_cards"], root / lang, lang, author=c.get("quote_author"))
        print(f"───────── {lang}  (화자: {c.get('quote_author') or '미표기'}) ─────────")
        for i, card in enumerate(c["ig_cards"], 1):
            print(f"  {i}. {card}")
        print(f"  [caption] {c['ig_caption'][:120]}")
        print(f"  [reels] {c['reels_script']}\n")

    (root / "content.json").write_text(json.dumps(
        {"source": quote.source, "url": quote.url, "title": quote.title,
         "theme": theme,
         "quote": {"id": quote.id, "author": quote.author, "text": quote.text},
         "contents": contents},
        ensure_ascii=False, indent=2), encoding="utf-8")

    if want_reels:
        from src import reels
        for lang, c in contents.items():
            cards = sorted((root / lang).glob("card_*.png"),
                           key=lambda x: int(x.stem.split("_")[1]))
            mp4 = reels.make_reels(c["reels_script"], lang, cards, root / "reels")
            print(f"reels {lang}: {mp4} ({mp4.stat().st_size // 1024}KB)")

    print(f"\n출력 폴더: {root}")


if __name__ == "__main__":
    main()
