"""숏폼 E2E 테스트 — 기존 미리보기 콘텐츠(2026-09-21_0134)로 KO 1편 생성."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(BASE / ".env", override=True)

from src import shortform  # noqa: E402

REP = BASE / "_sf_report.txt"
lines: list[str] = []


def out(s: str) -> None:
    print(s, flush=True)
    lines.append(s)


def main() -> None:
    src_json = BASE / "data" / "preview" / "2026-09-21_0134" / "content.json"
    data = json.loads(src_json.read_text(encoding="utf-8"))
    contents = data["contents"]
    out(f"source: {data.get('title', '')[:60]}")

    work = BASE / "data" / "preview" / "shortform_test"

    # 1) 스토리보드 (DeepSeek 1회, 기존 것이 있으면 재사용 → TTS 캐시 유효)
    sb_path = work / "storyboard.json"
    if sb_path.exists():
        board = json.loads(sb_path.read_text(encoding="utf-8"))
        out("storyboard: 기존 파일 재사용")
    else:
        board = shortform.plan_scenes(contents, theme="고난과 역경")
        sb_path.parent.mkdir(parents=True, exist_ok=True)
        sb_path.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    out(f"image_prompts: {len(board['image_prompts'])}")
    for l, sc in board["scenes"].items():
        out(f"  [{l}] scenes={len(sc)} sub1={sc[0]['subtitle'][:30]}")

    # 2) 이미지 5장 (공용)
    images = shortform.gen_images(board["image_prompts"], work / "images", seed_base=7000)
    out(f"images: {[p.name for p in images]}")

    # 3) KO 숏폼
    mp4 = shortform.make_shortform(
        "ko", contents["ko"], board["scenes"]["ko"], images, work)
    out(f"DONE: {mp4} {mp4.stat().st_size // 1024}KB")

    REP.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback
        lines.append("FATAL: " + traceback.format_exc()[-800:])
        REP.write_text("\n".join(lines), encoding="utf-8")
        raise
