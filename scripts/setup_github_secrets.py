"""GitHub Actions secrets 일괄 등록 스크립트.

로이가 GitHub private repo 를 만들고 fine-grained PAT 를 발급받은 뒤,
.env 의 모든 자격증명을 리포 Secrets 로 한 번에 밀어 넣는다.

사용:
    1) .env 에 GH_PAT=<your-fine-grained-PAT> 추가
    2) .env 에 GH_REPO=<owner>/<repo> 추가 (예: roy-choi/shinsegi-automation)
    3) python scripts/setup_github_secrets.py
"""
from __future__ import annotations

import os
import sys
import time
from base64 import b64decode, b64encode

import requests
from dotenv import load_dotenv
from nacl import public


# .env 에서 리포에 밀어넣을 시크릿 목록 (값이 있는 것만 등록됨)
SECRET_NAMES = [
    "DEEPSEEK_API_KEY", "HF_TOKEN",
    "IG_KO_TOKEN", "IG_KO_USER_ID", "IG_EN_TOKEN", "IG_EN_USER_ID",
    "IG_ZH_CN_TOKEN", "IG_ZH_CN_USER_ID", "IG_FR_TOKEN", "IG_FR_USER_ID",
    "MASTODON_EN_TOKEN", "MASTODON_KO_TOKEN", "MASTODON_ZH_CN_TOKEN", "MASTODON_FR_TOKEN",
    "MASTODON_EN_BASE_URL", "MASTODON_KO_BASE_URL", "MASTODON_ZH_CN_BASE_URL", "MASTODON_FR_BASE_URL",
    "FB_EN_PAGE_ID", "FB_FR_PAGE_ID", "FB_KO_PAGE_ID", "FB_ZH_CN_PAGE_ID", "META_USER_ID",
    "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_KO_REFRESH_TOKEN", "YOUTUBE_FR_REFRESH_TOKEN",
    # 2026-10-07 추가: 채널 재배치로 zh-cn / en 토큰이 생김
    "YOUTUBE_ZH_CN_REFRESH_TOKEN", "YOUTUBE_EN_REFRESH_TOKEN",
    # GH_PAT / GH_REPO 자체는 시크릿으로 올리지 않는다
]


def main() -> int:
    load_dotenv()
    pat = os.getenv("GH_PAT", "").strip()
    repo = os.getenv("GH_REPO", "").strip()

    if not pat or not repo:
        print("[오류] GH_PAT 또는 GH_REPO 가 .env 에 없다.")
        print("       .env 에 다음 두 줄 추가 후 재실행:")
        print('       GH_PAT=github_pat_xxx...')
        print('       GH_REPO=owner/shinsegi-automation')
        return 1

    H = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 1) 리포 접근 확인
    r = requests.get(f"https://api.github.com/repos/{repo}", headers=H, timeout=30)
    if r.status_code != 200:
        print(f"[오류] 리포 접근 실패: {r.status_code} — {r.text[:200]}")
        print("       PAT 권한(repo contents read / actions secrets write) 또는 리포 이름 확인.")
        return 1
    info = r.json()
    print(f"[ok] 리포: {info['full_name']} (private={info.get('private', False)})")

    # 2) public key 획득 (암호화에 필요)
    r = requests.get(
        f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
        headers=H, timeout=30)
    if r.status_code != 200:
        print(f"[오류] public-key 획득 실패: {r.status_code} — {r.text[:200]}")
        return 1
    pk = r.json()
    print(f"[ok] key_id: {pk['key_id']}")

    sealed = public.SealedBox(public.PublicKey(b64decode(pk["key"])))

    # 3) 시크릿 일괄 등록
    ok = missing = failed = 0
    for name in SECRET_NAMES:
        val = os.getenv(name, "").strip()
        if not val:
            print(f"  [skip] {name}: .env 에 값 없음")
            missing += 1
            continue
        enc = sealed.encrypt(val.encode())
        body = {
            "encrypted_value": b64encode(enc).decode(),
            "key_id": pk["key_id"],
        }
        # 이 PC 는 네트워크가 느려 30초 로는 ReadTimeout 이 난다 (2026-10-08 실측).
        # 실패해도 전체를 죽이지 않고 재시도한다 — 시크릿은 서로 독립적이다.
        resp = None
        for attempt, wait in enumerate((0, 3, 8), start=1):
            if wait:
                time.sleep(wait)
            try:
                resp = requests.put(
                    f"https://api.github.com/repos/{repo}/actions/secrets/{name}",
                    headers=H, json=body, timeout=90)
                break
            except requests.RequestException as e:
                print(f"  .. {name} 시도{attempt} 실패 ({type(e).__name__})")
                resp = None
        if resp is None:
            print(f"  [FAIL] {name}: 네트워크 오류 (3회 시도)")
            failed += 1
        elif resp.status_code in (201, 204):
            print(f"  [ok]   {name}")
            ok += 1
        else:
            print(f"  [FAIL] {name}: {resp.status_code} {resp.text[:120]}")
            failed += 1

    print()
    print(f"=== 결과: {ok} 등록, {missing} 누락, {failed} 실패 ===")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
