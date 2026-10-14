"""엔트리포인트.

사용:
  python -m src.main run-cycle [--cycle am|pm|ev|night|auto] [--mock]
  python -m src.main collect-metrics [--mock]
  python -m src.main prep-clips --cycle am|pm|ev [--max N]   # AI 클립 사전 생성
  python -m src.main schedule

우화 쇼츠 v6 (2026-10-05 — 하루 1편, IG+YouTube 동시):
  python -m src.main fable-story [--mock]       # 스토리 생성 (story.json 마커)
  python -m src.main fable-video [--lang ko]   # 4개 언어 렌더 (mp4 마커)
  python -m src.main fable-publish              # IG 릴스 + YT 쇼츠 업로드
  python -m src.main run-fable [--mock] [--no-publish]   # 전체 파이프라인
"""
from __future__ import annotations

import argparse
import json as _json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from src.publishers.youtube import YouTubePublisher

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
load_dotenv(BASE / ".env")


def run_cycle(cycle: str, mock: bool = False) -> None:
    from src import generator, quotes, source_log
    from src.cards import render_cards
    from src.error_log import log_error
    from src.publishers import PUBLISHERS

    print(f"[run-cycle:{cycle}] mock={mock}")
    theme = generator.THEME_BY_CYCLE.get(cycle)

    # 재료는 커뮤니티가 아니라 검증된 명언 은행에서 고른다.
    used = source_log.used_post_ids_today(DATA, cycle)
    try:
        quote = quotes.pick(theme, exclude=used, data_dir=DATA)
    except Exception as e:  # noqa: BLE001
        log_error(DATA, "quotes", str(e))
        raise
    print(f"테마: {quotes.THEME_LABELS.get(theme, theme)}")
    print(f"오늘의 명언: [{quote.id}] {quote.author_of('ko')} — {quote.text_of('ko')}")

    contents = generator.generate(quote, BASE / "config" / "prompts", mock=mock, theme=theme)

    today = datetime.now(quotes.KST).date().isoformat()
    card_map = {
        lang: render_cards(c["ig_cards"], DATA / "cards" / today / cycle / lang, lang,
                           author=c.get("quote_author"))
        for lang, c in contents.items()
    }

    # 생성 콘텐츠 아카이브 (품질 확인용)
    import json as _json
    archive = DATA / "cards" / today / cycle / "content.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(_json.dumps(
        {"source": quote.source, "url": quote.url, "title": quote.title,
         "views": quote.views, "theme": theme,
         "theme_label": quotes.THEME_LABELS.get(theme, theme),
         "quote": {"id": quote.id, "author": quote.author, "text": quote.text},
         "contents": contents},
        ensure_ascii=False, indent=2), encoding="utf-8")

    if mock:
        # mock 모드: 실제 게시 금지 (자격증명이 있어도 dry-run 처리)
        results = [{"platform": pub.name, "lang": lang, "status": "dry-run",
                    "detail": "mock mode"}
                   for pub in PUBLISHERS for lang in generator.LANGS]
    else:
        results = [
            pub.publish(lang, contents[lang], card_map[lang])
            for pub in _content_publishers()
            for lang in generator.LANGS
        ]
    for r in results:
        if r["status"] == "error":
            log_error(DATA, f"publish:{r['platform']}:{r['lang']}", r["detail"])

    n_pub = sum(1 for r in results if r["status"] == "published")
    n_dry = sum(1 for r in results if r["status"] == "dry-run")
    n_err = sum(1 for r in results if r["status"] == "error")
    status = "mock" if mock else ("published" if n_err == 0 else "partial_error")
    source_log.append(DATA, cycle, quote, status,
                      f"published={n_pub} dry-run={n_dry} error={n_err}")
    if not mock:  # mock 은 로테이션 이력을 더럽히지 않는다
        quotes.mark_used(DATA, quote.id)
    print(f"완료: published={n_pub} dry-run={n_dry} error={n_err} / 총 {len(results)}")


def _content_publishers() -> list:
    """콘텐츠(카드) 사이클에 참여할 게시 어댑터.

    2026-09-22 결정: **인스타그램은 영상(릴스) 전용**. 카드뉴스는 텍스트
    계열(Threads/Bluesky/Facebook/Telegram/Mastodon/Pinterest)에만 올린다.
    되돌리려면 .env 에 IG_CARDS=on.
    """
    from src.publishers import PUBLISHERS

    if os.getenv("IG_CARDS", "off").strip().lower() in ("1", "on", "true", "yes"):
        return PUBLISHERS
    return [p for p in PUBLISHERS if p.name != "instagram"]


def _shortform_youtube(cycle: str):
    """숏폼 회차에 YouTube 업로드를 붙일지 결정.

    ⚠️ 2026-10-11 정정 — 예전注释의 "하루 6건" 은 폐기된 규칙이다.
    videos.insert 는 2026-06-01 부터 독립 버킷(하루 100회, 1회당 1 unit).
    → 하루 3편 × 4언어 = 12건은 제한 안이므로 기본값은 **모든 회차를 올린다**.
    그래도 개별 채널에 몰아주지 않도록 .env 의 YOUTUBE_SHORTS_CYCLES 를
    `am,pm,ev,night` 처럼 지정할 수 있다(기본값은 기존 `pm` 유지).
    """
    if os.getenv("YOUTUBE_SHORTS", "on").strip().lower() not in ("1", "on", "true", "yes"):
        return None
    cycles = [c.strip() for c in os.getenv("YOUTUBE_SHORTS_CYCLES", "pm").split(",") if c.strip()]
    return YouTubePublisher() if cycle in cycles else None


_YT_QUOTA_FILE = "youtube_quota.json"


def youtube_daily_budget() -> tuple[int, int]:
    """오늘 YouTube 업로드 사용/상한을 돌려준다.

    ⚠️⚠️ 2026-10-11 정정 — 예전의 "하루 6건" 은 **폐기된 규칙**이다.
    Google 이 규칙을 두 번 바꿨다(YouTube Data API 공식 변경 기록):
      · 2025-12-04 : videos.insert 비용 1,600 units → 약 100 units 로 인하
      · 2026-06-01 : videos.insert / search.list 가 **독립 쿼터 버킷**으로 분리.
                      videos.insert 기본 한도 = **하루 100회, 1회당 1 unit**
    → 하루 3편 × 4언어 = 12건은 100건 한도 안에서 아무 문제 없다.
    → 상한은 100(기본). 더 필요하면 Google Cloud 콘솔에서 증액 신청(무료).
    그래도 가드는 남긴다 — 실제 403 quotaExceeded 를 만나면 멈추도록.

    주의: 쿼터는 **계정/채널이 아니라 Google Cloud 프로젝트 단위**다.
    4개 언어 채널이 같은 프로젝트를 쓰면 하나의 100회 버킷을 나눠 쓴다.
    """
    from src import quotes
    limit = int(os.getenv("YOUTUBE_DAILY_LIMIT", "100"))
    today = datetime.now(quotes.KST).date().isoformat()
    path = DATA / _YT_QUOTA_FILE
    used = 0
    if path.exists():
        try:
            rec = _json.loads(path.read_text(encoding="utf-8"))
            if rec.get("date") == today:
                used = int(rec.get("count", 0))
        except Exception:  # noqa: BLE001
            used = 0
    return used, limit


def youtube_quota_consume(n: int = 1) -> None:
    """업로드 성공분을 기록한다(다음 슬롯이 이어서 계산)."""
    from src import quotes
    today = datetime.now(quotes.KST).date().isoformat()
    used, _ = youtube_daily_budget()
    path = DATA / _YT_QUOTA_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps({"date": today, "count": used + n},
                                ensure_ascii=False, indent=1), encoding="utf-8")


def _load_cycle_archive(cycle: str):
    """오늘자(KST) 콘텐츠 아카이브 로드. 없으면 None."""
    from src import quotes

    today = datetime.now(quotes.KST).date().isoformat()
    cands = [DATA / "cards" / today / cycle / "content.json"]
    cands += sorted((DATA / "cards" / today).glob("*/content.json"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    src = next((p for p in cands if p.exists()), None)
    if src is None:
        return None
    archive = _json.loads(src.read_text(encoding="utf-8"))
    return archive["contents"], archive.get("theme"), src


def _prep_shortform(cycle: str, with_clips: bool = True):
    """숏폼 재료(스토리보드·이미지·AI 클립)를 준비 — 전 단계 파일 캐시로 멱등.

    - storyboard.json 이 이미 있으면 재사용(기획 1회 보장, 재실행 시 동일 장면)
    - images 는 캐시된 파일만 재사용(gen_images 내부 처리)
    - with_clips=True 일 때만 AI 클립을 **생성** 시도(느림, ZeroGPU 대기열)
      with_clips=False 면 캐시된 클립만 수집 — 렌더 단계가 절대 대기하지 않게 함
    반환: (contents, theme, board, images, ai_clips, vdir) 또는 None
    """
    from src import quotes, shortform
    from src.error_log import log_error

    loaded = _load_cycle_archive(cycle)
    if loaded is None:
        log_error(DATA, f"shortform:{cycle}", "오늘자 content.json 없음 — 건너뜀")
        print("오늘자 콘텐츠 없음 — 건너뜀")
        return None
    contents, theme, src = loaded
    print(f"콘텐츠 재사용: {src} (테마: {theme})")

    today = datetime.now(quotes.KST).date().isoformat()
    vdir = DATA / "reels" / today / cycle
    sb = vdir / "storyboard.json"
    try:
        if sb.exists():
            board = _json.loads(sb.read_text(encoding="utf-8"))
            print("스토리보드 캐시 재사용 (기획 생략)")
        else:
            # 장면 기획 1회 + 이미지 1세트 (4개 언어 공용)
            board = shortform.plan_scenes(contents, theme=theme)
            sb.parent.mkdir(parents=True, exist_ok=True)
            sb.write_text(_json.dumps(board, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        images = shortform.gen_images(
            board["image_prompts"], vdir / "images",
            seed_base=fablevideo.seed_from_date(today))
    except Exception as e:  # noqa: BLE001
        log_error(DATA, f"shortform:{cycle}", f"storyboard/images: {str(e)[:300]}")
        print(f"스토리보드/이미지 실패: {e}")
        return None

    ai_clips = [None] * len(board["image_prompts"])
    if with_clips:
        # AI 영상 클립(선택 보강, 무료 HF 스페이스) — 1세트를 4개 언어가 공유.
        # 실패하면 장면별로 None 이 들어가고 기존 이미지 켄번스로 자동 폴백된다.
        try:
            ai_clips = shortform.gen_ai_clips(
                board["image_prompts"], vdir / "ai",
                seed_base=fablevideo.seed_from_date(today))
        except Exception as e:  # noqa: BLE001 - AI 클립 실패가 영상 생성을 막으면 안 됨
            print(f"AI 클립 단계 오류 → 이미지 켄번스로 진행: {e}")
    else:
        # 렌더/게시 단계: **캐시된 클립만** 사용 (대기열 절대 대기하지 않음)
        for i in range(len(board["image_prompts"])):
            dest = vdir / "ai" / f"aiclip{i + 1}.mp4"
            if dest.exists() and dest.stat().st_size > 20000:
                ai_clips[i] = dest
    return contents, theme, board, images, ai_clips, vdir


def prep_clips(cycle: str, max_clips: int | None = None) -> None:
    """렌더/게시 없이 숏폼 재료만 미리 생성 (특히 AI 클립 사전 워밍).

    콘텐츠 회차(06/12/18시 KST)와 릴스 회차(08/13/19시) 사이 2시간 공백에
    느린 무료 AI 클립(ZeroGPU 대기열 10~25분/편)을 뽑아둔다. run-shortform 은
    캐시만 읽으므로 이 단계가 실패해도 발행은 켄번스 폴백으로 안전하게 진행.
    """
    if max_clips:
        os.environ["SHORTFORM_AI_CLIPS_MAX"] = str(max_clips)
    else:
        # 사전 생성 단계 기본 3장면(훅+2). 편당 대기열 10~25분 → 30~75분 내외.
        # 실패 장면은 켄번스 폴백이라 과하게 잡아도 발행은 안전.
        os.environ["SHORTFORM_AI_CLIPS_MAX"] = "3"
    prep = _prep_shortform(cycle, with_clips=True)
    if prep is None:
        return
    _, _, board, _, ai_clips, _ = prep
    n = sum(1 for c in ai_clips if c)
    total = len(board["image_prompts"])
    print(f"[prep-clips:{cycle}] AI 클립 {n}/{total} 확보 — 미확보 장면은 켄번스 폴백")


def run_shortform(cycle: str, mock: bool = False) -> None:
    """숏폼(템플릿 합성 영상) 전용 작업 — 하루 3회(08:00 am / 13:00 pm / 19:00 ev).

    직전 사이클(06/12/18시)에서 아카이브된 content.json을 재사용해 캐러셀과
    같은 명언·테마로 영상을 만든다. 해당 사이클이 누락됐으면 오늘자 최신
    content.json으로 폴백한다(절전 등으로 사이클이 늦게 돌았을 때 대비).

    2026-10-03: AI 클립 생성은 본 단계에서 **절대 하지 않는다**(prep-clips
    가 미리 뽑아둔 캐시만 사용) — ZeroGPU 대기열이 릴스 발행을 지연시키는
    사고(40분+ 스톨) 재발 방지. 캐시가 없으면 켄번스로 즉시 렌더.
    """
    from src import quotes, shortform
    from src.error_log import log_error
    from src.publishers.instagram import InstagramPublisher

    print(f"[run-shortform:{cycle}] mock={mock}")
    prep = _prep_shortform(cycle, with_clips=False)
    if prep is None:
        return
    contents, theme, board, images, ai_clips, vdir = prep

    n_ai = sum(1 for c in ai_clips if c)
    total = len(board["image_prompts"])
    if n_ai:
        print(f"AI 클립 {n_ai}/{total} 사용 (prep-clips 사전 생성분)")
    else:
        print("AI 클립 캐시 없음 — 이미지 켄번스로 렌더 (사전 생성: prep-clips)")

    ig = InstagramPublisher()
    yt = _shortform_youtube(cycle)
    if yt is not None:
        print(f"YouTube 업로드: {cycle} 회차에 포함")
    results = []
    for lang, c in contents.items():
        if mock or ig.missing(lang):
            results.append({"status": "dry-run", "detail": "mock mode" if mock
                            else f"missing env: {ig.missing(lang)}"})
            continue
        try:
            mp4 = shortform.make_shortform(
                lang, c, board["scenes"][lang], images, vdir, ai_clips=ai_clips)
            results.append(ig.publish_reel(lang, c["ig_caption"], mp4, ig.credentials(lang)))
            # 같은 mp4 를 YouTube Shorts 로도 업로드 (자격증명 없으면 자동 skip)
            if yt is not None and not yt.missing(lang):
                results.append(
                    yt.publish_reel(lang, c["ig_caption"], mp4, yt.credentials(lang)))
        except Exception as e:  # noqa: BLE001
            results.append({"status": "error", "detail": str(e)[:500]})

    n_pub = sum(1 for r in results if r["status"] == "published")
    n_err = sum(1 for r in results if r["status"] == "error")
    for r in results:
        if r["status"] == "error":
            log_error(DATA, f"shortform:{cycle}", r["detail"])
    print(f"[run-shortform:{cycle}] 완료: published={n_pub} error={n_err} / 총 {len(results)}")


def collect_metrics(mock: bool = False) -> None:
    from src import reporter

    rows = reporter.collect_all(DATA, mock=mock)
    print(f"[collect-metrics] {len(rows)}행 추가 (날짜×언어)")


# ─────────────────────────────────────────────────────────────
# 우화 쇼츠 v6 — 하루 1편 (2026-10-05 재구축)
#   스토리(명언→동물우화 대본) → 이미지(공용) → 4개 언어 렌더 → IG+YT 발행.
#   각 단계는 파일 마커로 멱등: story.json / fable_<lang>.mp4 / published.json
# ─────────────────────────────────────────────────────────────
def fable_story(mock: bool = False, date: str | None = None) -> None:
    """우화 스토리 생성 — 해당 날짜 story.json 이 이미 있으면 스킵(중복 방지)."""
    from src import fable, quotes
    from src.error_log import log_error

    if fable.load_story(DATA, date):
        print(f"[fable-story] {date or '오늘'}자 story.json 이미 있음 — 생성 생략")
        return
    try:
        quote, theme = fable.pick_quote(DATA)
        print(f"[fable-story] 테마: {quotes.THEME_LABELS.get(theme, theme)} (요일 로테이션)")
        print(f"[fable-story] 오늘의 명언: [{quote.id}] {quote.author_of('ko')} — {quote.text_of('ko')}")
        story = fable.generate(quote, theme, mock=mock)
        path = fable.save_story(story, DATA, date=date)
        print(f"[fable-story] 저장: {path} (장면 {len(story['scenes'])}개)")
        if not mock:  # mock 은 로테이션 이력을 더럽히지 않는다 (기존 규칙과 동일)
            quotes.mark_used(DATA, quote.id)
    except Exception as e:  # noqa: BLE001
        log_error(DATA, "fable-story", str(e)[:400])
        raise


def fable_video(lang: str | None = None, mock: bool = False, date: str | None = None) -> None:
    """4개 언어 렌더 — 언어별 mp4 마커로 멱등. 이미지는 1세트 공용 캐시.
    date=None 이면 오늘(KST). 자정 넘긴 보강 렌더는 --date 로 명시."""
    from src import fable, fablevideo
    from src.error_log import log_error

    story = fable.load_story(DATA, date)
    if story is None:
        print("[fable-video] 해당 날짜 story.json 없음 — fable-story 먼저 실행")
        return
    if mock:
        os.environ.setdefault("SHORTFORM_BGM", "on")  # mock 도 BGM 포함(미리듣기용)
    langs = [lang] if lang else fable.LANGS
    for lg in langs:
        sdir = fable.story_dir(DATA, story["date"])
        mp4 = sdir / f"fable_{lg}.mp4"
        if mp4.exists() and mp4.stat().st_size > 100000:
            print(f"[fable-video] {lg} 이미 렌더됨 — 스킵 ({mp4.name})")
            continue
        try:
            out = fablevideo.make_fable(lg, story, DATA)
            print(f"[fable-video] {lg} 완료: {out.name} ({out.stat().st_size // 1024}KB)")
        except Exception as e:  # noqa: BLE001
            import traceback
            log_error(DATA, f"fable-video:{lg}", str(e)[:400])
            print(f"[fable-video] {lg} 렌더 실패: {e}")
            traceback.print_exc()


def fable_publish(date: str | None = None) -> None:
    """IG 릴스 + YouTube 쇼츠 동시 발행 — 언어별 published.json 마커로 멱등."""
    from src import fable
    from src.error_log import log_error
    from src.publishers.instagram import InstagramPublisher

    story = fable.load_story(DATA, date)
    if story is None:
        print("[fable-publish] 해당 날짜 story.json 없음 — fable-story 먼저 실행")
        return
    sdir = fable.story_dir(DATA, story["date"])
    marker = sdir / "published.json"
    done: dict = {}
    if marker.exists():
        try:
            done = _json.loads(marker.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            done = {}

    ig = InstagramPublisher()
    yt = YouTubePublisher()
    for lang in fable.LANGS:
        if lang in done and all(done[lang].get(k) == "published" for k in ("ig", "yt")):
            print(f"[fable-publish] {lang} 이미 발행 완료 — 스킵")
            continue
        mp4 = sdir / f"fable_{lang}.mp4"
        if not (mp4.exists() and mp4.stat().st_size > 100000):
            print(f"[fable-publish] {lang} mp4 없음 — fable-video 먼저")
            continue
        rec = done.get(lang, {})
        caption = story["caption"][lang]
        try:
            if rec.get("ig") != "published" and not ig.missing(lang):
                rec["ig"] = ig.publish_reel(
                    lang, caption, mp4, ig.credentials(lang))["status"]
            elif ig.missing(lang):
                rec["ig"] = "skip(no-creds)"
            # YouTube 업로드 쿼터는 2026-06-01 부터 독립 버킷(하루 100회).
            # 하루 3편 × 4언어 = 12건은 한도 안이므로 사실상 항상 올라간다.
            # 100회짜리 여유는 "만약을 위한" 안전선일 뿐이다.
            used, limit = youtube_daily_budget()
            if rec.get("yt") != "published" and not yt.missing(lang):
                if used >= limit:
                    rec["yt"] = f"skip(quota {used}/{limit})"
                    print(f"[fable-publish] {lang}: YouTube 일일 쿼터 소진 "
                          f"({used}/{limit}) — IG 만 발행")
                else:
                    rec["yt"] = yt.publish_reel(
                        lang, caption, mp4, yt.credentials(lang))["status"]
                    if str(rec["yt"]).startswith("published"):
                        youtube_quota_consume()
            elif yt.missing(lang):
                rec["yt"] = "skip(no-creds)"
            rec["ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            done[lang] = rec
        except Exception as e:  # noqa: BLE001
            log_error(DATA, f"fable-publish:{lang}", str(e)[:400])
            done[lang] = {**rec, "error": str(e)[:200]}
        finally:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(_json.dumps(done, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        print(f"[fable-publish] {lang}: ig={rec.get('ig')} yt={rec.get('yt')}")
    print(f"[fable-publish] 마커: {marker}")


def _run_fable_kind(kind: str, mock: bool = False,
                    no_publish: bool = False,
                    date: str | None = None) -> None:
    """장르별 파이프라인 (stocks / biz) — story 생성 → 렌더 → 발행.

    ⚠️ 폴더 규칙: `fable.story_dir()` 는 `data/fables/<date>` 만 만든다.
    장르별로 날짜 폴더를 분리하려면 story['date'] 에 suffix 를 넣어야
    렌더/발행 경로가 일치한다 (예: '2026-10-17' → '2026-10-17-stocks').
    """
    from src import fable, fablevideo
    from src.error_log import log_error

    today = date or datetime.now().strftime("%Y-%m-%d")
    suffix = f"-{kind}"
    sdate = today if today.endswith(suffix) else f"{today}{suffix}"

    print(f"[run-fable] 장르={kind} 날짜={sdate}")

    # 1) 대본 생성
    story_path = fable.story_dir(DATA, sdate) / "story.json"
    if story_path.exists():
        print(f"[run-fable] story.json 존재 — 생성 생략")
        story = _json.loads(story_path.read_text(encoding="utf-8"))
    elif kind == "stocks":
        from src import stock_story
        story = stock_story.generate(date=sdate, mock=mock)
    elif kind == "biz":
        from src import biz_story
        story = biz_story.generate(date=sdate, mock=mock)
    else:
        print(f"[run-fable] 알 수 없는 kind='{kind}' — 기본 우화로 처리")
        run_fable(mock=mock, no_publish=no_publish, date=date)
        return

    sdir = fable.story_dir(DATA, sdate)
    sdir.mkdir(parents=True, exist_ok=True)
    # ⚠️ 2026-10-11 실측: 여기서 `json.dumps` 로 쓰면 NameError.
    # main.py 는 모듈 상단에서 `import json as _json` 으로 가져온다.
    # 이 한 줄 때문에 08시(stocks)·16시(biz) 슬롯이 story.json 을 못 써서
    # **한 번도 산출되지 않았다** — cron 은 3개인데 실제론 하루 1편만 나갔던 이유.
    story_path.write_text(_json.dumps(story, ensure_ascii=False, indent=1),
                          encoding="utf-8")

    # 2) 렌더 (4개 언어)
    for lg in fable.LANGS:
        mp4 = sdir / f"fable_{lg}.mp4"
        if mp4.exists() and mp4.stat().st_size > 100000:
            print(f"[run-fable] {lg} 이미 렌더됨 — 스킵")
            continue
        try:
            out = fablevideo.make_fable(lg, story, DATA)
            print(f"[run-fable] {lg} 렌더 완료: {out.name}")
        except Exception as e:  # noqa: BLE001
            log_error(DATA, f"fable-video:{kind}:{lg}", str(e)[:400])
            print(f"[run-fable] {lg} 렌더 실패: {e}")

    # ⚠️ 2026-10-12 교훈 (조용한 누락 사고): 렌더가 전멸해도
    # publish 는 "mp4 없음 — 스킵" 만 찍고 exit 0 으로 끝나
    # workflow 가 "success" 로 위장했다 (DeepSeek 402 사고).
    # → 산출 mp4 가 0개면 반드시 죽인다. 실패가 빨간색으로 보여야 한다.
    made = [lg for lg in fable.LANGS
            if (sdir / f"fable_{lg}.mp4").exists()
            and (sdir / f"fable_{lg}.mp4").stat().st_size > 100000]
    if not made:
        raise RuntimeError(
            f"[run-fable] {kind}({sdate}) 렌더 산출 0개 — 파이프라인 실패로 종료 "
            f"(errors.log 와 DeepSeek 잔액 확인)")

    # 3) 발행 — 기존 fable_publish 를 date=sdate 로 재사용한다.
    #    (IG/YT 토큰·중복 방지·크레딧 삽입 로직이 이미 전부 들어 있다)
    if no_publish or mock:
        print("[run-fable] 발행 생략 (no-publish / mock)")
        return
    _guard_quality(story, kind, sdate)
    fable_publish(date=sdate)
    print(f"[run-fable] 장르={kind} 파이프라인 종료")


# ⚠️ 2026-10-14 신설 — 폴백 대본의 품질 하한 게이트.
#
#   DeepSeek 잔액 0 → 무료 폴백(GPT-OSS 20B)으로 대본을 만든다.
#   그 결과물은 **대본 "완성"은 되지만 반 이상이 기본 문장으로 채워진다**
#   (실측: 10장 중 고유 문장 5개).
#   이런 영상을 YT/IG 에 올리면 채널이 "구린 영상"으로 고정된다.
#   추천 알고리즘은 内容 품질보다 일관된 저하를 더 강하게惩罚한다.
#
#   → 완성만으로는 통과시키지 않는다. **实质性**을 본다.
#   → 이건 "0편"보다 나은 선택이다. 실패는 Issue 로 눈에 보인다.
_GUARD_MIN_UNIQUE_RATIO = 0.7   # 10장 중 고유 문장 비율 하한


def _guard_quality(story: dict, kind: str, sdate: str) -> None:
    scenes = story.get("scenes") or []
    if not scenes:
        raise RuntimeError(f"[run-fable] {kind}({sdate}) 대본에 scenes 없음")
    nars = [str((s.get("narration") or {}).get("ko") or "").strip()
            for s in scenes]
    nonempty = [x for x in nars if x]
    uniq = len(set(nonempty))
    ratio = uniq / max(1, len(nonempty))
    repaired = bool(story.get("repaired"))
    print(f"[guard] {kind}: 장면 {len(scenes)} / 고유 문장 {uniq} "
          f"({ratio:.0%}) / repaired={repaired}")

    if ratio < _GUARD_MIN_UNIQUE_RATIO:
        raise RuntimeError(
            f"[run-fable] {kind}({sdate}) 품질 게이트 탈락 — "
            f"고유 문장 {ratio:.0%} (하한 {_GUARD_MIN_UNIQUE_RATIO:.0%}), "
            f"repaired={repaired}\n"
            f"  로그에 '[llm] DeepSeek 402' 가 있으면 platform.deepseek.com 충전.\n"
            f"  그 전까지는 대본이 반 이상 자동 문장으로 채워져 영상 품질이 무너진다.\n"
            f"  **발행하지 않고 멈췄다.** 구린 영상을 올리는 것보다 나쁘다."
        )


def run_fable(mock: bool = False, no_publish: bool = False,
              date: str | None = None, kind: str = "fable") -> None:
    """우화 쇼츠 전체 파이프라인 — 각 단계 마커로 재실행 안전.

    date 를 주면 그날의 우화를 다룬다 (보강 발행용).
    kind (2026-10-10 추가):
      fable  — 명언 기반 우화 (기본값, 기존 동작)
      stocks — 나스닥 시총 TOP 10 의 성공 이유
      biz    — 사업가 마인드
    """
    if kind and kind != "fable":
        _run_fable_kind(kind, mock=mock, no_publish=no_publish, date=date)
        return
    fable_story(mock=mock, date=date)
    fable_video(mock=mock, date=date)
    # ⚠️ 2026-10-12: 렌더 전멸 시 위장 성공 방지 (kind 경로와 동일한 가드).
    # fable_video 는 언어별 예외를 삼키므로, 여기서 산출 여부를 확인한다.
    _sdir = fable.story_dir(DATA, date)
    _made = [p.name for p in _sdir.glob("fable_*.mp4") if p.stat().st_size > 100000]
    if not _made:
        raise RuntimeError(
            f"[run-fable] fable({_sdir.name}) 렌더 산출 0개 — 파이프라인 실패로 종료 "
            f"(errors.log 와 DeepSeek 잔액 확인)")
    if not no_publish and not mock:
        _guard_quality(story, "fable", date or "today")
        fable_publish(date=date)
    elif mock:
        print("[run-fable] mock 모드 — 발행 생략 (mock 금지 규칙)")


SLOTS = ["fable", "stocks", "biz"]   # KST 00:07 / 08:07 / 16:07

SLOT_LABEL = {"fable": "명언 우화 (00:07)",
              "stocks": "나스닥 TOP10 (08:07)",
              "biz": "사업가 마인드 (16:07)"}


def run_three(mock: bool = False, no_publish: bool = False,
              date: str | None = None, skip: set[str] | None = None) -> dict:
    """하루 3편 일괄 제작 — 2026-10-11 추가.

    왜 필요한가: 슬롯별로 따로 실행하면 3편 중 하나가 조용히 실패해도
    눈치채기 어렵다. 실제로 16시 biz 편이 한 번도 산출되지 않은 채
    며칠이 지나갔다(실측). → 묶어서 돌리고 결과를 한눈에 보고한다.

    ⚠️ 한 편이 실패해도 나머지는 계속된다 (목표는 하루 3편 완주).
    """
    skip = skip or set()
    today = date or datetime.now().strftime("%Y-%m-%d")
    from src.error_log import log_error        # 함수 내 import — 모듈 상단 오염 방지
    report: dict[str, str] = {}

    for kind in SLOTS:
        if kind in skip:
            report[kind] = "SKIP"
            continue
        print(f"\n{'='*56}\n▶ {SLOT_LABEL.get(kind, kind)}\n{'='*56}")
        try:
            run_fable(mock=mock, no_publish=no_publish, date=today, kind=kind)
            report[kind] = "OK"
        except Exception as e:  # noqa: BLE001
            log_error(DATA, f"run-three:{kind}", str(e)[:400])
            report[kind] = f"FAIL: {str(e)[:120]}"
            print(f"[run-three] {kind} 실패: {e}")

    print(f"\n{'='*56}\n[run-three] 결과 ({today})\n{'='*56}")
    for kind in SLOTS:
        print(f"  {SLOT_LABEL.get(kind, kind):<26} : {report.get(kind, '-')}")
    return report


def _auto_cycle() -> str:
    h = datetime.now().hour
    if h < 12:
        return "am"
    if h < 18:
        return "pm"
    if h < 23:
        return "ev"
    return "night"


def main() -> None:
    ap = argparse.ArgumentParser(prog="sns-automation")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_cycle = sub.add_parser("run-cycle")
    p_cycle.add_argument("--cycle", choices=["am", "pm", "ev", "night", "auto"], default="auto")
    p_cycle.add_argument("--mock", action="store_true")

    p_metrics = sub.add_parser("collect-metrics")
    p_metrics.add_argument("--mock", action="store_true")

    p_sf = sub.add_parser("run-shortform")
    p_sf.add_argument("--cycle", choices=["am", "pm", "ev"], default="ev")
    p_sf.add_argument("--mock", action="store_true")

    p_prep = sub.add_parser("prep-clips")
    p_prep.add_argument("--cycle", choices=["am", "pm", "ev"], required=True)
    p_prep.add_argument("--max", type=int, default=None,
                        help="AI 클립 최대 장면 수 (기본 5=전 장면)")

    p_fstory = sub.add_parser("fable-story", help="우화 스토리 생성 (story.json)")
    p_fstory.add_argument("--mock", action="store_true")

    p_fvideo = sub.add_parser("fable-video", help="우화 쇼츠 렌더 (4개 언어)")
    p_fvideo.add_argument("--lang", choices=["ko", "en", "zh-cn", "fr"], default=None)
    p_fvideo.add_argument("--mock", action="store_true")
    p_fvideo.add_argument("--date", default=None, help="스토리 날짜(YYYY-MM-DD) — 자정 넘긴 보강 렌더용")

    p_fpub = sub.add_parser("fable-publish", help="우화 쇼츠 IG+YT 발행")
    p_fpub.add_argument("--date", default=None, help="스토리 날짜(YYYY-MM-DD) — 미발행 복구용")

    p_fable = sub.add_parser("run-fable", help="우화 쇼츠 전체 파이프라인")
    p_fable.add_argument("--mock", action="store_true")
    p_fable.add_argument("--no-publish", action="store_true")
    p_fable.add_argument("--date", default=None,
                         help="스토리 날짜(YYYY-MM-DD) — 기본은 오늘(KST)")
    p_fable.add_argument("--kind", default="fable",
                         choices=["fable", "stocks", "biz"],
                         help="fable=명언우화 / stocks=나스닥TOP10 / biz=사업가마인드")

    # 2026-10-11 추가 — 하루 3편을 한 번에. 우리 목표는 "하루 3편 × 4개 언어"다.
    # 슬롯별로 따로 실행하면 어느 한 편이 조용히 빠지는 걸 눈치채기 어렵다.
    p_three = sub.add_parser("run-three", help="하루 3편 일괄 제작 (명언/증권/사업가)")
    p_three.add_argument("--mock", action="store_true")
    p_three.add_argument("--no-publish", action="store_true")
    p_three.add_argument("--date", default=None, help="스토리 날짜(YYYY-MM-DD)")
    p_three.add_argument("--skip", default="",
                         help="제외할 장르 (쉼표 구분). 예: --skip stocks,biz")

    sub.add_parser("schedule")
    args = ap.parse_args()

    if args.cmd == "run-cycle":
        cycle = _auto_cycle() if args.cycle == "auto" else args.cycle
        run_cycle(cycle, mock=args.mock)
    elif args.cmd == "run-shortform":
        run_shortform(args.cycle, mock=args.mock)
    elif args.cmd == "prep-clips":
        prep_clips(args.cycle, max_clips=args.max)
    elif args.cmd == "collect-metrics":
        collect_metrics(mock=args.mock)
    elif args.cmd == "fable-story":
        fable_story(mock=args.mock)
    elif args.cmd == "fable-video":
        fable_video(lang=args.lang, mock=args.mock, date=args.date)
    elif args.cmd == "fable-publish":
        fable_publish(date=args.date)
    elif args.cmd == "run-fable":
        run_fable(mock=args.mock, no_publish=args.no_publish,
                  date=args.date, kind=args.kind)
    elif args.cmd == "run-three":
        skip = {s.strip() for s in (args.skip or "").split(",") if s.strip()}
        run_three(mock=args.mock, no_publish=args.no_publish,
                  date=args.date, skip=skip)
    elif args.cmd == "schedule":
        from src import scheduler
        scheduler.start(lambda c: run_cycle(c), lambda: collect_metrics(),
                        lambda c: run_shortform(c))


if __name__ == "__main__":
    main()
