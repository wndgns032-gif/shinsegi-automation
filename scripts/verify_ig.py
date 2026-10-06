"""오늘 각 IG 계정에 실제로 올라간 게시물 확인."""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env", override=True)
GRAPH = "https://graph.facebook.com/v23.0"

out = []


def p(m: str) -> None:
    print(m, flush=True)
    out.append(str(m))


for lang in ["en", "ko", "zh-cn", "fr"]:
    pre = f"IG_{lang.upper().replace('-', '_')}"
    uid, tok = os.getenv(f"{pre}_USER_ID"), os.getenv(f"{pre}_TOKEN")
    r = requests.get(f"{GRAPH}/{uid}/media", params={
        "fields": "id,media_type,timestamp,caption,permalink",
        "limit": 12, "access_token": tok}, timeout=60)
    if r.status_code != 200:
        p(f"[{lang}] 조회 실패 {r.status_code} {r.text[:200]}")
        continue
    items = [d for d in r.json().get("data", []) if str(d.get("timestamp", "")).startswith("2026-09-20")]
    p(f"\n[{lang}] 오늘 게시물 {len(items)}건")
    for d in items:
        cap = (d.get("caption") or "").replace("\n", " ")[:70]
        p(f"   {d['timestamp'][11:16]} | {d['media_type']:14s} | {d.get('permalink','')} | {cap}")
    if not items:
        p("   없음")

(BASE / "_verify_report.txt").write_text("\n".join(out), encoding="utf-8")
