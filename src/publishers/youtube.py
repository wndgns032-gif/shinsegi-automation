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

# ⚠️ 2026-10-09 실측 사고: 스코프를 늘리면 기존 refresh token 으로는 죽는다.
#   refresh token 의 스코프는 **발급 시 고정**이라서, 새로 추가한 스코프는
#   재인증 전까지 refresh 단계에서 `invalid_scope` 로 실패한다.
#   → youtube.upload 만 요구한다 (이 스코프는 모든 기존 토큰에 있다).
#   → force-ssl(영상 삭제/비공개 전환)이 필요한 코드는 그때그때
#     "없으면 조용히 넘어간다" 로 처리한다.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
# force-ssl 을 쓰고 싶은 곳에서만 선택적으로 사용:
SCOPES_ADMIN = SCOPES + ["https://www.googleapis.com/auth/youtube.force-ssl"]
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
    def _verify_upload(yt, lang: str, video_id: str, tries: int = 3) -> None:
        """업로드 직후 상태를 확인하고, 실패본이면 삭제한다.

        2026-10-09 실측 사고:
          videos().insert 는 렌더 실패(0바이트 mp4)에도 HTTP 200 + id 를 준다.
          그 결과 채널에 `uploaded / P0D` 상태의 빈 영상이 남았고,
          같은 제목의 정상 영상이 1분 뒤에 별도로 올라가 중복이 생겼다.
          (YouTube 는 0바이트 영상을 '실패'로 간주하지 않는다)

        → 여기서 contentDetails.duration 이 0 이거나 uploadStatus 가 done 이 아니면
          **비공개(private)로 전환**한다. 삭제는 force-ssl 스코프가 필요해
          기존 토큰으로는 불가하므로, 비공개가 안전한 대안이다.
          (그래도 videos.update 도 같은 스코프가 필요해서 실패할 수 있다)
        """
        import time as _t
        for _ in range(tries):
            try:
                v = yt.videos().list(part="contentDetails,status",
                                     id=video_id).execute()["items"][0]
            except Exception:  # noqa: BLE001
                return
            dur = (v.get("contentDetails") or {}).get("duration", "")
            status = (v.get("status") or {}).get("uploadStatus", "")
            if dur in ("P0D", "PT0S", "") or status != "processed":
                # 아직 처리 중일 수 있으므로 한 번 더 확인
                if _ < tries - 1:
                    _t.sleep(8)
                    continue
                print(f"  [youtube:{lang}] ⚠ 빈/미처리 영상 감지 (duration={dur or '?'}, "
                      f"status={status}) — 숨김/삭제 시도")
                #1) 비공개 전환(조회 스코프로는 가능할 수도, 아닐 수도 있다)
                for act, kw in (("private", {"privacyStatus": "private"}),
                                 ("삭제", None)):
                    try:
                        if kw is None:
                            yt.videos().delete(id=video_id).execute()
                        else:
                            yt.videos().update(part="status", id=video_id,
                                               body={"status": kw}).execute()
                        print(f"  [youtube:{lang}] {act} 처리 완료: {video_id}")
                        return
                    except Exception as e:  # noqa: BLE001
                        msg = str(e).lower()
                        if "scope" in msg or "insufficient" in msg:
                            print(f"  [youtube:{lang}] {act} 실패 — force-ssl 스코프 필요")
                            continue
                        print(f"  [youtube:{lang}] {act} 실패: {str(e)[:90]}")
                print(f"  [youtube:{lang}] 수동 정리 필요: "
                      f"scripts\\youtube_cleanup.py --delete")
                return
            print(f"  [youtube:{lang}] 업로드 확인 OK (duration={dur}, status={status})")
            return

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

        # ⚠️ 2026-10-09 실측 사고: 렌더가 실패해 mp4 가 0바이트여도
        #    videos().insert 가 HTTP 200 을 주고 실패로 간주되지 않는다.
        #    → 'uploaded / P0D' 상태의 빈 영상이 채널에 남았다(ko 채널 1건).
        #    업로드 전에 반드시 파일 크기를 검증한다.
        try:
            size = Path(video_path).stat().st_size
        except OSError as e:
            return {"platform": tag, "lang": lang, "status": "error",
                    "detail": f"영상 파일 없음: {e}"}
        if size < 500_000:
            # 500KB 미만은 사실상 빈 파일이다 (정상 쇼츠는 40MB 이상).
            return {"platform": tag, "lang": lang, "status": "error",
                    "detail": f"영상 파일이 너무 작음 ({size}B) — 렌더 실패 또는 빈 파일. "
                              f"업로드하지 않음."}

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

                # ⚠️ 업로드 직후 0초/미처리를 확인한다.
                #    YouTube 는 실패한 업로드도 200 + id 를 돌려주며,
                #    상태가 'uploaded'(처리 대기) 또는 길이가 P0D 인채널에 남는다.
                #    (2026-10-09 ko 채널에 P0D 빈 영상 1건이 그렇게 생겼다)
                self._verify_upload(yt, lang, vid)

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
