"""YouTube 채널 현황 스크레이퍼 (공개 페이지 기반, 2026-10-11).

왜 스크레이핑인가: 이 프로젝트의 OAuth refresh token 은
`youtube.upload` 스코프로만 발급돼 있어 API 로 조회수/구독자를 읽을 수 없다
(invalid_scope 실측). 읽기 스코프 재인증은 로이 브라우저가 필요해서,
일회성 현황 확인은 인증 없이 되는 공개 페이지 파싱이 가장 빠르다.

주의: 공개 HTML 구조에 의존한다. 나중에 깨지면 그때 고치면 된다.
사용: python scripts/youtube_public_stats.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]

HANDLES = {
    "ko": "@WisdomPathroad",
    "en": "@wisdompath-en",
    "zh-cn": "@shinsegi-zh",
    "fr": "@shinsegi-fr",
}

HDR = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


def _walk(node):
    """중첩된 dict/list 를 전부 순회하며 dict 를 yielding."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _text(o) -> str:
    """YouTube 의 {'text': ...} / {'simpleText': ...} 구조를 문자열로."""
    if o is None:
        return ""
    if isinstance(o, str):
        return o
    if isinstance(o, dict):
        if "simpleText" in o:
            return o["simpleText"]
        if "runs" in o:
            return "".join(r.get("text", "") for r in o["runs"])
        if "content" in o:
            return o["content"]
    return ""


def _views(s: str) -> int:
    s = s.replace(",", "").strip().lower()
    m = re.match(r"([\d.]+)\s*([kmb]?)\s*views?", s)
    if not m:
        return 0
    n = float(m.group(1))
    return int(n * {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(m.group(2), 1))


def scrape(handle: str) -> dict:
    out: dict = {"handle": handle, "error": None, "videos": []}
    try:
        r = requests.get(f"https://www.youtube.com/{handle}/shorts",
                         headers=HDR, timeout=30)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return out

    m = re.search(r"var ytInitialData = (\{.*?\});</script>", r.text, re.S)
    if not m:
        m = re.search(r'ytInitialData"\]\s*=\s*(\{.*?\});', r.text, re.S)
    if not m:
        out["error"] = "ytInitialData 파싱 실패 (youtube 응답 포맷 변경)"
        return out

    try:
        data = json.loads(m.group(1))
    except Exception as e:  # noqa: BLE001
        out["error"] = f"JSON 파싱 실패: {str(e)[:100]}"
        return out

    # 구독자 수 (헤더)
    for n in _walk(data):
        sv = n.get("subscriberCountText") or n.get("subscriberCount")
        if isinstance(sv, dict) and "content" in sv:
            out["subs"] = _text(sv) or sv.get("simpleText", "")
            break
        if isinstance(sv, str) and "subscriber" in sv.lower():
            out["subs"] = sv
            break

    seen = set()
    for n in _walk(data):
        vm = n.get("shortsLockupViewModel")
        if not isinstance(vm, dict):
            continue
        ent = vm.get("entityId", "")
        vid = vm.get("onTap", {}).get("innertubeCommand", {}) \
                  .get("reelWatchEndpoint", {}).get("videoId")
        if not vid:
            m2 = re.search(r"shorts/([\w-]{11})", ent or "")
            vid = m2.group(1) if m2 else None
        if not vid or vid in seen:
            continue
        seen.add(vid)
        overlay = vm.get("overlayMetadata", {}) or {}
        title = _text(vm.get("overlayMetadata", {}).get(
            "primaryText", {}).get("content")) or _text(
            vm.get("headline", {}).get("simpleText"))
        out["videos"].append({
            "id": vid,
            "title": title,
            "views": _views(_text(overlay.get("secondaryText", {}).get("content"))),
            "views_raw": _text(overlay.get("secondaryText", {}).get("content")),
            "age": _text(overlay.get("primaryText", {}).get("content")),
            "duration": _text(overlay.get("thumbnail", {}).get(
                "thumbnails", [{}])[-1].get("overlayText", {}).get("content")),
        })
    return out


def main() -> int:
    res = {}
    for lang, h in HANDLES.items():
        print(f"[{lang}] {h} 조회 중...", flush=True)
        res[lang] = scrape(h)
        time.sleep(1.5)

    (ROOT / "data" / "youtube_public_stats.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n" + "=" * 76)
    print(f"{'언어':<7}{'구독자':<14}{'게시':>4}{'합계조회':>10}   채널")
    print("=" * 76)
    for lang, r in res.items():
        if r["error"]:
            print(f"{lang:<7}❌ {r['error']}")
            continue
        vs = r["videos"]
        tot = sum(v["views"] for v in vs)
        print(f"{lang:<7}{r.get('subs','?'):<14}{len(vs):>4}{tot:>10,}   {r['handle']}")

    print("\n" + "=" * 76)
    for lang, r in res.items():
        if r["error"] or not r["videos"]:
            continue
        print(f"\n■ {lang} {r['handle']}  구독자 {r.get('subs','?')}")
        for v in r["videos"]:
            print(f"   {v['age']:<6} {v['views_raw']:>14}  {v['duration']:>5}  {v['title'][:46]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
