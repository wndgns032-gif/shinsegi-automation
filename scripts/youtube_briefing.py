"""YouTube 채널 실제 현황 브리핑 (2026-10-11 신설).

왜 필요한가: 지금까지는 "업로드했는가" 만 봤고 **얼마나 됐는가** 를 본 적이 없다.
채널마다 조회수·구독자·게시물 상태를 실제 API 로 가져와 한눈에 정리한다.

사용: python scripts/youtube_briefing.py [--days 14]
주의: videos.list 를 쓰므로 일일 쿼터를 아주 조금 먹는다(1 unit/호출).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LANGS = ["ko", "en", "zh-cn", "fr"]
ENV_TOKEN = {
    "ko": "YOUTUBE_KO_REFRESH_TOKEN",
    "en": "YOUTUBE_EN_REFRESH_TOKEN",
    "zh-cn": "YOUTUBE_ZH_CN_REFRESH_TOKEN",
    "fr": "YOUTUBE_FR_REFRESH_TOKEN",
}
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def client_for(lang: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    tok = os.environ.get(ENV_TOKEN[lang], "").strip()
    if not tok:
        return None, "토큰 없음"
    creds = Credentials(
        token=None, refresh_token=tok,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("YOUTUBE_CLIENT_ID", ""),
        client_secret=os.environ.get("YOUTUBE_CLIENT_SECRET", ""),
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False), None


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch(lang: str, days: int) -> dict:
    yt, err = client_for(lang)
    if err:
        return {"lang": lang, "error": err}

    try:
        ch = yt.channels().list(part="snippet,statistics,contentDetails",
                                mine=True).execute()
    except Exception as e:  # noqa: BLE001
        return {"lang": lang, "error": f"인증 실패: {type(e).__name__}: {str(e)[:120]}"}
    if not ch.get("items"):
        return {"lang": lang, "error": "채널 없음"}

    c = ch["items"][0]
    st = c.get("statistics", {})
    uploads = (c.get("contentDetails", {})
               .get("relatedPlaylists", {}).get("uploads"))

    vids, page = [], None
    while True:
        r = yt.playlistItems().list(playlistId=uploads, maxResults=50,
                                   part="contentDetails", pageToken=page).execute()
        vids += [x["contentDetails"]["videoId"] for x in r.get("items", [])]
        page = r.get("nextPageToken")
        if not page or len(vids) > 300:
            break

    details = []
    for i in range(0, len(vids), 50):
        chunk = vids[i:i + 50]
        r = yt.videos().list(part="snippet,statistics,contentDetails,status",
                             id=",".join(chunk)).execute()
        details += r.get("items", [])

    rows = []
    for v in details:
        sn, stt = v.get("snippet", {}), v.get("statistics", {})
        cd, status = v.get("contentDetails", {}), v.get("status", {})
        pub = sn.get("publishedAt", "")
        rows.append({
            "id": v["id"],
            "title": sn.get("title", ""),
            "published": pub,
            "views": int(stt.get("viewCount", 0) or 0),
            "likes": int(stt.get("likeCount", 0) or 0),
            "comments": int(stt.get("commentCount", 0) or 0),
            "dur": cd.get("duration", ""),
            "privacy": status.get("privacyStatus", "?"),
            "madeForKids": status.get("madeForKids"),
            "license": status.get("license"),
            "publishedAt": pub,
        })
    rows.sort(key=lambda r: r["published"])

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = [r for r in rows
              if r["published"] and parse_iso(r["published"]) >= cutoff]

    return {
        "lang": lang,
        "channel_id": c["id"],
        "title": c.get("snippet", {}).get("title", ""),
        "handle": c.get("snippet", {}).get("customUrl", ""),
        "subs": int(st.get("subscriberCount", 0) or 0),
        "views_total": int(st.get("viewCount", 0) or 0),
        "videos_total": int(st.get("videoCount", 0) or 0),
        "created": c.get("snippet", {}).get("publishedAt", ""),
        "rows": rows,
        "recent": recent,
        "error": None,
    }


def duration_sec(iso: str) -> float:
    # PT#M#S / PT#S
    try:
        t = iso.replace("PT", "").replace("S", "")
        if "M" in t:
            m, s = t.split("M")
            return int(m) * 60 + float(s)
        return float(t)
    except Exception:  # noqa: BLE001
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()
    load_env()

    out = []
    for lang in LANGS:
        print(f"[{lang}] 조회 중...", flush=True)
        out.append(fetch(lang, a.days))

    report = ROOT / "data" / "youtube_briefing.json"
    report.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                      encoding="utf-8")

    print("\n" + "=" * 74)
    print(f"{'언어':<6}{'채널':<24}{'구독':>7}{'총조회':>9}{'영상':>6}{'최근':>5}{'최근조회':>10}")
    print("=" * 74)
    for r in out:
        if r["error"]:
            print(f"{r['lang']:<6}❌ {r['error']}")
            continue
        rv = sum(x["views"] for x in r["recent"])
        print(f"{r['lang']:<6}{(r['title'] or '')[:22]:<24}{r['subs']:>7,}"
              f"{r['views_total']:>9,}{r['videos_total']:>6}{len(r['recent']):>5}{rv:>10,}")

    print("\n" + "=" * 74)
    print("최근 영상 상세")
    print("=" * 74)
    for r in out:
        if r["error"]:
            continue
        print(f"\n■ {r['lang']} — {r['title']} ({r['handle']})  구독 {r['subs']:,}")
        for x in r["recent"]:
            d = x["published"][:16].replace("T", " ")
            flag = "" if x["privacy"] == "public" else f"  [{x['privacy']}]"
            print(f"   {d}  {duration_sec(x['dur']):>5.0f}s  "
                  f"{x['views']:>6,}회  ♥{x['likes']:>5}  💬{x['comments']:>3}  "
                  f"{x['title'][:38]}{flag}")
    print(f"\n저장: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
