"""YouTube Shorts 업로드 — Data API v3.

왜 이 방식인가:
  · 완전 무료. 일 기본 쿼터 10,000 units, videos.insert 1건 = 1,600 units
    → 하루 **6건**까지 무료 한도 안. (기본값은 언어 4개 × 1회 = 4건 = 6,400 units)
  · OAuth2 refresh token 방식이라 최초 1회만 사람이 브라우저에서 허용하면,
    이후에는 스케줄러가 무인으로 계속 올린다.
  · 업로드된 영상이 세로(9:16) + 60초 이하면 YouTube가 자동으로 Shorts로 분류한다.
    제목 끝에 #Shorts 를 붙여 분류를 확실히 한다.

필요한 .env 값:
  YOUTUBE_CLIENT_ID=...          (GCP OAuth 클라이언트 — 언어 공용)
  YOUTUBE_CLIENT_SECRET=...
  YOUTUBE_EN_REFRESH_TOKEN=...   (언어별 · scripts/youtube_auth.py 가 자동 기록)
  YOUTUBE_KO_REFRESH_TOKEN=...
  YOUTUBE_ZH_CN_REFRESH_TOKEN=...
  YOUTUBE_FR_REFRESH_TOKEN=...

선택:
  YOUTUBE_PRIVACY=public|unlisted|private   (기본 public)
  YOUTUBE_CATEGORY=27                       (27=교육)
  YOUTUBE_SHORTS=on|off                     (기본 on — 자격증명 있을 때만 동작)
  YOUTUBE_SHORTS_CYCLES=pm                  (기본 13:00 회차만 — 쿼터 보호)
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .base import Publisher

ROOT = Path(__file__).resolve().parents[2]

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
TITLE_MAX = 100          # YouTube 제목 상한
TAG_MAX = 15
CATEGORY_DEFAULT = "27"  # Education
# 업로드 이력 (중복 방지 + 쿼터 절약). search.list 는 100units/건이라 쓰지 않는다.
HISTORY = Path(__file__).resolve().parents[2] / "data" / "youtube_uploads.json"

_LANG_TAG = {"en": "en", "ko": "ko", "zh-cn": "zh-CN", "fr": "fr"}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\r", " ").replace("\n", " ")).strip()


def _title(caption: str) -> str:
    """캡션 첫 문장을 제목으로. 100자 제한 + #Shorts 보장."""
    head = _clean(caption.split("\n")[0])
    for sep in (". ", "! ", "? ", "。", "！", "？", ".", "!"):
        if sep in head[:70]:
            cut = head.split(sep)[0]
            if len(cut) >= 12:
                head = cut + sep.strip()
                break
    if len(head) > TITLE_MAX - 8:
        head = head[: TITLE_MAX - 9].rstrip() + "…"
    if "#Shorts" not in head and "#shorts" not in head:
        head = f"{head} #Shorts"
    return head[:TITLE_MAX]


def _tags(caption: str, lang: str) -> list[str]:
    found = re.findall(r"#([^\s#]{1,30})", caption or "")
    extra = {"en": ["wisdom", "quote", "shorts", "motivation"],
             "ko": ["명언", "오늘의문장", "배움", "쇼츠"],
             "zh-cn": ["名言", "今日一句", "感悟", "短视频"],
             "fr": ["citation", "sagesse", "lecondevie", "shorts"]}.get(lang, [])
    out, seen = [], set()
    for t in list(found) + extra:
        k = t.lower()
        if k in seen or not t:
            continue
        seen.add(k)
        out.append(t)
        if len(out) >= TAG_MAX:
            break
    return out


# ── 채널 매핑 설정 (config/youtube_channels.yaml) ────────────────────
# 채널을 개명/재배치하면 기존 토큰이 다른 채널을 가리키게 된다.
# 그 상태로 업로드하면 다른 언어 채널에 영상이 올라가므로 config 로 차단한다.
_CHANNELS_YAML = ROOT / "config" / "youtube_channels.yaml"
_channels_cfg: dict | None = None


def _channels_config() -> dict:
    global _channels_cfg
    if _channels_cfg is not None:
        return _channels_cfg
    _channels_cfg = {}
    if _CHANNELS_YAML.exists():
        try:
            import yaml
            _channels_cfg = yaml.safe_load(
                _CHANNELS_YAML.read_text(encoding="utf-8")) or {}
        except Exception as e:  # noqa: BLE001
            print(f"  [youtube] youtube_channels.yaml 파싱 실패 — 차단 판정 생략: {e}")
            _channels_cfg = {}
    return _channels_cfg


def _is_blocked(lang: str) -> bool:
    """채널 재배치로 업로드가 위험한 언어인지 판정."""
    return lang in ((_channels_config().get("blocked_languages")) or [])


class YouTubePublisher(Publisher):
    name = "youtube"
    env_suffixes = ["REFRESH_TOKEN"]
    extra_env = ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"]

    # ── 인증 ────────────────────────────────────────────────────────────
    def _client(self, refresh_token: str):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=TOKEN_URI,
            client_id=os.environ["YOUTUBE_CLIENT_ID"],
            client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
            scopes=SCOPES,
        )
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    # ── 중복 방지 ───────────────────────────────────────────────────────
    @staticmethod
    def _already(lang: str, title: str) -> bool:
        try:
            hist = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else {}
        except Exception:  # noqa: BLE001
            hist = {}
        return title in {h.get("title") for h in hist.get(lang, [])}

    @staticmethod
    def _record(lang: str, title: str, video_id: str) -> None:
        try:
            hist = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else {}
        except Exception:  # noqa: BLE001
            hist = {}
        rows = [h for h in hist.get(lang, []) if h.get("title") != title]
        rows.append({"title": title, "id": video_id, "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
        hist[lang] = rows[-60:]
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 업로드 ──────────────────────────────────────────────────────────
    def publish_reel(self, lang: str, caption: str, video_path: Path, creds: dict) -> dict:
        tag = f"{self.name}_shorts"

        # ⚠️ 위험 차단: 채널이 개명/재배치된 상태에서 옛 토큰으로 업로드하면
        #    다른 언어 채널에 영상이 올라간다.
        #    예: 2026-10-07 한국어 채널을 중국어로 바꾸면서, ko 토큰이
        #        @shinsegi-zh 를 가리키게 됨 → 한국어 영상이 중국어 채널에 게시.
        # config/youtube_channels.yaml 의 blocked_languages 로 명시 차단한다.
        if _is_blocked(lang):
            print(f"  [youtube:{lang}] ⛔ 업로드 차단 — config blocked_languages "
                  f"(채널 재배치 후 재인증 필요)")
            return {"platform": tag, "lang": lang, "status": "blocked",
                    "detail": "채널 재배치로 토큰이 다른 채널을 가리킴 — 재인증 필요"}
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as e:  # noqa: BLE001
            return {"platform": tag, "lang": lang, "status": "error",
                    "detail": f"google-api-python-client 미설치: {e}"}

        title = _title(caption)
        # 토큰 자체가 없으면 조용히 넘어간다 (클라우드에서 secret 이 아직 없을 수 있음).
        # None 으로 client() 를 부르면 AttributeError 가 나므로 여기서 막는다.
        if not (creds.get("REFRESH_TOKEN") or "").strip():
            print(f"  [youtube:{lang}] 토큰 미설정 — 건너뜀 "
                  f"(인증 필요: scripts\\youtube_auth.cmd {lang})")
            return {"platform": tag, "lang": lang, "status": "skipped",
                    "detail": "refresh token 미설정 — 채널 인증 필요"}
        if self._already(lang, title):
            print(f"  [youtube:{lang}] 동일 제목 업로드 이력 있음 — 중복 방지로 건너뜀")
            return {"platform": tag, "lang": lang, "status": "skipped",
                    "detail": "동일 제목 업로드 이력 존재"}

        body = {
            "snippet": {
                "title": title,
                "description": _clean(caption),
                "tags": _tags(caption, lang),
                "categoryId": os.getenv("YOUTUBE_CATEGORY", CATEGORY_DEFAULT),
                "defaultLanguage": _LANG_TAG.get(lang, "en"),
                "defaultAudioLanguage": _LANG_TAG.get(lang, "en"),
            },
            "status": {
                "privacyStatus": os.getenv("YOUTUBE_PRIVACY", "public"),
                "selfDeclaredMadeForKids": False,
                "embeddable": True,
            },
        }

        last_err: Exception = RuntimeError("업로드 실패")
        for attempt in (1, 2, 3):
            try:
                yt = self._client(creds["REFRESH_TOKEN"])
                media = MediaFileUpload(str(video_path), mimetype="video/mp4",
                                        resumable=True, chunksize=1024 * 1024)
                req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
                resp, last = None, None
                while resp is None:
                    last, resp = req.next_chunk()      # (status, response)
                    if last and last.progress():
                        print(f"  [youtube:{lang}] 업로드 {int(last.progress() * 100)}%")
                vid = (resp or {}).get("id")
                if not vid:
                    raise RuntimeError(f"응답에 id 없음: {str(resp)[:200]}")
                self._record(lang, title, vid)
                return {"platform": tag, "lang": lang, "status": "published", "id": vid}
            except Exception as e:  # noqa: BLE001 - 3회 재시도 후 실패 처리
                last_err = e
                msg = str(e)
                print(f"  [youtube:{lang}] 시도 {attempt}/3 실패: {msg[:200]}")
                # GCP 앱이 '테스트' 상태면 refresh token 이 7일 뒤 만료된다(invalid_grant).
                if "invalid_grant" in msg.lower():
                    print(f"  [youtube:{lang}] ⇒ 인증 만료. "
                          f"python scripts/youtube_auth.py {lang} 한 번만 다시 실행하세요.")
                    break
                time.sleep(5 * attempt)
        return {"platform": tag, "lang": lang, "status": "error", "detail": str(last_err)[:500]}

    # 카드뉴스는 YouTube 에 올리지 않는다 (영상 전용 플랫폼).
    def _publish(self, lang, content, card_paths, creds) -> dict:
        return {"platform": self.name, "lang": lang, "status": "skipped",
                "detail": "youtube 는 영상 전용 — 카드 발행 대상 아님"}
