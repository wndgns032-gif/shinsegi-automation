"""새 파이프라인(명언 은행) 결과를 게시 없이 미리 확인하는 미리보기.

사용법:
  python scripts/quote_preview.py              # 테마 4개 전부 생성
  python scripts/quote_preview.py hardship     # 테마 하나만 (growth|courage|hardship|attitude)

출력: data/preview/quote_preview_<테마|all>.html
※ 실제 게시·업로드는 하지 않고, 명언 로테이션 이력도 남기지 않는다.
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from src import generator, quotes  # noqa: E402

LANG_LABEL = {"ko": "한국어", "en": "영어", "zh-cn": "중국어", "fr": "프랑스어"}
ORDER = ("ko", "en", "zh-cn", "fr")
STEP_LABEL = ["① 명언", "② 쉬운 풀이", "③ 일상 예시", "④ 오늘 한 가지", "⑤ 질문"]

CSS = """
:root{--bg:#f7f8fa;--card:#fff;--ink:#1b1f24;--sub:#5b6472;--line:#e4e7eb;--acc:#2563eb;--hl:#fff8e6}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:16px/1.7 -apple-system,'Malgun Gothic','Apple SD Gothic Neo',Segoe UI,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:36px 20px 90px}
h1{font-size:26px;margin:0 0 6px}
h2{font-size:19px;margin:32px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--line)}
h3{font-size:16px;margin:0 0 10px}
.lead{color:var(--sub);margin:0 0 22px;font-size:15px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:14px}
.q{background:var(--hl);border:1px solid #f0dcae}
table{width:100%;border-collapse:collapse;font-size:15px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{width:110px;color:var(--sub);font-weight:600;white-space:nowrap}
.badge{display:inline-block;background:#eef2f7;color:#334155;border-radius:20px;
 padding:2px 12px;font-size:13px;margin-right:8px}
.script{white-space:pre-wrap;background:#f4f6f8;border-radius:10px;padding:12px 14px;font-size:15px}
details{margin-top:10px}
summary{cursor:pointer;color:var(--acc);font-size:14px}
"""


def _cards_table(cards: list[str]) -> str:
    rows = []
    for i, s in enumerate(cards):
        step = STEP_LABEL[i] if i < len(STEP_LABEL) else f"{i+1}"
        rows.append(f"<tr><th>{step}</th><td>{html.escape(s)}</td></tr>")
    return "<table>" + "".join(rows) + "</table>"


def build(theme: str, quote: quotes.Quote, contents: dict) -> None:
    out = ROOT / "data" / "preview"
    out.mkdir(parents=True, exist_ok=True)
    parts = [
        f'<h2>{html.escape(quotes.THEME_LABELS.get(theme, theme))} '
        f'<span class="badge">{theme}</span></h2>',
        f'<div class="card q"><b>오늘의 명언</b><br>'
        f'<span style="font-size:18px">{html.escape(quote.text_of("ko"))}</span><br>'
        f'<span style="color:var(--sub)">— {html.escape(quote.author_of("ko"))}</span></div>',
    ]
    for lang in ORDER:
        c = contents[lang]
        parts.append(
            f'<div class="card"><h3>{LANG_LABEL[lang]} '
            f'<span class="badge">{html.escape(c.get("quote_author", ""))}</span></h3>'
            f'{_cards_table(c["ig_cards"])}'
            f'<details><summary>낭독 대본(영상에서 실제로 읽는 문장) 펼치기</summary>'
            f'<div class="script">{html.escape(c.get("reels_script", ""))}</div></details>'
            f'<details><summary>캡션 / 스레드 / 티저 펼치기</summary>'
            f'<div class="script">{html.escape(c.get("ig_caption", ""))}</div>'
            f'<div class="script">{html.escape(c.get("threads_text", ""))}</div></details></div>')
    head = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            f'<title>명언 파이프라인 미리보기</title><style>{CSS}</style></head><body><div class="wrap">'
            f'<h1>명언 기반 콘텐츠 미리보기</h1>'
            f'<p class="lead">커뮤니티 글 없이 <b>명언 은행 → 명언 1장 + 쉬운 풀이 + 일상 예시 + 오늘 한 가지 + 질문</b>'
            f' 구조로 만든 결과입니다. 게시되지 않았습니다.</p>')
    p = out / f"quote_preview_{theme}.html"
    p.write_text(head + "".join(parts) + "</div></body></html>", encoding="utf-8")
    print(f"  wrote {p}")


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    themes = list(quotes.THEME_LABELS) if arg == "all" else [arg]
    used: set[str] = set()
    merged: list[str] = []
    for theme in themes:
        quote = quotes.pick(theme, exclude=used, data_dir=ROOT / "data")
        used.add(quote.id)
        print(f"[{theme}] {quote.author_of('ko')} — {quote.text_of('ko')}")
        contents = generator.generate(quote, ROOT / "config" / "prompts", theme=theme)
        build(theme, quote, contents)
        for lang in ORDER:
            print(f"  -{lang}- " + " | ".join(contents[lang]["ig_cards"]))
        merged.append(f"=== {theme} ({quote.author_of('ko')}) ===\n"
                      + "\n".join(f"[{lang}] " + " / ".join(contents[lang]["ig_cards"])
                                  for lang in ORDER))

    # 전체 요약 페이지
    if len(themes) > 1:
        summary = ROOT / "data" / "preview" / "quote_preview_summary.txt"
        summary.write_text(
            f"생성 시각: {datetime.now().isoformat(timespec='seconds')}\n\n"
            + "\n\n".join(merged), encoding="utf-8")
        print(f"\n요약: {summary}")


if __name__ == "__main__":
    main()
