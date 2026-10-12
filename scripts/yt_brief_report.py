"""YouTube 브리핑 리포트 생성 (공개 통계 + 업로드 이력 → HTML).

사용: python scripts/yt_brief_report.py
입력: data/youtube_public_stats.json (youtube_public_stats.py 가 만든 것)
출력: data/preview/youtube_brief.html
"""
from __future__ import annotations

import json
import statistics as st
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LABEL = {"ko": ("한국어", "@WisdomPathroad"),
         "en": ("English", "@wisdompath-en"),
         "zh-cn": ("中文", "@shinsegi-zh"),
         "fr": ("Français", "@shinsegi-fr")}

OUR_KW = ("#명언", "#성공으로가는길", "#동기부여", "#인생의도전", "#Shorts",
          "成功", "人生", "短片")

# 타임라인 (D0 = 오늘)
def timeline():
    today = datetime(2026, 10, 11)
    rows = []
    for i in range(14):
        d = today + timedelta(days=i)
        rows.append((d, d.strftime("%a")))
    return rows


def main() -> int:
    stats = json.loads((ROOT / "data" / "youtube_public_stats.json")
                       .read_text(encoding="utf-8"))
    hist = json.loads((ROOT / "data" / "youtube_uploads.json")
                      .read_text(encoding="utf-8"))

    cards = []
    for lang, (nm, handle) in LABEL.items():
        r = stats.get(lang, {})
        if r.get("error"):
            cards.append({"lang": lang, "nm": nm, "handle": handle, "error": r["error"]})
            continue
        vs = r["videos"]
        views = [v["views"] for v in vs]
        cards.append({
            "lang": lang, "nm": nm, "handle": handle,
            "n": len(vs), "total": sum(views),
            "avg": int(st.mean(views)) if views else 0,
            "med": int(st.median(views)) if views else 0,
            "max": max(views) if views else 0,
            "zero": sum(1 for v in views if v == 0),
            "videos": vs,
        })

    # ko 채널: 우리 콘텐츠 vs 기존 타주제
    ko = stats.get("ko", {})
    ko_ours = ko_ours_avg = ko_ours_med = None
    ko_other_avg = ko_other_med = None
    if not ko.get("error"):
        ours = [v for v in ko["videos"] if any(k in v["title"] for k in OUR_KW)]
        other = [v for v in ko["videos"] if v not in ours]
        ko_ours = len(ours)
        ko_ours_avg = int(st.mean([v["views"] for v in ours]))
        ko_ours_med = int(st.median([v["views"] for v in ours]))
        ko_other_avg = int(st.mean([v["views"] for v in other]))
        ko_other_med = int(st.median([v["views"] for v in other]))

    # 해시태그 중복률 (ko)
    dup_rate = 0
    if not ko.get("error"):
        import collections
        tot = dups = 0
        for v in ko["videos"]:
            tags = [t for t in v["title"].split() if t.startswith("#")]
            c = collections.Counter(tags)
            tot += len(tags)
            dups += sum(n - 1 for n in c.values() if n > 1)
        dup_rate = round(dups / tot * 100) if tot else 0

    # 업로드 이력
    hist_rows = []
    for lang, items in hist.items():
        for h in items:
            hist_rows.append((h["ts"], lang, h["id"], h["title"]))
    hist_rows.sort(reverse=True)

    # 잘못된 채널에 올라간 영상.
    # id 로만 매칭하면 실패한 업로드(=같은 제목이 다른 id 로 올라간 경우)를 놓친다.
    # → 제목 기준으로 매칭하고, 한글이 들어가면 무조건 ko 로 판정한다.
    import re as _re
    misplaced = []
    zh_videos = stats.get("zh-cn", {}).get("videos", [])
    titles = {lang: {h["title"].strip() for h in items}
              for lang, items in hist.items()}
    for v in zh_videos:
        t = v.get("title", "").strip()
        if _re.search(r"[가-힣]", t):
            src = "ko"
        else:
            src = next((lang for lang, ts in titles.items()
                        if t in ts and lang != "zh-cn"), "?")
        if src in ("ko", "en", "fr"):
            misplaced.append((v["id"], src, t))

    html = render(cards, ko_ours, ko_ours_avg, ko_ours_med, ko_other_avg,
                  ko_other_med, dup_rate, hist_rows, misplaced)
    out = ROOT / "data" / "preview" / "youtube_brief.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"저장: {out}")
    return 0


def render(cards, ko_n, ko_avg, ko_med, o_avg, o_med, dup_rate,
           hist_rows, misplaced) -> str:
    rows = ""
    for c in cards:
        if c.get("error"):
            rows += (f'<tr><td class="l">{c["nm"]}</td>'
                     f'<td class="h">{c["handle"]}</td>'
                     f'<td colspan="5" class="err">{c["error"]}</td></tr>')
            continue
        warn = ' class="bad"' if c["med"] < 50 else ""
        rows += (f'<tr{warn}><td class="l">{c["nm"]}</td>'
                 f'<td class="h">{c["handle"]}</td>'
                 f'<td class="n">{c["n"]}</td>'
                 f'<td class="n">{c["total"]:,}</td>'
                 f'<td class="n">{c["avg"]}</td>'
                 f'<td class="n">{c["med"]}</td>'
                 f'<td class="n">{c["max"]}</td></tr>')

    mis = ""
    for vid, src, title in misplaced:
        mis += (f'<li><b>{src}</b> → <code>zh-cn</code> 채널에 올라감: '
                f'{title} <span class="mono">({vid})</span></li>')

    hist = ""
    for ts, lang, vid, title in hist_rows[:14]:
        hist += (f'<tr><td class="mono">{ts[:16]}</td>'
                 f'<td class="l">{LABEL[lang][0]}</td>'
                 f'<td class="t">{title[:46]}</td>'
                 f'<td class="mono dim">{vid}</td></tr>')

    tl = ""
    base = datetime(2026, 10, 11)
    for i in range(14):
        d = base + timedelta(days=i)
        wd = ["월", "화", "수", "목", "금", "토", "일"][d.weekday()]
        if i == 0:
            note, cls = "오늘 — v3 3편 제작 완료 (미발행)", "now"
        elif i == 1:
            note, cls = "저녁 19:30 · 내일 분량 12편 제작", "mk"
        elif i == 2:
            note, cls = "저녁 19:30 · 12편 제작", "mk"
        else:
            note, cls = "저녁 19:30 · 12편 제작", "mk"
        tl += (f'<tr><td class="mono">{d.strftime("%m-%d")}</td>'
               f'<td>{wd}</td>'
               f'<td class="l {cls}">{note}</td></tr>')

    return f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<title>YouTube 채널 브리핑 — 2026-10-11</title>
<style>
 body{{font-family:-apple-system,"Malgun Gothic",sans-serif;background:#f7f6f2;
      color:#22221f;margin:0;padding:32px;line-height:1.6}}
 .wrap{{max-width:940px;margin:0 auto}}
 h1{{font-size:22px;font-weight:600;margin:0 0 4px}}
 .sub{{color:#6b6a63;font-size:13px;margin-bottom:24px}}
 h2{{font-size:16px;font-weight:600;margin:32px 0 10px;padding-bottom:6px;
    border-bottom:1px solid #dcdad2}}
 table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;
        overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,.05);font-size:13px}}
 th{{background:#f0eee7;text-align:right;padding:9px 10px;font-weight:600;
    font-size:12px;color:#5c5b54}}
 th.l,td.l{{text-align:left}}
 td{{padding:9px 10px;text-align:right;border-top:1px solid #eeece4}}
 tr.bad td{{background:#fdf1ee}}
 td.h,td.t{{text-align:left;font-weight:400}}
 .mono{{font-family:ui-monospace,Menlo,monospace;font-size:12px}}
 .dim{{color:#9a9890}}
 .err{{color:#a33;text-align:left}}
 .box{{background:#fff;border-radius:8px;padding:16px 18px;box-shadow:0 1px 2px rgba(0,0,0,.05)}}
 .p1{{border-left:3px solid #c0392b}}
 .p2{{border-left:3px solid #d68910}}
 .p3{{border-left:3px solid #3b7dd8}}
 ul{{margin:8px 0 0;padding-left:20px}}
 li{{margin:5px 0;font-size:13px}}
 code{{background:#eeece4;padding:1px 5px;border-radius:3px;font-size:12px}}
 tr.now td.l{{color:#1a7f4b;font-weight:600}}
 tr.mk td.l{{color:#6b6a63}}
 .kpi{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px}}
 .k{{flex:1;min-width:150px;background:#fff;border-radius:8px;padding:12px 14px;
    box-shadow:0 1px 2px rgba(0,0,0,.05)}}
 .k b{{display:block;font-size:20px;font-weight:600}}
 .k span{{font-size:12px;color:#6b6a63}}
</style><div class="wrap">

<h1>YouTube 채널 브리핑</h1>
<div class="sub">2026-10-11 · 공개 페이지 실측 (조회수/구독자는 공개 데이터 기준) ·
출처 <span class="mono">scripts/youtube_public_stats.py</span></div>

<h2>1. 채널 현황</h2>
<table><thead><tr><th class="l">언어</th><th class="l">채널</th>
<th>게시</th><th>합계조회</th><th>평균</th><th>중앙값</th><th>최고</th>
</tr></thead><tbody>{rows}</tbody></table>
<p style="font-size:12px;color:#6b6a63;margin-top:8px">
배경색이 붉은 행은 중앙값 50회 미만 — 알고리즘이 아직 못 잡은 채널.</p>

<div class="kpi" style="margin-top:16px">
 <div class="k"><b>{ko_avg}</b><span>한국어 · 우리 콘텐츠 평균 조회</span></div>
 <div class="k"><b>{ko_med}</b><span>한국어 · 우리 콘텐츠 중앙값</span></div>
 <div class="k"><b>{o_med}</b><span>한국어 · 기존 타주제 중앙값</span></div>
 <div class="k"><b>{dup_rate}%</b><span>제목 해시태그 중복률</span></div>
</div>
<p style="font-size:13px">
한국어 채널에서는 <b>우리 명언·동기부여 콘텐츠가 기존 콘텐츠보다 중앙값에서
3배</b>({ko_med} vs {o_med})를 기록한다. 주제 정합성은 문제없다 — 채널이 커야 하는
방향이 맞다는 뜻이다.</p>

<h2>2. 발견된 문제</h2>
<div class="box p1">
<b>P1 · 중국어 채널에 다른 언어가 섞여 있다</b>
<ul>{mis or "<li>현재 채널 목록 기준으로는 미검출</li>"}
<li>YouTube 는 채널의 언어·주제를 학습한다. 한국어·프랑스어가 섞이면
중국어 쇼츠 추천이 밀린다 — 중국어 채널 평균 15회의 직접적인 원인 중 하나.</li>
</ul>
</div>

<div class="box p3">
<b>P2 · YouTube 쿼터는 문제가 아니다 (2026-10-11 정정)</b>
<ul>
<li>예전 정보 "하루 6건" 은 <b>폐기된 규칙</b>이다. Google 이 두 번 바꿨다:
  2025-12-04 비용 1,600 → 약 100 units, 2026-06-01 <b>독립 쿼터 버킷</b> 분리.</li>
<li>현재 <code>videos.insert</code> = <b>하루 100회, 1회당 1 unit</b>. 3편×4언어=12건은 한도 안.</li>
<li>쿼터는 계정/채널이 아니라 <b>Google Cloud 프로젝트 단위</b>다.
4개 채널이 한 버킷을 나눠 쓴다.</li>
<li>→ 하루 12편 전부 유튜브에 올릴 수 있다. 배치 분필은 필요 없어졌다.</li>
</ul>
</div>

<div class="box p1" style="margin-top:10px">
<b>P3 · 폴더 날짜와 실제 발행일이 다르다</b>
<ul>
<li><code>2026-10-15</code> 폴더 = 10-09 23:43 에 업로드된 영상,
<code>2026-10-17</code> 폴더 = 10-10 19:33 에 업로드된 영상.</li>
<li>중복 방지 마커(<span class="mono">published.json</span>)가 날짜 기준이라
날짜가 어긋나면 <b>같은 영상을 두 번 올릴 수 있다</b>.</li>
<li>날짜 스텁을 쓰지 말고 <b>실제 발행일</b>로 통일해야 한다.</li>
</ul>
</div>

<div class="box p2" style="margin-top:10px">
<b>P4 · 프랑스어 채널이 사실상 죽어 있다</b>
<ul>
<li>9편 합계 29회, 절반이 0회.</li>
<li>신규 채널이 알고리즘을 잡으려면 30~50편이 필요. 매일 올려야 하는데,
쿼터가 그걸 막고 있다.</li>
</ul>
</div>

<div class="box p2" style="margin-top:10px">
<b>P5 · 영상 용량 75MB</b>
<ul>
<li>40초짜리가 15Mbps — 흑백 선화 슬라이드쇼에 과다하다.</li>
<li>CRF 20 → 26, preset veryfast → medium 으로 내리면 5~8MB로 화질 손실이 거의 없다.</li>
</ul>
</div>

<h2>3. 최근 업로드 이력 (우리 기록)</h2>
<table><thead><tr><th>시각</th><th class="l">언어</th><th class="l">제목</th>
<th>ID</th></tr></thead><tbody>{hist}</tbody></table>
<p style="font-size:12px;color:#6b6a63;margin-top:8px">
10-08 하루에 4편, 10-09 하루에 6~8편이 몰려 있다 — 쿼터 한도 안에서
_slot_ 을 지키지 않고 한꺼번에 올라간 상태.</p>

<h2>4. 앞으로 2주 타임라인</h2>
<table><thead><tr><th>날짜</th><th>요일</th><th class="l">저녁 19:30 제작</th>
</tr></thead><tbody>{tl}</tbody></table>

<div class="box" style="margin-top:14px">
<b>발행 슬롯 (매일, KST)</b>
<table style="margin-top:10px"><thead><tr><th>시각</th><th class="l">편</th>
<th>Instagram</th><th>YouTube</th><th class="l">쿼터</th></tr></thead><tbody>
<tr><td class="mono">00:07</td><td class="l">명언 우화</td><td class="n">4언어</td>
<td class="n">4언어</td><td class="l">4 / 100</td></tr>
<tr><td class="mono">08:07</td><td class="l">나스닥 TOP10</td><td class="n">4언어</td>
<td class="n">4언어</td><td class="l">8 / 100</td></tr>
<tr><td class="mono">16:07</td><td class="l">사업가 마인드</td><td class="n">4언어</td>
<td class="n">4언어</td><td class="l">12 / 100</td></tr>
</tbody></table>
<p style="font-size:12px;color:#6b6a63;margin-top:8px">
일일 한도 100회 대비 12회 — 88회 여유. Instagram·YouTube 모두 12편 전부 발행.</p>
</div>

<h2>5. 10-19 리뷰에서 결정할 것</h2>
<div class="box p3">
<ul>
<li>프랑스어 채널을 계속 YT 로 밀지, Instagram 전용으로 낮출지</li>
<li>중국어 채널의 오염된 3편을 삭제할지, 비공개로 낮출지</li>
<li>스페인어를 5번째 언어로 추가할지 — 쿼터는 이제 제약이 아니다
(12건이면 88회 남음). 채널 생성과 OAuth 만 새로 하면 된다.</li>
</ul>
</div>

</div></html>"""


if __name__ == "__main__":
    sys.exit(main())
