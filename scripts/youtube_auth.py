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


# ─────────────────────────────────────────────────────────────
# 채널 매핑 설정 (config/youtube_channels.yaml)
#   채널 재배치 시 코드를 고치지 말고 이 파일만 바꾼다.
# ─────────────────────────────────────────────────────────────
CHANNELS_YAML = BASE / "config" / "youtube_channels.yaml"
_cfg_cache: dict | None = None


def channels_config() -> dict:
    global _cfg_cache
    if _cfg_cache is not None:
        return _cfg_cache
    empty = {"language_to_group": {}, "expected_handles": {}, "channels": {}}
    if not CHANNELS_YAML.exists():
        return empty
    try:
        import yaml
        _cfg_cache = yaml.safe_load(CHANNELS_YAML.read_text(encoding="utf-8")) or empty
    except Exception as e:  # noqa: BLE001
        print(f"[warn] youtube_channels.yaml 파싱 실패: {e}")
        _cfg_cache = empty
    return _cfg_cache


def group_of(lang: str) -> str:
    """언어가 속한 채널 그룹 ('brand' / 'personal')"""
    return (channels_config().get("language_to_group") or {}).get(lang, "")


def expected_handle(lang: str) -> str:
    """언어의 기대 채널 핸들. 미설정이면 빈 문자열(=검증 안 함)."""
    return (channels_config().get("expected_handles") or {}).get(lang, "") or ""


def _is_blocked(lang: str) -> bool:
    """채널 재배치로 업로드가 차단된 언어인지."""
    return lang in ((channels_config().get("blocked_languages")) or [])


def _unblock(lang: str) -> bool:
    """재인증 완료된 언어를 blocked_languages 에서 제거. 실제로 제거했으면 True.

    채널을 개명/재배치하면 옛 토큰이 다른 채널을 가리켜 업로드가 위험해진다.
    blocked_languages 로 막아 두었다가, 재인증이 성공하면 자동으로 해제한다.
    (로이가 config 을 손으로 고치지 않아도 되도록)
    """
    global _cfg_cache
    cfg = channels_config()
    blocked = list(cfg.get("blocked_languages") or [])
    if lang not in blocked:
        return False
    blocked.remove(lang)
    cfg["blocked_languages"] = blocked
    try:
        text = CHANNELS_YAML.read_text(encoding="utf-8")
        out, in_block = [], False
        for line in text.splitlines():
            if line.strip().startswith("blocked_languages:"):
                in_block = True
                out.append(line)
                continue
            if in_block:
                # 목록 항목( "- ko") 은 통째로 건너뛴다
                if re.match(r"^\s*-\s", line):
                    continue
                in_block = False
            out.append(line)
        # 빈 목록으로 재작성
        result = "\n".join(out)
        result = re.sub(r"(blocked_languages:\n)(?:\s*#.*\n)*",
                        lambda m: m.group(1), result, count=1)
        CHANNELS_YAML.write_text(result.rstrip() + "\n", encoding="utf-8")
        _cfg_cache = None
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[warn] blocked_languages 제거 실패: {e}")
        _cfg_cache = None
        return False


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
    grp = group_of(lang)
    exp = expected_handle(lang)
    label = ((channels_config().get("channels") or {}).get(grp) or {}).get("label", grp or "미지정")
    print(f"목표 그룹: {label}")
    print(f"기대 핸들: {exp or '(미설정 — 아무 채널이나 매칭됨)'}")
    if _is_blocked(lang):
        print(f"⚠ 현재 {lang} 는 blocked_languages 에 있습니다(재배치로 토큰이 다른 채널을 가리킴).")
        print(f"  이 언어의 인증을 마치면 자동으로 차단이 해제되도록 하겠습니다.")
    print("브라우저가 열립니다. **업로드할 YouTube 계정으로 로그인**하고 허용을 누르세요.")
    if exp:
        print(f"  계정 선택 화면에서 핸들이 '{exp}' 인 채널을 고르세요.")
    flow = InstalledAppFlow.from_client_config(cfg, SCOPES)

    # 샌드박스/헤드리스 환경에서는 브라우저를 띄울 수 없다.
    # → 인증 URL 을 stdout 에 찍고 로이가 직접 열어 pasting 하도록 안내한다.
    # 주의: 콜백 서버를 **URL 생성 전에** 먼저 띄워야 한다
    #       (OAuth 는 state 에 redirect_uri 를 포함하므로 순서가 중요).
    import webbrowser

    def _free_port() -> int:
        """임의의 로컬 포트. 0 을 주면 OS 가 비어 있는 포트를 배정한다."""
        return 0

    try:
        can_open = webbrowser.get() is not None
    except Exception:  # noqa: BLE001
        can_open = False

    if not can_open or os.getenv("YT_NO_BROWSER") == "1":
        # ── 프록시 무력화 ────────────────────────────────────────────
        # 이 PC 에는 HTTP_PROXY=http://127.0.0.1:6222 가 설정돼 있고,
        # 그 상태면 Google 이 127.0.0.1 로 보내는 **콜백까지 프록시로 빠져나간다.**
        # → 콜백이 절대 돌아오지 않는다. (scripts/diag_localhost.py 로 실측 확인)
        for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
                  "ALL_PROXY", "all_proxy"):
            os.environ.pop(k, None)
        os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
        os.environ["no_proxy"] = "127.0.0.1,localhost,::1"

        # ── Google 공식 구현을 그대로 사용 ──────────────────────────
        # InstalledAppFlow.run_local_server(open_browser=False) 는
        #  1) 콜백 서버를 띄우고
        #  2) authorization_url 을 stdout 에 찍으며
        #  3) handle_request() 로 콜백을 받고 fetch_token() 을 부른다.
        # 우리가 직접 만들면 이 중 하나를 놓쳐서 콜백을 못 받는다.
        # open_browser=False 면 URL 만 출력되므로 로이가 붙여넣을 수 있다.
        # host="localhost" 로 지정해 IPv6(::1) 해석 문제도 함께 해결한다
        # — 이 PC 에선 localhost 가 ::1(IPv6) 이 먼저 나온다.
        creds = flow.run_local_server(
            host="localhost", port=0, prompt="consent select_account",
            access_type="offline", open_browser=False,
            timeout_seconds=int(os.getenv("YT_AUTH_TIMEOUT", "1200")),
            authorization_prompt_message=(
                "\n" + "=" * 74 + "\n"
                "아래 URL 을 브라우저 주소창에 붙여넣으세요:\n"
                + "=" * 74 + "\n{url}\n" + "=" * 74 + "\n"
                "① 로그인할 Google 계정 선택"
                f"\n② '{exp}' 채널 선택" if exp else "② 사용할 채널 선택"
                "\n③ '권한 허용' 클릭"
                "\n④ '액세스 거부' 화면이 뜨는 게 정상입니다 (성공)."
                "\n" + "=" * 74
            ),
        )
    else:
        # 브라우저를 자동 띄울 수 있는 환경 — 그래도 host 를 localhost 로 통일한다
        # (IPv6 우선 해석 문제 회피)
        creds = flow.run_local_server(host="localhost", port=0,
                                      prompt="consent select_account",
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
            print("       로그인한 Google 계정 아래에 YouTube 채널이 있어야 합니다.")
            print("       YouTube 접속 → '채널 만들기'로 먼저 만든 뒤 다시 인증하세요.")
            print("       토큰을 저장하지 않습니다.")
            return False
        name = items[0]["snippet"]["title"]
        handle = items[0]["snippet"].get("customUrl", "")
        # 채널 검증 — config/youtube_channels.yaml 의 expected_handles 를 따른다.
        #   (예전엔 ko/fr 을 하드코딩했으나, 채널 재배치 때마다 코드를 수정해야 했다)
        # 채널명은 전부 'shinsegi' 라 구분은 핸들로만 가능.
        expected = expected_handle(lang)
        if expected and handle != expected:
            grp = group_of(lang)
            print(f"[fail] {lang} 토큰이 {handle} 채널에 묶였습니다 (기대: {expected})")
            print(f"       '{grp}' 그룹 소속이어야 합니다. config/youtube_channels.yaml 확인.")
            print("       계정 선택 화면에서 올바른 채널을 골라야 합니다. 토큰을 저장하지 않습니다.")
            return False
        if not expected:
            grp = group_of(lang)
            print(f"[warn] {lang} 기대 핸들이 미설정이라 채널을 확정 검증하지 못했습니다.")
            print(f"       현재: {name} ({handle}) · 그룹: {grp}")
            print(f"       → config/youtube_channels.yaml 의 expected_handles.{lang} 을 채우면")
            print(f"         앞으로 다른 채널에 실수로 묶이는 것을 막을 수 있습니다.")
        # 검증 통과 후에만 저장 — 실패한 토큰이 .env 에 남는 사고 방지
        _set_env("YOUTUBE_CLIENT_ID", client["client_id"])
        _set_env("YOUTUBE_CLIENT_SECRET", client["client_secret"])
        _set_env(key, creds.refresh_token)
        print(f"[ok] {lang} 연결 완료 — 채널: {name} ({handle})")
        print(f"     {key} 저장됨")
        # 차단이 있었다면 이제 재인증이 끝났으니 해제
        if _unblock(lang):
            print(f"     ⛔→✅ blocked_languages 에서 {lang} 제거됨 (재인증 완료)")
    except Exception as e:  # noqa: BLE001
        print(f"[fail] 채널 조회 실패 (토큰 미저장): {str(e)[:150]}")
        return False
    return True


def status() -> None:
    """현재 언어별 토큰 연결 상태 + 실제 묶인 채널 조회."""
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH, override=True)
    client = load_client()
    print("OAuth 클라이언트:", "준비됨" if client else "없음 (data/youtube_client.json 필요)")

    # 채널 매핑 요약
    print("\n=== 채널 매핑 (config/youtube_channels.yaml) ===")
    cfg = channels_config()
    groups = cfg.get("channels") or {}
    for lang in LANGS:
        grp = group_of(lang)
        label = (groups.get(grp) or {}).get("label", grp or "(미지정)")
        exp = expected_handle(lang)
        print(f"  {lang:6s} → {label:28s} 기대핸들 {exp or '(미설정)'}")

    print("\n=== 토큰 상태 ===")
    if not client:
        return
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        print("  (google-api-python-client 미설치)")
        return

    scopes = ["https://www.googleapis.com/auth/youtube.upload",
              "https://www.googleapis.com/auth/youtube.readonly"]
    for lang in LANGS:
        tok = os.getenv(_env_key(lang))
        if not tok:
            print(f"  {lang:6s}: 미연결")
            continue
        try:
            c = Credentials(token=None, refresh_token=tok,
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=client["client_id"],
                            client_secret=client["client_secret"], scopes=scopes)
            yt = build("youtube", "v3", credentials=c, cache_discovery=False)
            items = yt.channels().list(part="snippet", mine=True).execute().get("items") or []
            if not items:
                print(f"  {lang:6s}: ⚠ 채널 없는 신분 (업로드 시 401)")
                continue
            s = items[0]["snippet"]
            got = s.get("customUrl", "")
            exp = expected_handle(lang)
            mark = "OK " if (not exp or got == exp) else "≠ "
            print(f"  {lang:6s}: {mark} {s['title']} ({got})")
        except Exception as e:  # noqa: BLE001
            print(f"  {lang:6s}: 조회 실패 — {type(e).__name__}: {str(e)[:70]}")


def plan() -> None:
    """재인증 플랜 출력 — 로이에게 '무엇을 무엇에 붙이는지' 확인용.

    채널 재배치(언어 → 계정)를 실제 인증 없이 먼저 검토한다.
    """
    cfg = channels_config()
    groups = cfg.get("channels") or {}
    mapping = cfg.get("language_to_group") or {}
    handles = cfg.get("expected_handles") or {}

    print("=== 인증 플랜 (config/youtube_channels.yaml 기준) ===\n")
    by_group: dict[str, list[str]] = {}
    for lang in LANGS:
        by_group.setdefault(mapping.get(lang, "(미지정)"), []).append(lang)

    for grp, langs in by_group.items():
        meta = groups.get(grp) or {}
        label = meta.get("label", grp)
        email = meta.get("email", "")
        print(f"[{label}]  계정: {email}")
        for lang in langs:
            exp = handles.get(lang) or "(핸들 미설정)"
            print(f"    {lang:6s} → {exp}")
        print()

    print("=== 실행 순서 (인증은 반드시 1개씩) ===")
    print("  python scripts/youtube_auth.py ko")
    print("    → 브라우저에서 [개인 계정] 로그인 → 계정 선택 화면에서")
    print("      한국어 채널 선택 → '권한 허용'")
    print("")
    print("계정 단위 revoke 를 쓰면 그 계정의 모든 토큰이 죽으므로 금지.")
    print("언어 하나만 바꾸려면 그 언어만 재인증한다.")
    print("""
주의: Google 이 직전 선택 신분을 재사용하는 경우가 있다. 그럴 때:
  1) https://myaccount.google.com/connections 접속
  2) 해당 앱(YouTube Data API 클라이언트) 권한 삭제
  3) youtube_auth.py 를 다시 실행 → 계정 선택 화면이 반드시 뜬다""")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args or args[0] == "status":
        status()
        print("\n사용법:")
        print("  python scripts/youtube_auth.py status   # 현재 상태")
        print("  python scripts/youtube_auth.py plan     # 재인증 플랜(계정·채널 매핑 확인)")
        print("  python scripts/youtube_auth.py ko en    # 해당 언어만 인증")
        return
    if args[0] == "plan":
        plan()
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
