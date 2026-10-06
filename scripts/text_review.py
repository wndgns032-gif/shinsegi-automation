"""오늘 나간 글을 사람이 읽기 좋게 HTML 로 뽑아준다 (검수용).

사용법:
  python scripts/text_review.py              # 오늘
  python scripts/text_review.py 2026-09-22   # 특정 날짜

출력: data/preview/text_review_<date>.html  (브라우저에서 열어보면 됨)
"""
from __future__ import annotations

import html
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

LANG_LABEL = {"ko": "한국어", "en": "영어", "zh-cn": "중국어", "fr": "프랑스어"}
CYCLE_LABEL = {"am": "06:00", "pm": "12:00", "ev": "18:00", "night": "23:00"}
ORDER = ("ko", "en", "zh-cn", "fr")

CSS = """
:root{--bg:#f7f8fa;--card:#fff;--ink:#1b1f24;--sub:#5b6472;--line:#e4e7eb;--acc:#2563eb;--hl:#fff8e6}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:16px/1.7 -apple-system,'Malgun Gothic','Apple SD Gothic Neo',Segoe UI,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:36px 20px 90px}
h1{font-size:27px;margin:0 0 6px}
h2{font-size:19px;margin:34px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--line)}
h3{font-size:16px;margin:0 0 10px}
.lead{color:var(--sub);margin:0 0 24px;font-size:15px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:16px}
.q{background:var(--hl);border:1px solid #f0dcae}
.step{display:flex;gap:10px;margin:8px 0;font-size:15px}
.num{flex:0 0 24px;height:24px;line-height:24px;text-align:center;background:var(--acc);color:#fff;
 border-radius:50%;font-size:13px;margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line);vertical-align:top}
th{width:96px;color:var(--sub);font-weight:600}
.badge{display:inline-block;background:#eef2f7;color:#334155;border-radius:20px;
 padding:2px 12px;font-size:13px;margin-right:8px}
.script{white-space:pre-wrap;background:#f4f6f8;border-radius:10px;padding:12px 14px;font-size:15px}
details{margin-top:10px}
summary{cursor:pointer;color:var(--acc);font-size:14px}
ul{margin:6px 0 0;padding-left:20px}
li{margin:5px 0}
code{background:#eef1f5;padding:2px 6px;border-radius:5px;font-size:13px}
.mono{font-family:ui-monospace,Consolas,monospace}
"""


def card_list(items: list[str]) -> str:
    out = []
    for i, s in enumerate(items, 1):
        out.append(f"<tr><th>카드 {i}</th><td>{html.escape(s)}</td></tr>")
    return "<table>" + "".join(out) + "</table>"


def build(day: str) -> Path:
    day_dir = DATA / "cards" / day
    cycles = sorted(p for p in day_dir.glob("*/content.json")) if day_dir.exists() else []
    if not cycles:
        raise SystemExit(f"{day} 콘텐츠가 없습니다.")

    parts: list[str] = []
    for cp in cycles:
        arch = json.loads(cp.read_text(encoding="utf-8"))
        contents = arch.get("contents", {})
        theme = arch.get("theme", "")
        cycle = cp.parent.name
        parts.append(
            f'<h2>{CYCLE_LABEL.get(cycle, cycle)} 회차 <span class="badge">테마: {html.escape(theme)}</span></h2>')
        for lang in ORDER:
            c = contents.get(lang)
            if not c:
                continue
            author = c.get("quote_author", "")
            cards_ = c.get("ig_cards", [])
            script = c.get("reels_script", "")
            parts.append(
                f'<div class="card"><h3>{LANG_LABEL.get(lang, lang)}'
                f' <span class="badge">화자: {html.escape(author)}</span></h3>'
                f'<div class="q" style="padding:10px 14px;border-radius:10px;margin-bottom:12px">'
                f'<b>명언:</b> {html.escape(cards_[0] if cards_ else "")}</div>'
                f'{card_list(cards_)}'
                f'<details><summary>낭독 대본(영상에서 실제로 읽는 글) 펼치기</summary>'
                f'<div class="script">{html.escape(script)}</div></details></div>')
            if lang != "ko":
                continue

    head = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>{day} 나간 글 검수</title><style>{CSS}</style></head><body><div class="wrap">
<h1>{day} — 오늘 나간 글 검수</h1>
<p class="lead">영상에서 <b>실제로 읽히는 문장</b>을 그대로 모았습니다. 읽어보시고
"이렇게 바꿔줘" 하시면 그대로 반영합니다.</p>

<div class="card">
<h3>1) .md 파일이 뭐예요?</h3>
<p><b>메모장으로 여는 텍스트 파일</b>입니다. <code>#</code>는 제목, <code>-</code>는 목록 표시일 뿐이고,
프로그램 코드가 아니라 <b>사람이 읽는 설명서</b>예요. 더블클릭하면 메모장/VS Code로 열립니다.</p>
<ul>
<li><code>README.md</code> — 이 자동화 프로그램 사용법</li>
<li><code>PRD_다국어_SNS_콘텐츠_자동화_MVP.md</code> — 처음 설계서(무엇을 어떻게 만들지)</li>
<li><code>SETUP_계정가이드.md</code> — 계정 만들기 순서</li>
<li><code>COST_비용구조.md</code> — 돈이 어디에 드는지</li>
<li><code>.workbuddy/memory/2026-09-22.md</code> — 제 작업 일지(오늘 뭘 했는지)</li>
</ul>
<p><b>중요:</b> 영상에 나가는 글은 .md에 없고
<code>data/cards/{day}/회차/content.json</code> 에 들어있습니다. 이 페이지가 그 파일을 읽어서 보여주는 겁니다.</p>
</div>

<div class="card">
<h3>2) 지금 글을 만드는 순서 (커뮤니티 크롤링 → 명언 은행으로 교체)</h3>
<div class="step"><span class="num">1</span><div><code>config/quotes.yaml</code> — 직접 검증해 모아둔 <b>명언 28개</b>에서 하나를 고릅니다
(테마별 7개씩 · 최근 7일 안에 쓴 명언은 자동 제외)</div></div>
<div class="step"><span class="num">2</span><div>그 명언을 <b>원문 그대로</b> 1장 카드에 올립니다 (고치지도 번역하지도 않음)</div></div>
<div class="step"><span class="num">3</span><div>뒤에 4장을 붙입니다: <b>쉬운 풀이 → 일상 예시 → 오늘 한 가지 → 질문</b></div></div>
<div class="step"><span class="num">4</span><div>이 5장을 이어 <b>낭독 대본</b>으로 만들고 4개 언어로 씁니다 → 이게 영상에서 읽히는 글</div></div>
<div class="step"><span class="num">5</span><div>각 언어별 TTS로 읽고, 배경음악을 입혀 영상으로 만듭니다</div></div>
<p style="color:#047857;margin:12px 0 0"><b>달라진 점:</b> 커뮤니티 글을 재료로 쓰지 않으니 장면이 튀지 않고,
한국어는 한국어로 · 영어는 영어로 <b>처음부터</b> 씁니다(번역투 금지 규칙 추가).</p>
</div>

<div class="card" style="border-color:#b9ddc4;background:#f2faf4">
<h3>3) 카드 5장의 역할</h3>
<ul>
<li><b>① 명언</b> — 표지. 명언 은행의 문장 그대로 (화자는 따로 표기)</li>
<li><b>② 쉬운 풀이</b> — 중학생이 한 번에 이해하는 한 문장 ("쉽게 말하면 ~라는 뜻이에요")</li>
<li><b>③ 일상 예시</b> — 누구나 겪을 법한 구체적 장면 (메일 한 통, 지각, 통장 잔고처럼 손에 잡히는 것)</li>
<li><b>④ 오늘 한 가지</b> — 오늘 당장 5분 안에 해볼 수 있는 아주 작은 행동</li>
<li><b>⑤ 질문</b> — 읽는 사람의 경험을 묻고 끝</li>
</ul>
</div>

<h2>오늘 실제로 나간 글</h2>
"""
    out = DATA / "preview" / f"text_review_{day}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    (head + "".join(parts) + "</div></body></html>").encode("utf-8")
    out.write_text(head + "".join(parts) + "</div></body></html>", encoding="utf-8")
    return out


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    p = build(d)
    print("wrote", p)
