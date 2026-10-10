"""사업가 마인드 편 대본 생성 — 성공하는 사람의 마인드/전략/실패공학.

2026-10-10 신설. 하루 3편 구조의 16:07 슬롯용.
외부 데이터 불필요 — LLM 대본만 생성한다.
"""
from __future__ import annotations

import os
import random
import re

import requests

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
LANGS = ["en", "ko", "zh-cn", "fr"]

STYLE = ("black and white pencil drawing, monochrome, graphite sketch, "
         "hand-drawn line art, no color, no border, no frame, no text")

# 주제 로테이션 — 같은 편이 반복되지 않게 요일로 바꾼다.
# 4개 축을 돌며 variety 를 만든다.
THEMES = [
    ("risk",    "불확실성을 다루는 법", [
        "small bet, big learning",
        "loss is information",
        "optionality as strategy"]),
    ("speed",   "속도와 실행", [
        "ship before perfect",
        "momentum beats accuracy",
        "decide fast, correct later"]),
    ("focus",   "집중 전략", [
        "say no to almost everything",
        "one thing, done extremely well",
        "subtraction over addition"]),
    ("failure", "실패를 다루는 법", [
        "the first ten attempts are tuition",
        "post-mortem without blame",
        "kill the project, keep the lesson"]),
]

THEME_KEYS = [t[0] for t in THEMES]

# act 구성 — 마인드 편에 맞는 흐름
ACTS = [
    ("hook",    "가장 흔한 오류를 단정한다"),
    ("truth",   "실제 성공한 사람들의 공통점을 말한다"),
    ("why",     "왜 그렇게 됐는지 이유를 든다"),
    ("method",  "구체적으로 어떻게 하는지"),
    ("example", "짧은 사례 또는 비유"),
    ("risk",    "이 방법을 쓰면 뭐가 위험한지"),
    ("mindset", "마인드 전환 문장"),
    ("practice","오늘 당장 할 수 있는 것"),
    ("act",     "행동을 지시한다"),
]


def _theme_for(date: str, rng: random.Random | None = None) -> dict:
    """날짜로 테마를 고정(같은 날짜면 항상 같은 주제) — 재생성해도 흔들리지 않게."""
    import datetime
    try:
        d = datetime.date.fromisoformat(date[:10])
        idx = d.toordinal() % len(THEMES)
    except Exception:  # noqa: BLE001
        idx = (rng or random.Random()).randrange(len(THEMES))
    key, label, angles = THEMES[idx]
    return {"key": key, "label": label,
            "angle": angles[(idx + 1) % len(angles)]}


def build_prompt(theme: dict, seed_note: str = "") -> list[dict]:
    schema = """
반드시 아래 JSON 형식으로만 답하라. 설명문·코드블록 없이 JSON 만.

{
  "title": {"ko":"...","en":"...","zh-cn":"...","fr":"..."},
  "caption": {"ko":"...","en":"...","zh-cn":"...","fr":"..."},
  "hook": {
    "lines": {"ko":["한 문장","한 문장"],"en":[...],"zh-cn":[...],"fr":[...]},
    "highlight": {"ko":"강조 단어","en":"...","zh-cn":"...","fr":"..."}
  },
  "moral": {"ko":"...","en":"...","zh-cn":"...","fr":"..."},
  "cta": {"ko":"...","en":"...","zh-cn":"...","fr":"..."},
  "scenes": [
    {"act":"hook",
     "subtitle":{"ko":"...","en":"...","zh-cn":"...","fr":"..."},
     "narration":{"ko":"...","en":"...","zh-cn":"...","fr":"..."}},
    ... 총 9개
  ]
}
"""
    rules = """
[작성 규칙 — 반드시 지킬 것]
1. **4개 언어(ko/en/zh-cn/fr) 모두 작성.** 각 언어의 자연스러운 문장으로.
2. **한국어는 해라체·구어체.** "~한다/~했다/~이다" 로 끝나라.
   존댓말('~하세요', '~합니다')은 금지 — 쓰면 실패다.
3. 구어체. "~입니다" 금지. **"~해라" 직접 지시는 쓰지 마라.**
  moral 은 반지·단정으로 끝낸다. 예: "집중은 버리는 게 아니라 고르는 일이다."
4. 각 장면 narration 은 2~3문장, 60~100자 내외.
5. **구독 유도 금지.** 구체적 행동 지시만.
6. **구체적인 기업·사람 이름 금지.** 일반화한 논리로 써라.
   (실제 성공자를 특정하면 검증 없이 사실을 말하는 것처럼 보인다)
7. 숫자는 반올림해도 무방하나 없는 통계를 만들지 마라.
8. hook 은 짧고 강한 2문장. 첫 문장이 시선을 잡아야 한다.
9. moral 은 구사절. 행동 지시형으로 끝맺어라.
10. 톤: 담담하고 단정적으로. excitement 이 아니라 conviction.
"""
    user = (
        f"주제: **{theme['label']}**\n"
        f"핵심 각도: {theme['angle']}\n"
        f"{seed_note}\n"
        f"{rules}\n"
        f"장면 구성(순서 고정):\n"
        + "\n".join(f"  {i+1}. act='{a}' — {d}" for i, (a, d) in enumerate(ACTS))
        + f"\n\n{schema}"
    )
    return [{"role": "system",
             "content": "당신은 성공하는 사업가들의 마인드를 다뤄 쓰는 쇼츠 대본 작가다."},
            {"role": "user", "content": user}]


def _extract_json(text: str) -> dict:
    import json
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        pass
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        return json.loads(t[i:j + 1])
    raise ValueError("JSON 파싱 실패")


def generate(date: str, mock: bool = False,
             seed: int | None = None) -> dict:
    """사업가 마인드 편 대본 생성 → story.json 구조."""
    rng = random.Random(seed) if seed is not None else random.Random()
    theme = _theme_for(date, rng)

    if mock or not os.getenv("DEEPSEEK_API_KEY"):
        data = _mock(theme)
    else:
        r = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}"},
            json={"model": MODEL, "max_tokens": 16000,
                  "messages": build_prompt(theme),
                  "response_format": {"type": "json_object"}},
            timeout=300)
        r.raise_for_status()
        data = _extract_json(r.json()["choices"][0]["message"]["content"])

    data["date"] = date
    data["theme"] = "biz"
    data["theme_label"] = theme["label"]
    data["quote"] = {"text": theme["angle"], "author": "성공하는 사람의 마인드"}
    data["characters"] = "사업가 마인드"
    for sc in data.get("scenes", []):
        if not sc.get("image_prompt"):
            sc["image_prompt"] = (
                f"{STYLE}, {ACT_IMAGE_HINT.get(sc.get('act'), 'old workshop tools')}")
    data["naturalness_issues"] = []
    return data


# act 별 검색 키워드 (실사 사진 검색용 안전망)
ACT_IMAGE_HINT = {
    "hook":    "business person silhouette office window",
    "truth":   "handshake business partnership",
    "why":     "chess board strategy close up",
    "method":  "notebook planning desk workspace",
    "example": "mountain road fork path choice",
    "risk":    "stormy sky lightning field",
    "mindset": "person looking out window horizon",
    "practice":"small plant growing through stone",
    "act":     "footpath stepping stones forward",
}


def _mock(theme: dict) -> dict:
    out = {
        "title": {k: theme["label"] for k in LANGS},
        "caption": {k: theme["angle"] for k in LANGS},
        "hook": {"lines": {k: [theme["angle"], "Look closer."] for k in LANGS},
                 "highlight": {k: theme["angle"][:12] for k in LANGS}},
        "moral": {k: "Act on it today." for k in LANGS},
        "cta": {k: "Follow for more." for k in LANGS},
        "scenes": [],
    }
    for act, _ in ACTS:
        out["scenes"].append({
            "act": act,
            "subtitle": {k: theme["label"] for k in LANGS},
            "narration": {k: f"{theme['label']} scene." for k in LANGS},
            "image_prompt": f"{STYLE}, {ACT_IMAGE_HINT.get(act, 'workshop')}",
        })
    return out


if __name__ == "__main__":
    import json
    import sys
    d = generate(date="2026-10-17", mock="--mock" in sys.argv)
    print(json.dumps({"theme": d["theme_label"], "title": d["title"]["ko"],
                      "hook": d["hook"]["lines"]["ko"],
                      "moral": d["moral"]["ko"]},
                     ensure_ascii=False, indent=2))