"""미발행분 복구 도구 (재사용용).

사용:
    python scripts/resend_missing.py --cycles am,pm        # IG 카드만 재발행
    python scripts/resend_missing.py --cycles am --regen   # 원문으로 콘텐츠 재생성 후 발행
    python scripts/resend_missing.py --reels ev            # TTS 리일스 4개 언어 생성·발행
    python scripts/resend_missing.py --cycles pm --reels ev --log

전제: data/cards/<오늘>/<cycle>/content.json + <lang>/card_*.png 이 이미 존재해야 한다.
(콘텐츠 재생성 시 카드까지 새로 렌더링한다)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BASE / ".env", override=True)

from src import generator, quotes, reels, source_log  # noqa: E402
from src.cards import render_cards  # noqa: E402
from src.crawler import Post  # noqa: E402
from src.error_log import log_error  # noqa: E402
from src.publishers.instagram import InstagramPublisher  # noqa: E402

KST = timezone(timedelta(hours=9))
DATA = BASE / "data"
LANGS = ["en", "ko", "zh-cn", "fr"]

lines: list[str] = []


def quotes_used() -> set[str]:
    """오늘 이미 사용한 명언 id (중복 발행 방지)."""
    return source_log.used_post_ids_today(DATA)


def p(msg: str) -> None:
    print(msg, flush=True)
    lines.append(str(msg))


def _clear_dir(d: Path) -> None:
    if d.exists():
        for f in d.iterdir():
            if f.is_file():
                f.unlink()


def _cards(d: Path, lang: str) -> list[Path]:
    return sorted((d / lang).glob("card_*.png"), key=lambda x: int(x.stem.split("_")[1]))


def _maybe_regen(d: Path, meta: dict, cycle: str) -> dict:
    """명언 은행에서 새 명언을 뽑아 콘텐츠를 다시 생성. 실패 시 기존 반환.

    (커뮤니티 재수집 → 최근 사용 제외 명언 재선정으로 교체됨)
    """
    theme = generator.THEME_BY_CYCLE.get(cycle)
    try:
        quote = quotes.pick(theme, exclude=quotes_used(), data_dir=DATA)
    except Exception as e:  # noqa: BLE001
        p(f"  명언 선정 실패: {e}")
        return meta["contents"]
    try:
        contents = generator.generate(quote, BASE / "config" / "prompts", theme=theme)
    except Exception as e:  # noqa: BLE001
        p(f"  생성 실패: {e}")
        return meta["contents"]
    for lang, c in contents.items():
        _clear_dir(d / lang)
        render_cards(c["ig_cards"], d / lang, lang, author=c.get("quote_author"))
    meta = {**meta, "contents": contents, "theme": theme,
            "title": quote.title, "source": quote.source, "url": quote.url,
            "quote": {"id": quote.id, "author": quote.author, "text": quote.text}}
    (d / "content.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
    quotes.mark_used(DATA, quote.id)
    p(f"  명언 재선정({quote.id}) 후 콘텐츠 재생성 + 카드 재렌더")
    return contents


def publish_cards(cycle: str, regen: bool, do_log: bool) -> None:
    d = DATA / "cards" / TODAY / cycle
    if not (d / "content.json").exists():
        p(f"  [{cycle}] content.json 없음 — 건너뜀")
        return
    meta = json.loads((d / "content.json").read_text(encoding="utf-8"))
    contents = _maybe_regen(d, meta, cycle) if regen else meta["contents"]

    ig = InstagramPublisher()
    published = []
    for lang in LANGS:
        if ig.missing(lang):
            p(f"  [{cycle}/{lang}] 자격증명 누락: {ig.missing(lang)}")
            continue
        try:
            r = ig.publish(lang, contents[lang], _cards(d, lang))
            p(f"  [{cycle}/{lang}] {r['status']} {r.get('id') or r.get('detail','')}")
            if r["status"] == "published":
                published.append(lang)
            else:
                log_error(DATA, f"resend:instagram:{cycle}:{lang}", r["detail"])
        except Exception as e:  # noqa: BLE001
            p(f"  [{cycle}/{lang}] 예외: {str(e)[:300]}")
            log_error(DATA, f"resend:instagram:{cycle}:{lang}", str(e)[:500])

    if do_log and published:
        source_log.append(
            DATA, f"{cycle}-resent",
            Post(id=meta.get("url", ""), source=meta.get("source", ""),
                 title=meta.get("title", ""), url=meta.get("url", ""),
                 views=meta.get("views"), content="", comments=[]),
            "published", f"IG 재발행 {len(published)}개 언어: {','.join(published)}",
        )


def publish_reels(cycle: str, do_log: bool) -> None:
    d = DATA / "cards" / TODAY / cycle
    if not (d / "content.json").exists():
        p(f"  [{cycle}] content.json 없음 — 리일스 건너뜀")
        return
    meta = json.loads((d / "content.json").read_text(encoding="utf-8"))
    contents = meta["contents"]
    p(f"  원글: {meta.get('title')} (조회수 {meta.get('views')})")

    ig = InstagramPublisher()
    vdir = DATA / "reels" / TODAY / cycle
    published = []
    for lang in LANGS:
        if ig.missing(lang):
            p(f"  [{cycle}/{lang}] 자격증명 누락: {ig.missing(lang)}")
            continue
        script = (contents[lang].get("reels_script") or "").strip() \
            or " ".join(contents[lang]["ig_cards"])
        try:
            mp4 = reels.make_reels(script, lang, _cards(d, lang), vdir)
            p(f"  [{lang}] 영상 생성 {mp4.name} ({mp4.stat().st_size/1_048_576:.1f}MB) "
              f"/ 음성 {reels.voice_for(lang)}")
            r = ig.publish_reel(lang, contents[lang]["ig_caption"], mp4, ig.credentials(lang))
            p(f"  [{lang}] 리일스 {r['status']} {r.get('id') or r.get('detail','')}")
            if r["status"] == "published":
                published.append(lang)
            else:
                log_error(DATA, f"resend:reels:{cycle}:{lang}", r["detail"])
        except Exception as e:  # noqa: BLE001
            p(f"  [{lang}] 리일스 실패: {str(e)[:300]}")
            log_error(DATA, f"resend:reels:{cycle}:{lang}", str(e)[:500])

    if do_log and published:
        source_log.append(
            DATA, f"{cycle}-reels",
            Post(id=meta.get("url", ""), source=meta.get("source", ""),
                 title=meta.get("title", ""), url=meta.get("url", ""),
                 views=meta.get("views"), content="", comments=[]),
            "published", f"TTS 리일스 발행 {len(published)}개 언어: {','.join(published)}",
        )


if __name__ == "__main__":
    TODAY = datetime.now(KST).date().isoformat()
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", default="", help="카드 재발행할 사이클 (쉼표 구분: am,pm,ev,night)")
    ap.add_argument("--reels", default="", help="리일스 생성·발행할 사이클")
    ap.add_argument("--regen", action="store_true", help="원문으로 콘텐츠 재생성 후 발행")
    ap.add_argument("--log", action="store_true", help="source_log에 복구 기록 남기기")
    args = ap.parse_args()

    p(f"복구 시작 {datetime.now(KST).isoformat(timespec='seconds')} (오늘 {TODAY})")
    for c in [x for x in args.cycles.split(",") if x]:
        p(f"\n===== IG 카드 재발행: {c} =====")
        publish_cards(c, args.regen, args.log)
    for c in [x for x in args.reels.split(",") if x]:
        p(f"\n===== TTS 리일스: {c} =====")
        publish_reels(c, args.log)
    p(f"\n복구 종료 {datetime.now(KST).isoformat(timespec='seconds')}")
    (BASE / "_resend_report.txt").write_text("\n".join(lines), encoding="utf-8")
