"""인스타그램 계정별 '무엇이 실제로 올라갔는지' 타임라인 리포트.

언어 계정 × 최근 게시물을 조회해 카드뉴스(CAROUSEL_ALBUM)와 영상(VIDEO/REELS)을
구분해서 보여주고, 같은 글이 짧은 시간에 여러 번 올라간 중복을 표시한다.

사용: python scripts/ig_activity.py [일수]   (기본 2일)
"""
from __future__ import annotations

import html
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(BASE / ".env", override=True)
import requests  # noqa: E402

GRAPH = "https://graph.facebook.com/v23.0"
KST = timezone(timedelta(hours=9))
LANGS = ["en", "ko", "zh-cn", "fr"]
LABEL = {"en": "EN (shinsegi.en)", "ko": "KO (shinsegi.kr)",
         "zh-cn": "ZH (shinsegi.zh)", "fr": "FR (shinsegi.fr)"}


def fetch(uid: str, token: str, limit: int = 25) -> list[dict]:
    r = requests.get(f"{GRAPH}/{uid}/media", params={
        "fields": "id,media_type,timestamp,caption,permalink",
        "limit": limit, "access_token": token}, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
    return r.json().get("data", [])


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    since = datetime.now(KST) - timedelta(days=days)
    out = BASE / "data" / "preview" / "ig_activity.html"
    out.parent.mkdir(parents=True, exist_ok=True)

    sections, stats = [], {}
    for lang in LANGS:
        key = lang.upper().replace("-", "_")
        uid, token = os.getenv(f"IG_{key}_USER_ID"), os.getenv(f"IG_{key}_TOKEN")
        if not uid or not token:
            sections.append(f"<h2>{LABEL[lang]}</h2><p class=err>자격증명 없음</p>")
            continue
        try:
            media = fetch(uid, token)
        except Exception as e:  # noqa: BLE001
            sections.append(f"<h2>{LABEL[lang]}</h2><p class=err>조회 실패: {html.escape(str(e)[:200])}</p>")
            continue

        rows = []
        for m in media:
            ts = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")).astimezone(KST)
            if ts < since:
                continue
            rows.append({**m, "kst": ts})
        rows.sort(key=lambda x: x["kst"], reverse=True)

        # 중복 표시: 같은 캡션이 30분 안에 2번 이상
        dup_idx = set()
        for i, a in enumerate(rows):
            for j, b in enumerate(rows):
                if i >= j:
                    continue
                same = (a.get("caption") or "").strip()[:200] == (b.get("caption") or "").strip()[:200]
                if same and abs((a["kst"] - b["kst"]).total_seconds()) <= 1800:
                    dup_idx.add(i)
                    dup_idx.add(j)

        cnt = Counter("VIDEO" if r["media_type"] in ("VIDEO", "REELS") else "CARD"
                      for r in rows)
        stats[lang] = cnt

        body = "".join(_row(r, i in dup_idx) for i, r in enumerate(rows)) or \
            "<tr><td colspan=4 class=dim>기간 내 게시물 없음</td></tr>"
        n_video, n_card = cnt["VIDEO"], cnt["CARD"]
        sections.append(f"""
<h2>{LABEL[lang]} <span class=badge v>영상 {n_video}</span> <span class=badge c>카드 {n_card}</span></h2>
<table>
<tr><th>시간(KST)</th><th>형태</th><th>내용</th><th>비고</th></tr>
{body}
</table>""")

    doc = f"""<!doctype html><meta charset=utf-8>
<title>IG 업로드 현황</title>
<style>
 body{{font-family:-apple-system,'Malgun Gothic',sans-serif;background:#f6f7f9;color:#1c1f23;
       margin:0;padding:28px;line-height:1.55}}
 h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#6b7280;font-size:13px;margin-bottom:22px}}
 h2{{font-size:16px;margin:26px 0 8px;display:flex;align-items:center;gap:8px}}
 .badge{{font-size:12px;padding:2px 9px;border-radius:20px;font-weight:600}}
 .badge.v{{background:#fee2e2;color:#b91c1c}} .badge.c{{background:#e0e7ff;color:#3730a3}}
 table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;
        overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.07)}}
 th{{background:#f3f4f6;font-size:12px;color:#6b7280;text-align:left;padding:9px 12px}}
 td{{padding:9px 12px;border-top:1px solid #f0f1f3;font-size:13px;vertical-align:top}}
 .t{{font-variant-numeric:tabular-nums;color:#4b5563;white-space:nowrap}}
 .tv{{color:#b91c1c;font-weight:700}} .tc{{color:#4338ca;font-weight:700}}
 .cap{{color:#374151}} .dup{{background:#fef2f2}}
 .dupmark{{color:#b91c1c;font-size:12px;font-weight:700}}
 .err{{background:#fff;border:1px solid #fecaca;background:#fef2f2;padding:12px;border-radius:8px;color:#b91c1c}}
 .dim{{color:#9ca3af}}
 .note{{background:#fff;border-left:4px solid #f59e0b;padding:14px 16px;border-radius:8px;
        margin:18px 0;font-size:13px}}
 .box{{max-width:900px;margin:0 auto}}
</style>
<div class=box>
<h1>인스타 업로드 현황</h1>
<div class=sub>조회 시각 {datetime.now(KST):%Y-%m-%d %H:%M} KST · 최근 {days}일 · IG Graph API 실조회</div>
<div class=note>
<b>영상(VIDEO)</b> = 오전 8시·오후 1시·저녁 7시, 하루 3회 올라가는 숏폼.<br>
<b>카드(CAROUSEL)</b> = 오전 6시·낮 12시·저녁 6시·밤 11시, 하루 4회 올라가는 카드뉴스.<br>
두 종류가 <b>같은 계정에 같이</b> 올라가고 있어서 피드에는 카드가 더 많아 보입니다.
</div>
{"".join(sections)}
</div>"""
    out.write_text(doc, encoding="utf-8")
    print(f"리포트: {out}")
    for lang in LANGS:
        c = stats.get(lang)
        if c:
            print(f"  {lang:<6} 영상 {c['VIDEO']} / 카드 {c['CARD']}")


def _row(m: dict, dup: bool) -> str:
    cap = (m.get("caption") or "").replace("\n", " ")
    cap = html.escape(cap[:90]) + ("…" if len(cap) > 90 else "")
    is_video = m["media_type"] in ("VIDEO", "REELS")
    cls = ' class=dup' if dup else ''
    return (f"<tr{cls}><td class=t>{m['kst']:%m-%d %H:%M}</td>"
            f"<td class={'tv' if is_video else 'tc'}>{'영상' if is_video else '카드'}</td>"
            f"<td class=cap>{cap or '(캡션 없음)'}</td>"
            f"<td>{'<span class=dupmark>중복</span>' if dup else ''}</td></tr>")


if __name__ == "__main__":
    main()
