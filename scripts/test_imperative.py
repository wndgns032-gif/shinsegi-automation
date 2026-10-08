"""지시형(命令형) 톤 규칙 검증 — 새 프롬프트가 실제로 통하는지 확인.

게시 없이 스토리만 생성한다 (파일 저장·명언 이력 변경 없음).

사용:
  python scripts/test_imperative.py [개수]
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from src import fable, quotes  # noqa: E402
from src.error_log import log_error  # noqa: E402

DATA = BASE / "data"


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env", override=True)

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    ok = 0
    for i in range(n):
        print(f"\n{'=' * 66}")
        print(f"  시도 {i + 1}/{n}")
        print("=" * 66)
        quote, theme = fable.pick_quote(DATA)
        print(f"명언: [{quote.id}] {quote.author_of('ko')} — {quote.text_of('ko')}")
        try:
            story = fable.generate(quote, theme, mock=False)
        except ValueError as e:
            print(f"[검수 실패 — 재생성 필요] {str(e)[:400]}")
            continue
        except Exception as e:  # noqa: BLE001
            log_error(DATA, "test-imperative", str(e)[:300])
            print(f"[오류] {type(e).__name__}: {str(e)[:200]}")
            continue

        ok += 1
        print("\n--- 2장면 hook (명령형이어야 함) ---")
        for lang in fable.LANGS:
            lines = story["hook"]["lines"].get(lang) or []
            print(f"  [{lang:6s}] {lines[0][:70]}")
        print("\n--- 9장면 real (명령형이어야 함) ---")
        print(f"  [ko] {story['scenes'][8]['narration']['ko'][:70]}")
        print("\n--- 10장면 outro = moral (명령형이어야 함) ---")
        for lang in fable.LANGS:
            print(f"  [{lang:6s}] {story['moral'][lang][:70]}")
        print(f"\n[ok] {ok}/{n} 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())