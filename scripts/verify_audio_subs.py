"""낭독·자막 실검증 (2026-10-11 신설).

기존 verify_three.py 는 길이·해상도·채도만 봤다. 그래서 아래를 놓쳤다:
  · 10개 장면이 전부 같은 mp3 → 같은 문장이 10번 반복
  · 자막이 10장면 중 2장면만 존재
  · 훅 문구가 0초~끝까지 화면 상단에 붙박이
이 스크립트는 "소리"와 "자막"을 실제로 검사한다.

사용:  python scripts/verify_audio_subs.py --date 2026-10-11-v3
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LANGS = ["ko", "en", "zh-cn", "fr"]


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def check_dir(d: Path, verbose: bool = True) -> tuple[bool, list[str]]:
    """data/fables/<date> 한 편을 검사. (ok, 문제목록)"""
    problems: list[str] = []
    story_p = d / "story.json"
    if not story_p.exists():
        return False, ["story.json 없음"]

    for lang in LANGS:
        work = d / f"work_{lang}"
        mp4 = d / f"fable_{lang}.mp4"
        if not mp4.exists():
            problems.append(f"{lang}: fable_{lang}.mp4 없음")
            continue

        # ── 1) 낭독 중복 ─────────────────────────────────────
        voices = sorted(work.glob("voice_*.mp3"))
        if len(voices) < 8:
            problems.append(f"{lang}: 낭독 파일 {len(voices)}개 (10개여야 함)")
        dg = [_md5(v) for v in voices]
        dup = len(dg) - len(set(dg))
        if dup:
            # 같은 해시가 몇 개씩인지
            from collections import Counter
            worst = Counter(dg).most_common(1)[0][1]
            problems.append(
                f"{lang}: 🔴 낭독 {dup}개 중복 (최대 {worst}장면이 같은 음성) "
                "→ 같은 문장이 반복됨")

        # ── 2) 낭독 길이 편차 (모두 같은 길이면 의심) ─────────
        try:
            from src import tts
            durs = [tts._audio_duration(v) for v in voices]
            if len(set(round(x, 2) for x in durs)) <= 1 and len(voices) > 3:
                problems.append(f"{lang}: 🔴 모든 낭독 길이 동일({durs[0]:.2f}초) — 의심")
        except Exception:
            pass

        # ── 3) 자막 커버리지 ─────────────────────────────────
        subs = work / "subs.ass"
        if not subs.exists():
            problems.append(f"{lang}: subs.ass 없음")
            continue
        text = subs.read_text(encoding="utf-8", errors="ignore")
        caps = [l for l in text.splitlines() if l.startswith("Dialogue:")
                and ",CAP,," in l]
        hooks = [l for l in text.splitlines() if l.startswith("Dialogue:")
                 and ",HOOK,," in l]
        try:
            import json as _json
            story = _json.loads(story_p.read_text(encoding="utf-8"))
            n = len(story["scenes"])
        except Exception:
            n = 10
        # 카드(명언/교훈)가 글자를 담당하는 장면 제외
        expect = n - 2 if n > 8 else n
        if len(caps) < expect - 1:
            problems.append(
                f"{lang}: 🔴 자막 {len(caps)}개 / 필요 {expect}개 "
                f"(장면 {n}개 중 {n - len(caps)}개 무자막)")

        # ── 4) 훅 붙박이 (영상 길이의 90% 이상 차지하면 경고) ──
        def _t(s: str) -> float:
            h, m, rest = s.split(":")
            return int(h) * 3600 + int(m) * 60 + float(rest)

        for hl in hooks:
            try:
                f = hl.split(",")
                st, en = _t(f[1].strip()), _t(f[2].strip())
            except Exception:
                continue
            total = _get_total(mp4)
            if total and (en - st) > total * 0.9:
                problems.append(
                    f"{lang}: 🔴 훅 문구가 {en - st:.1f}초/{total:.1f}초 "
                    "내내 상단 고정 → 같은 문장 반복으로 보임")
                break

    return (not problems), problems


def _get_total(mp4: Path) -> float:
    try:
        from src import tts
        return tts._audio_duration(mp4)
    except Exception:
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--all-suffix", action="store_true",
                    help="date 뒤에 -stocks / -biz 붙은 편까지 검사")
    a = ap.parse_args()

    dates = [a.date]
    if a.all_suffix:
        dates += [f"{a.date}-stocks", f"{a.date}-biz"]

    bad = 0
    for dt in dates:
        d = ROOT / "data" / "fables" / dt
        print(f"\n===== {dt} =====")
        if not d.exists():
            print("  ❌ 폴더 없음")
            bad += 1
            continue
        ok, problems = check_dir(d)
        if ok:
            print("  ✅ 낭독 전 장면 서로 다름 / 자막·훅 정상")
        else:
            bad += 1
            for p in problems:
                print(f"  {p}")
    print("\n" + ("❌ 문제 있음" if bad else "✅ 전체 정상"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
