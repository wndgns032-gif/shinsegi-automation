"""최근 게시물 몇 개만 확인 (날짜 필터 없음)."""
import os, sys
from pathlib import Path
import requests

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from dotenv import load_dotenv
load_dotenv(BASE / ".env", override=True)

GRAPH = "https://graph.facebook.com/v23.0"
out = []
for lang in ("en", "ko", "zh-cn", "fr"):
    uid = os.getenv(f"IG_{lang.upper().replace('-', '_')}_USER_ID")
    tok = os.getenv(f"IG_{lang.upper().replace('-', '_')}_TOKEN")
    r = requests.get(f"{GRAPH}/{uid}/media", params={
        "fields": "media_type,permalink,caption,timestamp",
        "limit": "4", "access_token": tok}, timeout=60)
    r.raise_for_status()
    out.append(f"== {lang} ==")
    for m in r.json().get("data", []):
        cap = (m.get("caption") or "").replace("\n", " ")[:60]
        out.append(f"  {m['timestamp']} | {m['media_type']:14s} | {m['permalink']} | {cap}")
(BASE / "_recent.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
