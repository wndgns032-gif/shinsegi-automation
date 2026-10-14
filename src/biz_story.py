"""사업가 마인드 편 — 16:07 슬롯.

2026-10-11 전면 재작성.
이전 버전은 프롬프트를 파일 안에 따로 들고 있어서 참고 채널 규칙이
전혀 적용되지 않았다. 실측 결과 1장면이 86자 설교체로 나왔다:

    "대부분은 준비가 부족해서 시작하지 못한다고 믿는다. 실제로는 결정을
     미루는 습관이 발목을 잡는다. 완벽한 타이밍을 기다리는 동안 판은
     이미 바뀐다."

→ 이제 **규칙은 story_core 가 전부 갖고 있고, 여긴 소재만 공급한다.**
"""
from __future__ import annotations

import datetime
import random

from src import story_core

LANGS = story_core.LANGS

SYSTEM = ("당신은 성공하는 사람들의 마인드를 다뤄 쓰는 쇼츠 대본 작가다. "
          "설교하지 않고, 관찰한 장면을 짧게 던진다.")

# 주제 로테이션 — 날짜로 고정 (같은 날 재생성해도 흔들리지 않게)
THEMES = [
    ("risk", "불확실성을 다루는 법", [
        "small bet, big learning",
        "loss is information",
        "optionality as strategy"]),
    ("speed", "속도와 실행", [
        "ship before perfect",
        "momentum beats accuracy",
        "decide fast, correct later"]),
    ("focus", "집중 전략", [
        "say no to almost everything",
        "one thing, done extremely well",
        "subtraction over addition"]),
    ("failure", "실패를 다루는 법", [
        "the first ten attempts are tuition",
        "post-mortem without blame",
        "kill the project, keep the lesson"]),
    ("compound", "시간이 만드는 차이", [
        "the boring thing done daily",
        "reputation compounds quietly",
        "skill is an accumulation, not an event"]),
    ("price", "대가를 치르는 법", [
        "everything has a hidden price",
        "what you refuse to give up",
        "comfort is expensive"]),
]


def _theme_for(date: str, rng: random.Random | None = None) -> dict:
    try:
        d = datetime.date.fromisoformat(date[:10])
        idx = d.toordinal() % len(THEMES)
    except Exception:  # noqa: BLE001
        idx = (rng or random.Random()).randrange(len(THEMES))
    key, label, angles = THEMES[idx]
    return {"key": key, "label": label,
            "angle": angles[(idx + 1) % len(angles)]}


def generate(date: str, mock: bool = False,
             seed: int | None = None) -> dict:
    """사업가 마인드 편 대본 생성 → story.json 구조."""
    import os
    rng = random.Random(seed) if seed is not None else random.Random()
    theme = _theme_for(date, rng)

    # ⚠️ 2026-10-14 수정 — `not os.getenv(KEY)` 는 **조용한 목업 반환**이었다.
    #   키가 사라지면 10장 전부가 같은 한 줄("집중 전략.")인 대본이 만들어지고,
    #   그것이 정상처럼 파이프라인을 끝까지 흘러 영상을 찍는다.
    #   → 명시적 mock 인 경우에만 목업. 그 외에는 아래 폴백 체인이 붙는다.
    if mock:
        return _mock(theme, date)

    topic = (
        f"# 오늘의 주제: {theme['label']}\n"
        f"핵심 각도: {theme['angle']}\n\n"
        "사업가·창업가의 마인드를 다루지만 **교훈을 설교하지 마라.**\n"
        "추상적 조언('준비가 중요하다')이 아니라 **구체적인 장면 하나**를 "
        "보여주고, 화자는 그 장면을 관찰한 사람이다.\n"
        "특정 기업이나 실존 인물의 이름은 쓰지 마라."
    )

    data = story_core.generate(SYSTEM, topic, verbose=True)

    data["date"] = date
    data["theme"] = "biz"
    data["theme_label"] = theme["label"]
    data["quote"] = {"text": theme["angle"], "author": "성공하는 사람의 마인드"}
    return data


def _mock(theme: dict, date: str) -> dict:
    """API 키 없을 때 최소 형태 — 렌더가 죽지 않게만 한다."""
    core = story_core.SCENE_PLAN
    scenes = []
    for act, _ in core:
        scenes.append({
            "act": act,
            "subtitle": {k: theme["label"] for k in LANGS},
            "narration": {k: f"{theme['label']}." for k in LANGS},
            "image_prompt": story_core._image_prompt("", act),
        })
    return {
        "title": {k: theme["label"] for k in LANGS},
        "caption": {k: theme["angle"] for k in LANGS},
        "hook": {"lines": {k: [theme["angle"], "Look closer."] for k in LANGS},
                 "highlight": {k: theme["angle"][:12] for k in LANGS}},
        "moral": {k: "Act on it today." for k in LANGS},
        "cta": {k: "Follow for more." for k in LANGS},
        "scenes": scenes,
        "date": date, "theme": "biz", "theme_label": theme["label"],
        "quote": {"text": theme["angle"], "author": "성공하는 사람의 마인드"},
        "naturalness_issues": ["mock"],
    }


if __name__ == "__main__":
    import json
    import sys
    d = generate(date=sys.argv[1] if len(sys.argv) > 1 else "2026-10-17",
                 mock="--mock" in sys.argv)
    print(json.dumps({"theme": d["theme_label"],
                      "issues": d.get("naturalness_issues"),
                      "hook": d["hook"]["lines"]["ko"],
                      "moral": d["moral"]["ko"]},
                     ensure_ascii=False, indent=2))
