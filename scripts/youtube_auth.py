"""YouTube 업로드 권한 1회 인증 → refresh token 을 .env 에 기록.

사용:
  python scripts/youtube_auth.py ko           # 한국어 채널 인증 (브라우저 열림)
  python scripts/youtube_auth.py en ko zh-cn fr
  python scripts/youtube_auth.py status       # 어떤 언어가 연결됐는지 확인

준비물: GCP 에서 만든 OAuth 클라이언트(데스크톱 앱) JSON.
  data/youtube_client.json 에 넣어두면 자동으로 읽는다.
  (없으면 .env 의 YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET 사용)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

ENV_PATH = BASE / ".env"
CLIENT_JSON = BASE / "data" / "youtube_client.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]
LANGS = ["en", "ko", "zh-cn", "fr"]
ENV_LANG = {"en": "EN", "ko": "KO", "zh-cn": "ZH_CN", "fr": "FR"}


def _env_key(lang: str) -> str:
    return f"YOUTUBE_{ENV_LANG[lang]}_REFRESH_TOKEN"


def load_client() -> dict | None:
    """(client_id, client_secret) — data/youtube_client.json 우선, 없으면 .env."""
    if CLIENT_JSON.exists():
        try:
            d = json.loads(CLIENT_JSON.read_text(encoding="utf-8"))
            cfg = d.get("installed") or d.get("web") or {}
            cid, csec = cfg.get("client_id"), cfg.get("client_secret")
            if cid and csec:
                return {"client_id": cid, "client_secret": csec}
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {CLIENT_JSON.name} 파싱 실패: {e}")
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH, override=True)
    cid, csec = os.getenv("YOUTUBE_CLIENT_ID"), os.getenv("YOUTUBE_CLIENT_SECRET")
    return {"client_id": cid, "client_secret": csec} if cid and csec else None


def _set_env(key: str, value: str) -> None:
    """기존 키가 있으면 값만 교체, 없으면 파일 끝에 추가."""
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    pat = re.compile(rf"^{re.escape(key)}\s*=.*$", re.M)
    if pat.search(text):
        text = pat.sub(f"{key}={value}", text)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"{key}={value}\n"
    ENV_PATH.write_text(text, encoding="utf-8")


def auth(lang: str, client: dict) -> bool:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    cfg = {"installed": {
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }}
    print(f"\n=== {lang} 채널 인증 ===")
    print("브라우저가 열립니다. **업로드할 YouTube 계정으로 로그인**하고 허용을 누르세요.")
    flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent select_account",
                                  access_type="offline", open_browser=True)
    if not creds.refresh_token:
        print("[fail] refresh token 을 받지 못했습니다. 'consent' 화면에서 허용을 눌렀는지 확인.")
        return False

    key = _env_key(lang)

    try:
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        ch = yt.channels().list(part="snippet", mine=True).execute()
        items = ch.get("items") or []
        if not items:
            # 채널 없는 신분(개인 계정 등)의 토큰은 업로드 시 youtubeSignupRequired 401
            print("[fail] 이 토큰에는 YouTube 채널이 없습니다!")
            print("       shinsegimedia@gmail.com 으로 로그인 후 언어별 브랜드 채널을")
            print("       계정 선택 화면에서 골라야 합니다. 토큰을 저장하지 않습니다.")
            return False
        name = items[0]["snippet"]["title"]
        handle = items[0]["snippet"].get("customUrl", "")
        # 언어별 예상 핸들(알려진 것만 강제 검증) — 채널명이 전부 'shinsegi'라
        # 구분은 핸들로만 가능. 틀린 채널에 묶이면 저장 자체를 거부한다.
        EXPECTED = {"ko": "@shinsegi-kr", "fr": "@shinsegi-fr"}
        if lang in EXPECTED and handle != EXPECTED[lang]:
            print(f"[fail] {lang} 토큰이 {handle} 채널에 묶였습니다 (기대: {EXPECTED[lang]})")
            print("       계정 선택 화면에서 올바른 채널을 골라야 합니다. 토큰을 저장하지 않습니다.")
            return False
        # 검증 통과 후에만 저장 — 실패한 토큰이 .env 에 남는 사고 방지
        _set_env("YOUTUBE_CLIENT_ID", client["client_id"])
        _set_env("YOUTUBE_CLIENT_SECRET", client["client_secret"])
        _set_env(key, creds.refresh_token)
        print(f"[ok] {lang} 연결 완료 — 채널: {name} ({handle})")
        print(f"     {key} 저장됨")
    except Exception as e:  # noqa: BLE001
        print(f"[fail] 채널 조회 실패 (토큰 미저장): {str(e)[:150]}")
        return False
    return True


def status() -> None:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH, override=True)
    client = load_client()
    print("OAuth 클라이언트:", "준비됨" if client else "없음 (data/youtube_client.json 필요)")
    for lang in LANGS:
        tok = os.getenv(_env_key(lang))
        print(f"  {lang:6s}: {'연결됨' if tok else '미연결'}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args or args[0] == "status":
        status()
        print("\n사용법: python scripts/youtube_auth.py ko")
        return

    client = load_client()
    if not client:
        print("OAuth 클라이언트 정보가 없습니다.")
        print("1) https://console.cloud.google.com → 프로젝트 만들기")
        print("2) API 및 서비스 > 라이브러리 > 'YouTube Data API v3' 사용 설정")
        print("3) API 및 서비스 > 사용자 인증 정보 > OAuth 클라이언트 ID 만들기 (데스크톱 앱)")
        print("4) JSON 다운로드 → sns-automation/data/youtube_client.json 로 저장")
        print("   (또는 .env 에 YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET 입력)")
        sys.exit(1)

    ok = 0
    for lang in (a.lower() for a in args):
        if lang not in LANGS:
            print(f"[skip] 알 수 없는 언어: {lang} (en/ko/zh-cn/fr)")
            continue
        try:
            ok += 1 if auth(lang, client) else 0
        except Exception as e:  # noqa: BLE001
            print(f"[fail] {lang}: {type(e).__name__}: {str(e)[:300]}")
    print(f"\n완료: {ok}/{len(args)} 채널 인증")
    print("다음: python -m src.main fable-publish --date <YYYY-MM-DD>  (미발행분 YT 보완 업로드)")


if __name__ == "__main__":
    main()
