"""Instagram — Meta Graph API 캐러셀(텍스트 카드 4~6장) + 캡션.

이미지 호스팅:
  카드 PNG(1.7MB)를 그대로 올리면 Meta 서버가 내려받다 타임아웃
  (error_subcode 2207003) 나는 경우가 있어,
   1) JPEG(q85, ~180KB)로 경량화하고
   2) catbox → uguu → Mastodon 미디어 순으로 폴백 업로드하며
   3) 컨테이너 생성 실패 시 다음 호스트로 넘어간다.
  이전에는 단일 호스트(catbox) 장애 시 그 날 게시 전체가 실패했다.
"""
from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PIL import Image

from .base import Publisher

GRAPH = "https://graph.facebook.com/v23.0"
CATBOX = "https://catbox.moe/user/api.php"
UGUU = "https://uguu.se/upload?expiry=24"
JPEG_QUALITY = 85


def _retry(fn, attempts: int = 3, base_wait: float = 5.0):
    """간헐적 네트워크 타임아웃 대응 — 지수 백오프 재시도."""
    import time as _t

    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < attempts - 1:
                _t.sleep(base_wait * (2 ** i))
    raise last


# ───────────────────────── 이미지 준비 ─────────────────────────
def to_jpeg(path) -> Path:
    """PNG를 IG 업로드용 경량 JPEG로 변환(임시 폴더)."""
    src = Path(path)
    out_dir = Path(tempfile.gettempdir()) / "shinsegi_media"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{src.stem}.jpg"
    Image.open(src).convert("RGB").save(
        out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out


# ───────────────────────── 업로드 호스트 ─────────────────────────
def _catbox(path: Path, mime: str = "image/jpeg") -> str:
    def _up():
        with open(path, "rb") as f:
            r = requests.post(
                CATBOX,
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (path.name, f, mime)},
                timeout=120,
            )
            r.raise_for_status()
            url = r.text.strip()
            if not url.startswith("http"):
                raise RuntimeError(f"catbox upload failed: {r.text[:200]}")
            return url
    return _retry(_up, attempts=2, base_wait=3)


def _uguu(path: Path, mime: str = "image/jpeg") -> str:
    def _up():
        with open(path, "rb") as f:
            r = requests.post(UGUU, files={"files[]": (path.name, f, mime)}, timeout=120)
            r.raise_for_status()
            return r.json()["files"][0]["url"]
    return _retry(_up, attempts=2, base_wait=3)


def _mastodon_media(path: Path, mime: str = "image/jpeg") -> str:
    """이미 쓰고 있는 Mastodon 계정의 미디어 스토리지를 업로드 호스트로 활용.

    게시물은 만들지 않고 첨부파일(미사용)만 업로드하므로 계정에 노출되지 않는다.
    """
    base = os.getenv("MASTODON_EN_BASE_URL") or os.getenv("MASTODON_KO_BASE_URL")
    token = os.getenv("MASTODON_EN_TOKEN") or os.getenv("MASTODON_KO_TOKEN")
    if not base or not token:
        raise RuntimeError("Mastodon 미디어 호스팅 불가: 토큰 없음")

    def _up():
        with open(path, "rb") as f:
            r = requests.post(f"{base}/api/v2/media",
                              headers={"Authorization": f"Bearer {token}"},
                              files={"file": (path.name, f, mime)}, timeout=180)
            r.raise_for_status()
            url = r.json().get("url") or r.json().get("preview_url")
            if not url:
                raise RuntimeError(f"mastodon media upload failed: {r.text[:200]}")
            time.sleep(2)  # 미디어 처리(트랜스코딩) 대기
            return url
    return _retry(_up, attempts=2, base_wait=3)


IMAGE_HOSTS = [_catbox, _uguu, _mastodon_media]


def upload_image(path) -> str:
    """호스트 폴백 체인 — 하나가 죽어도 다음으로."""
    last = None
    for host in IMAGE_HOSTS:
        try:
            return host(Path(path))
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"모든 이미지 호스트 실패: {last}")


def upload_video(path) -> str:
    last = None
    for host in IMAGE_HOSTS:
        try:
            return host(Path(path), "video/mp4")
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"모든 비디오 호스트 실패: {last}")


class InstagramPublisher(Publisher):
    name = "instagram"
    env_prefix_override = "IG"
    env_suffixes = ["USER_ID", "TOKEN"]

    def _post_media(self, uid: str, token: str, payload: dict, timeout: int = 60):
        """미디어 컨테이너 생성 — Meta 실패 본문을 그대로 남긴다."""
        return requests.post(f"{GRAPH}/{uid}/media", data={**payload, "access_token": token},
                             timeout=timeout)

    # ─────────────────── 중복 게시 방지 ───────────────────
    def _recent_media(self, uid: str, token: str, limit: int = 10) -> list[dict]:
        try:
            r = requests.get(f"{GRAPH}/{uid}/media", params={
                "fields": "id,media_type,timestamp,caption",
                "limit": limit, "access_token": token}, timeout=60)
            if r.status_code >= 400:
                return []
            return r.json().get("data", [])
        except Exception:  # noqa: BLE001 - 조회 실패는 '중복 아님'으로 취급
            return []

    def _posted_recently(self, uid: str, token: str, caption: str,
                         minutes: int = 180) -> bool:
        """같은 캡션의 게시물이 최근 N분 안에 이미 있으면 True.

        왜 필요한가(2026-09-22): Meta가 media_publish 에 403을 돌려주면서도
        게시물은 실제로 만들어버리는 경우가 있다(meta_publish_rate_like 등).
        그러면 호스트 폴백(catbox→uguu→mastodon)을 도는 동안 같은 글이
        3번씩 올라갔다. 발행 전·후로 실물을 확인해 중복을 차단한다.
        """
        key = (caption or "").strip()[:200]
        if not key:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        for m in self._recent_media(uid, token, limit=12):
            if (m.get("caption") or "").strip()[:200] != key:
                continue
            try:
                ts = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts >= cutoff:
                return True
        return False

    def _publish(self, lang, content, card_paths, creds):
        uid, token = creds["USER_ID"], creds["TOKEN"]
        caption = content["ig_caption"]

        # 게시 전 중복 검사 — 같은 캡션이 방금 올라갔다면 이번 사이클은 건너뛴다.
        if self._posted_recently(uid, token, caption):
            print(f"  [instagram:{lang}] 최근 동일 캡션 게시 확인 — 중복 방지로 건너뜀")
            return {"platform": self.name, "lang": lang, "status": "skipped",
                    "detail": "최근 동일 캡션 게시 존재"}

        jpegs = [to_jpeg(p) for p in card_paths]

        last_err = None
        for host in IMAGE_HOSTS:  # 호스트가 죽으면 다음 호스트로 (업로드 단계만 폴백)
            child_ids: list[str] = []
            try:
                for path in jpegs:
                    image_url = host(path)
                    r = _retry(lambda u=image_url: self._post_media(uid, token, {
                        "image_url": u, "is_carousel_item": "true"}), attempts=2, base_wait=4)
                    if r.status_code >= 400:
                        raise RuntimeError(
                            f"{host.__name__} /media 실패 {r.status_code}: {r.text[:220]}")
                    child_ids.append(r.json()["id"])
                    time.sleep(1)

                r = _retry(lambda: self._post_media(uid, token, {
                    "media_type": "CAROUSEL",
                    "children": ",".join(child_ids),
                    "caption": caption,
                }, timeout=90), attempts=2, base_wait=4)
                if r.status_code >= 400:
                    raise RuntimeError(f"캐러셀 컨테이너 실패 {r.status_code}: {r.text[:220]}")
                creation_id = r.json()["id"]

                # 발행은 단 1회 시도. 재시도하면 같은 글이 2~3번 올라간다.
                r = requests.post(f"{GRAPH}/{uid}/media_publish", data={
                    "creation_id": creation_id, "access_token": token,
                }, timeout=120)
                if r.status_code < 400:
                    return {"platform": self.name, "lang": lang, "status": "published",
                            "id": r.json().get("id")}
                raise RuntimeError(f"media_publish 실패 {r.status_code}: {r.text[:220]}")
            except Exception as e:  # noqa: BLE001 - 다음 호스트로 폴백
                last_err = e
                print(f"  [instagram:{lang}] {host.__name__} 경로 실패: {str(e)[:160]}")
                # ★ 오류를 받았어도 실제로는 게시됐을 수 있다 → 확인 후 중단
                if self._posted_recently(uid, token, caption, minutes=20):
                    print(f"  [instagram:{lang}] 오류 응답에도 실제 게시 확인 — "
                          f"추가 시도 중단(중복 방지)")
                    return {"platform": self.name, "lang": lang, "status": "published",
                            "id": None, "detail": "오류 응답 후 실제 게시 확인"}

        raise RuntimeError(f"모든 업로드 경로 실패: {last_err}")

    def publish_reel(self, lang, caption, video_path, creds) -> dict:
        """나레이션 리일스(mp4) 발행 — 영상은 인코딩 대기 polling이 필요하다."""
        uid, token = creds["USER_ID"], creds["TOKEN"]

        # 중복 방지: 같은 캡션이 방금 올라갔다면 건너뛴다.
        if self._posted_recently(uid, token, caption):
            print(f"  [instagram_reels:{lang}] 최근 동일 캡션 게시 확인 — 중복 방지로 건너뜀")
            return {"platform": f"{self.name}_reels", "lang": lang, "status": "skipped",
                    "detail": "최근 동일 캡션 게시 존재"}

        # 비디오도 호스트 폴백 체인 적용 (2026-10-03: catbox는 Meta측 릴스 처리 실패 유발 → uguu 우선)
        video_url, last = None, None
        # 2026-10-10 실측: uguu가 간헐적으로 실패하면 아래 호스트로 넘어간다.
        #   영어 계정 1건이 이 경로에서 ig=error 로 기록됐으나 실제로는 게시돼 있었다
        #   (Graph API 응답 지연). → 각 호스트를 2회씩 재시도해 흡수한다.
        for host in (_uguu, _catbox, _mastodon_media):
            for attempt in (1, 2):
                try:
                    video_url = host(Path(video_path), "video/mp4")
                    break
                except Exception as e:  # noqa: BLE001
                    last = e
                    if attempt == 1:
                        import time as _t
                        _t.sleep(3)
            if video_url:
                break
        if not video_url:
            return {"platform": f"{self.name}_reels", "lang": lang, "status": "error",
                    "detail": f"비디오 업로드 실패: {last}"}

        r = _retry(lambda: requests.post(f"{GRAPH}/{uid}/media", data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
            "access_token": token,
        }, timeout=120))
        if r.status_code >= 400:
            return {"platform": f"{self.name}_reels", "lang": lang, "status": "error",
                    "detail": f"리일스 컨테이너 실패 {r.status_code}: {r.text[:220]}"}
        creation_id = r.json()["id"]

        # 영상 처리 완료까지 대기 (최대 5분)
        for _ in range(30):
            time.sleep(10)
            st = _retry(lambda: requests.get(f"{GRAPH}/{creation_id}", params={
                "fields": "status_code", "access_token": token}, timeout=60))
            code = st.json().get("status_code")
            if code == "FINISHED":
                break
            if code == "ERROR":
                return {"platform": f"{self.name}_reels", "lang": lang,
                        "status": "error", "detail": f"미디어 처리 실패: {st.text[:200]}"}
        else:
            return {"platform": f"{self.name}_reels", "lang": lang,
                    "status": "error", "detail": "영상 인코딩 타임아웃(5분)"}

        r = _retry(lambda: requests.post(f"{GRAPH}/{uid}/media_publish", data={
            "creation_id": creation_id, "access_token": token,
        }, timeout=120))
        r.raise_for_status()
        return {"platform": f"{self.name}_reels", "lang": lang,
                "status": "published", "id": r.json().get("id")}
