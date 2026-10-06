"""GitHub 리포로 push — .env 의 GH_PAT/GH_REPO 를 읽어 자동 인증.

사용 (GH_PAT 와 GH_REPO 가 .env 에 있어야 함):
    python scripts/push_to_github.py

최초 실행 시:
- remote origin 이 없으면 추가 (PAT 인증 URL)
- main 브랜치 push (-u)
이후 실행 시:
- pull --rebase (원격이 앞서 있을 때) 후 push
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


def sh(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    return r.returncode, (r.stdout + r.stderr).strip()


def main() -> int:
    load_dotenv()
    pat = os.getenv("GH_PAT", "").strip()
    repo = os.getenv("GH_REPO", "").strip()  # owner/repo

    if not pat or not repo:
        print("[오류] GH_PAT 또는 GH_REPO 가 .env 에 없다.")
        return 1

    root = Path(__file__).resolve().parent.parent
    os.chdir(root)

    remote_url = f"https://{pat}@github.com/{repo}.git"

    # 1) remote 상태 확인
    rc, out = sh(["git", "remote", "get-url", "origin"])
    if rc != 0:
        print(f"[add] remote origin 추가: {repo}")
        sh(["git", "remote", "add", "origin", remote_url])
    else:
        # 기존 origin 이 다른 리포를 가리키면 갱신
        if pat not in out:
            print(f"[update] remote origin URL 갱신: {repo}")
            sh(["git", "remote", "set-url", "origin", remote_url])

    # 2) push
    print("[push] main → origin/main ...")
    rc, out = sh(["git", "push", "-u", "origin", "main"])
    print(out[-800:] if out else "(no output)")
    if rc != 0:
        # 원격이 앞서 있을 가능성 — 강제 pull --rebase 후 재시도
        if "non-fast-forward" in out or "rejected" in out or "fetch first" in out:
            print("[pull] 원격이 앞서 있음 — rebase 시도")
            rc2, out2 = sh(["git", "pull", "--rebase", "origin", "main"])
            print(out2[-400:] if out2 else "")
            rc, out = sh(["git", "push", "-u", "origin", "main"])
            print(out[-400:] if out else "")
        if rc != 0:
            print(f"[오류] push 실패: rc={rc}")
            return 2

    print(f"[ok] push 완료 — https://github.com/{repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
