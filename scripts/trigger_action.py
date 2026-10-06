"""GitHub Actions workflow_dispatch 트리거 — PAT 로 리포의 워크플로우를 수동 실행.

사용:
    python scripts/trigger_action.py <workflow_filename>
    (예: python scripts/trigger_action.py fable.yml)

GH_PAT 와 GH_REPO 가 .env 에 있어야 함.
"""
from __future__ import annotations

import os
import sys
import time

import requests
from dotenv import load_dotenv


def main() -> int:
    if len(sys.argv) < 2:
        print("사용: python scripts/trigger_action.py <workflow.yml> [input1=val1 input2=val2 ...]")
        return 1

    workflow = sys.argv[1]
    inputs = {}
    for arg in sys.argv[2:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            inputs[k] = v

    load_dotenv()
    pat = os.getenv("GH_PAT", "").strip()
    repo = os.getenv("GH_REPO", "").strip()

    if not pat or not repo:
        print("[오류] GH_PAT 또는 GH_REPO 가 .env 에 없다.")
        return 1

    H = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 1) 브랜치 기본 ref 획득 (보통 main)
    r = requests.get(f"https://api.github.com/repos/{repo}", headers=H, timeout=30)
    if r.status_code != 200:
        print(f"[오류] 리포 조회 실패: {r.status_code} {r.text[:200]}")
        return 1
    branch = r.json().get("default_branch", "main")

    # 2) dispatch
    r = requests.post(
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches",
        headers=H,
        json={"ref": branch, "inputs": inputs or {}},
        timeout=30,
    )
    if r.status_code != 204:
        print(f"[오류] dispatch 실패: {r.status_code} {r.text[:300]}")
        return 2

    print(f"[ok] {workflow} dispatch 전송 — 브랜치 {branch}")
    print(f"     진행 상황: https://github.com/{repo}/actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
