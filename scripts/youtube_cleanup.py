"""YouTube 채널 위생 점검 — 빈 영상 / 미처리 업로드 찾아서 정리.

왜 필요한가 (2026-10-09 실측 사고)
─────────────────────────────────
videos().insert 는 렌더 실패(0바이트 mp4)에도 HTTP 200 + id 를 돌려준다.
YouTube 는 0바이트 영상을 '실패'로 간주하지 않기 때문에
채널에 `uploaded / P0D` 상태의 빈 영상이 남고,
같은 제목의 정상 영상이 뒤에 올라가 **중복**이 생긴다.

이 스크립트는 4개 채널을 훑어:
  1. duration 이 P0D / PT0S 인 영상
  2. uploadStatus 가 processed 가 아닌 영상
을 찾아 보고한다. 삭제하려면 force-ssl 스코프가 필요하다.

사용법
------
python scripts/youtube_cleanup.py            # 진단만
python scripts/youtube_cleanup.py --delete   # 진단 + 삭제 시도

⚠️ --delete 는 force-ssl 스코프가 있어야 동작한다.
   없으면 아래처럼 안내가 나온다:
   scripts\\youtube_auth.cmd<lang> 로 재인증 후 다시 실행.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
load_dotenv(BASE / ".env", override=True)

LANGS = [("ko", "KO"), ("en", "EN"), ("zh-cn", "ZH_CN"), ("fr", "FR")]
SCOPES_READ = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
SCOPES_FULL = SCOPES_READ + ["https://www.googleapis.com/auth/youtube.force-ssl"]


def _has_scope(tok: str, scope: str) -> bool:
    """refresh token 에 해당 스코프가 있는지 토큰 endpoint 로 직접 확인."""
    import requests
    cid = os.getenv("YOUTUBE_CLIENT_ID", "")
    sec = os.getenv("YOUTUBE_CLIENT_SECRET", "")
    try:
        r = requests.post(
            "https://oauth2.googleapis.com/token",
            data={"grant_type": "refresh_token", "refresh_token": tok,
                  "client_id": cid, "client_secret": sec},
            timeout=30,
        )
        if r.status_code != 200:
            return False
        granted = r.json().get("scope", "")
        return scope in granted
    except Exception:  # noqa: BLE001
        return False


def _client(scopes):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(
        token=None,
        refresh_token=os.getenv("YOUTUBE_KO_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("YOUTUBE_CLIENT_ID", ""),
        client_secret=os.getenv("YOUTUBE_CLIENT_SECRET", ""),
        scopes=scopes,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true", help="빈 영상 삭제 시도")
    ap.add_argument("--max", type=int, default=15, help="채널당 조회 개수")
    args = ap.parse_args()

    try:
        import googleapiclient  # noqa: F401
    except ImportError:
        print("google-api-python-client 가 없습니다: pip install google-api-python-client")
        return 1

    found: list[tuple[str, str, str, str, str]] = []
    ok = True

    for lang, key in LANGS:
        tok = os.getenv(f"YOUTUBE_{key}_REFRESH_TOKEN", "").strip()
        if not tok:
            print(f"{lang:6s} 토큰 없음 — 건너뜀")
            continue
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            # force-ssl 이 없는 기존 토큰이면 읽기 전용 스코프로 물러난다.
            # (조회는 되지만 삭제/비공개 전환은 불가 — 아래에서 안내)
            scopes = (SCOPES_FULL
                      if _has_scope(tok, "youtube.force-ssl") else SCOPES_READ)
            creds = Credentials(
                token=None, refresh_token=tok,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=os.getenv("YOUTUBE_CLIENT_ID"),
                client_secret=os.getenv("YOUTUBE_CLIENT_SECRET"),
                scopes=scopes,
            )
            yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
            ch = yt.channels().list(part="snippet,contentDetails", mine=True).execute()["items"][0]
            ul = ch["contentDetails"]["relatedPlaylists"]["uploads"]
            items = yt.playlistItems().list(part="snippet", playlistId=ul,
                                            maxResults=args.max).execute().get("items", [])
            issues = 0
            for it in items:
                vid = it["snippet"]["resourceId"]["videoId"]
                v = yt.videos().list(part="contentDetails,status,snippet", id=vid
                                     ).execute()["items"][0]
                dur = (v.get("contentDetails") or {}).get("duration", "")
                st = (v.get("status") or {}).get("uploadStatus", "")
                if dur in ("P0D", "PT0S", "") or st != "processed":
                    issues += 1
                    title = v["snippet"]["title"][:44]
                    print(f"  ⚠ {lang} {vid} | {dur or '?'} | {st} | {title}")
                    found.append((lang, vid, dur, st, title))
            if issues == 0:
                print(f"{lang:6s} {ch['snippet'].get('customUrl','?'):24s} 이상 없음")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"{lang:6s} 오류: {type(e).__name__}: {str(e)[:90]}")

    if not found:
        print("\n모든 채널 정상 — 빈 영상 없음")
        return 0

    print(f"\n=== 빈/미처리 영상 {len(found)}건 발견 ===")
    if not args.delete:
        print("삭제하려면: python scripts/youtube_cleanup.py --delete")
        print("이력에 동일 제목이 있으면 중복이므로 삭제를 권장합니다.")
        return 0

    print("\n삭제 시도:")
    ko_tok = os.getenv("YOUTUBE_KO_REFRESH_TOKEN", "").strip()
    scopes = (SCOPES_FULL if _has_scope(ko_tok, "youtube.force-ssl") else SCOPES_READ)
    if scopes is SCOPES_READ:
        print("  (force-ssl 스코프 없음 — 조회만 가능, 삭제 불가)")
    for lang, vid, dur, st, title in found:
        try:
            _client(scopes).videos().delete(id=vid).execute()
            print(f"  ✅ 삭제: {vid} ({lang}) {title}")
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            print(f"  ❌ 실패: {vid} ({lang}) — {msg[:110]}")
            if "insufficient" in msg.lower() or "scope" in msg.lower():
                print("     → force-ssl 스코프가 필요합니다.")
                print(f"     → scripts\\youtube_auth.cmd {lang} 로 재인증 후 재시도")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())