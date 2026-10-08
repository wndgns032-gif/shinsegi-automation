"""우화(fable) 스토리 생성기 — 명언 하나를 동물 우화 숏폼 대본으로 바꾼다.

2026-10-05 v6 파이프라인 (사용자 지시: 동영상 전면 리셋, 쇼츠 위주 재구축).
참고 영상(youtube.com/shorts/V2UtKas1xAA) 구조 분석 결과:
    상단 고정 훅 바(검정 바, 흰 글씨 + 주황 강조어)
    → 동물 우화 본편 (0~40s)
    → 실생활 전환 (40~65s)
    → 마무리 명언 + CTA
  71초 / 9:16 세로 / BGM 은 끊기지 않고 낭독이 그 위에 얹힌다.

하루 1편, 매일 다른 주제 — 테마는 요일 로테이션(월=성장, 화=용기, ...).
재료는 기존 명언 은행(config/quotes.yaml)을 그대로 쓰고 사용 이력
(quotes_used.json)도 공유한다 → 카드 파이프라인과 중복 선정 방지.

출력(data/fables/<오늘>/story.json)은 fablevideo 렌더러가 소비한다.
"""
from __future__ import annotations

import json
import os
import random
import re
from datetime import datetime
from pathlib import Path

import requests

from . import quotes
from .generator import load_handles

# 우화 쇼츠 전용 해시태그 — 언어별 5개 고정 (로이 확정 2026-10-05)
# 카드 파이프라인의 DEFAULT_TAGS(3개)와 별개. AI가 섞어 넣어도 항상 이 5개로 통일.
FABLE_TAGS = {
    "ko": "#명언 #오늘의명언 #우화 #위로 #동기부여",
    "en": "#fable #quotes #quoteoftheday #wisdom #motivation",
    "zh-cn": "#名言 #寓言 #治愈 #正能量 #每日一句",
    "fr": "#citation #fable #sagesse #proverbe #motivation",
}
from .quotes import Quote, THEME_LABELS

LANGS = ["en", "ko", "zh-cn", "fr"]
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

ROOT = Path(__file__).resolve().parent.parent

# 장면 구조 — 명언 오프닝 1 + 훅 1 + 우화 5 + 현실 2 + 아웃트로(교훈+CTA) 1 = 10장면
# (2026-10-04 로이 피드백: "실제 명인이 말한 내용로 시작" — 명언을 영상 첫 장면에)
SCENE_ACTS = ["quote", "hook", "fable", "fable", "fable", "fable", "fable", "real", "real", "outro"]

# 하루 1편이라 사이클 대신 **요일**로 테마를 정한다 (월~목 로테이션)
THEMES_BY_WEEKDAY = ["growth", "courage", "hardship", "attitude"]

# 이미지 프롬프트 일관성 — 모든 장면에 공통으로 들어가는 스타일 토큰.
# (2026-10-07 로이 지시: "이미지가 통일적이지 않다, 흑백 느낌으로 통일")
# 상세 규칙 = config/prompts/fable_style.md
# 주의: 여기서 "색 지정" 단어(golden light 등)는 절대 넣지 않는다 — 결과가 그림마다 갈라진다.
# 이미지 프롬프트 일관성 — 모든 장면에 공통으로 들어가는 스타일 토큰.
# (2026-10-07 로이 지시: "이미지가 통일적이지 않다, 흑백 느낌으로 통일")
# 상세 규칙 = config/prompts/fable_style.md
#
# ⚠️ 두 가지 실측 함정 (이 주석을 지우지 말 것):
#
# 1) **프롬프트가 길어지면 flux 가 장면 내용을 희생한다.**
#    스타일 설명을 길게 쓰면 실제 장면 대신 추상 패턴·기하학이 나온다
#    (실측: "거북이" → 등껍질 무늬만 / "바위 벽을 오르는 두더지" → 타원만).
#    → 스타일 토큰은 **짧게** 유지한다. 흑백 통일은 프롬프트가 아니라
#      **후처리(fablevideo._to_monochrome)** 가 확실히 보장한다.
#
# 2) **characters 를 앞에 넣으면 클로즈업에 고정돼 장면이 사라진다.**
#    실측: "바위 벽을 오르는 두더지" → 바위만 꽉 찬 화면.
#    → 조립 순서는 반드시 STYLE_PREFIX + **장면 묘사 먼저** + characters 뒤.
#      (아래 `_validate()` 의 이미지 프롬프트 조립부 참고)
STYLE_PREFIX = ("black and white pencil drawing, monochrome, graphite sketch, "
                "hand-drawn line art, no color, no border, no frame, no text")
STYLE_SUFFIX = ("monochrome, grayscale, no color, no frame, no border, no text, "
                "no watermark, simple background, subject clearly visible, "
                "full-bleed scene, edge to edge")

# 주인공 동물을 넣지 않는 장면 — 현실 대입(real)은 사람이 중심이다.
# (2026-10-07: 예전엔 real 에도 거북이가 삽입돼 "회사원 + 거북이" 화면이 나왔음)
NO_CHARACTER_ACTS = {"real"}

# 화면에 크게 띄우는 CTA (아웃트로 하단, 주황색). 언어별 문구.
CTA_TEXTS = {
    "en": "Follow @{h} — a new story every day",
    "ko": "매일 새로운 이야기 @{h}",
    "zh-cn": "每天一个新故事 @{h}",
    "fr": "Une nouvelle histoire chaque jour @{h}",
}


# ─────────────────────────────────────────────────────────────
# 재료 선정
# ─────────────────────────────────────────────────────────────
def pick_quote(data_dir: Path) -> tuple[Quote, str]:
    """오늘의 테마(요일 로테이션)에 맞는 명언 1개. 이력은 카드 파이프라인과 공유."""
    theme = THEMES_BY_WEEKDAY[datetime.now(quotes.KST).weekday() % 4]
    return quotes.pick(theme, data_dir=data_dir), theme


def story_dir(data_dir: Path, date: str | None = None) -> Path:
    d = date or datetime.now(quotes.KST).date().isoformat()
    return data_dir / "fables" / d


def load_story(data_dir: Path, date: str | None = None) -> dict | None:
    p = story_dir(data_dir, date) / "story.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────
# DeepSeek 호출
# ─────────────────────────────────────────────────────────────
def _build_messages(quote: Quote, theme: str, feedback: list[str] | None = None) -> list[dict]:
    quote_block = "\n".join(
        f"- {l}: {quote.text_of(l)} ({quote.author_of(l)})" for l in LANGS)
    voice = _load_voice_rules()
    # 직전 시도에서 검출된 문제 — 다음 시도에서 교정하도록 명시적으로 feedback
    fb = ""
    if feedback:
        items = "\n".join(f"- {f}" for f in feedback)
        fb = ("## ⚠️ 직전 시도에서 아래 문제가 검출됨 — 반드시 고쳐서 다시 써라\n"
              f"{items}\n"
              "같은 실수를 반복하지 말고, 해당 언어로 **원어민이 실제로 쓰는 표현**으로 "
              "처음부터 다시 작성하라. 특히 '번역한 티'가 나는 문장은 통째로 삭제하고 새로 써라.\n\n")
    system = (
        "당신은 자기계발 우화 숏츠 채널의 작가다. "
        "동물 우화로 인생의 교훈을 전달하고, 마지막에 명언으로 마무리하는 "
        "60~75초 세로 영상 대본을 쓴다. "
        "가장 중요한 것: **각 언어의 narration/subtitle 은 그 언어 원어민이 실제로 입으로 "
        "말하는 문장이어야 한다. 문법이 맞아도 원어민이 쓰지 않는 표현이면 실패다.** "
        "다른 언어에서 통역한 흔적이 있으면 반드시 처음부터 다시 써라."
    )
    user = f"""## 오늘의 명언 (이 교훈을 우화로 풀 것)
{quote_block}

테마: {THEME_LABELS.get(theme, theme)}

## 구조 (총 10장면 — 명언이 영상을 연다)
1장면 quote: 명언 원문을 화면 가운데 크게 보여주며 낭독. (낭독은 시스템이 명언 원문으로 자동 교체 — image_prompt만 작성: 명언의 분위기를 상징하는 고요한 장면, 주인공 동물 등장 가능)
2장면 hook: **명령형 2줄 — 시청자에게 직접 지시한다.**
  - 첫 줄은 반드시 **명령형(~하라 / ~해라 / ~하세요)** 으로 시작한다. 질문 금지.
  - 두 번째 줄은 **지금 당장 무엇을 할지** 구체적인 행동을 지시한다.
  - "바쁘면 좋겠어" 같은 관찰이 아니라 "~하라" 로 끝나야 한다.
  - **각 줄은 그 자체로 완전한 문장**이어야 한다 (끝에 마침표를 찍어라).
  (예: "시간을 아끼지 마라. 지금 당장 폰을 집어 들고 밖으로 나가라.")
3~7장면 fable: 주인공 동물이 목표를 갖고 → 실패와 시행착오 → 다른 동물의 조언이나 사건 → 깨달음. 이 5장은 **하나의 연속된 이야기**다. 시간대(아침→저녁)와 카메라 각도는 5장 안에서 고정하고, 주인공의 위치와 감정만 변하게 한다.
8~9장면 real: 우화의 교훈을 현대인의 일상(출근, 공부, 관계, 새벽 루틴, 포기하고 싶은 순간)에 대입. 여기서 주인공은 **사람**이다 (동물 캐릭터는 쓰지 않는다).
  - **8장면은 '성공한 사람'의 실제 사례**로 시작한다. 구체적으로 서술하라.
  - **9장면은 '당신이 지금 할 일'** — 여기서도 명령형(~해라) 으로 끝낸다.
10장면 outro: **명령형 한 문장.** (낭독은 시스템이 moral로 자동 교체 — image_prompt만 작성)
  - 교훈을 "배우면 됩니다" 로 끝내지 말고 **"~해라" / "~하라"** 로 끝낸다.
  - 이 한 문장이 시청자가 그대로 따라 할 행동 지시가 되어야 한다.

## 🔥 톤 — 반드시 지시형으로
이 영상은 **설명하는 것이 아니라 지시하는 짧편**이다.

- **시청자를 '당신'으로 불러라.** "사람들은" "누군가" 같은 3인칭 금지.
  → "~해라" 로 직접 명령한다.
- **명령형(~하라 / ~해라 / ~하세요) 을 최소 3회.** 2장면·9장면·10장면.
- **모호한 동사 금지.** "정리해라" "노력해라" 처럼 애매하면 실패다.
  → "하루 중 한 시간을 그 일에 몰아라" 처럼 **구체적으로 무엇을** 명시하라.
- **성공 사례를 넣어라.** 8장면에서 실제로 그렇게 한 사람을 서술하면
  시청자가 "나도 할 수 있겠다" 는 느낌을 갖는다.

## ❌ 금지 표현
- "배우면 좋습니다" / "알아두면 유용합니다" — 교훈 상담식
- "어쩌면" / "아마" — 흐리게 만드는 표현
- "여러분" / "우리 모두" — 시청자와 거리를 두는 표현
- 질문으로 끝나는 문장 — 질문은 답을 주지 않으므로 행동을 만들지 못한다

## ✅ 좋은 예시
**한국어**
- 2장면: "미루지 마라. 지금 당장 손을 펴서 첫 줄을 써라."
- 2장면: "하루를 버리지 마라. 지금 서서 5분만 걸어라."
- 8장면: "그 여자는 매일 아침 6시에 일어났다. 3년 동안 한 번도 안 틀렸어."
- 9장면: "당신도 오늘 밤에 그 시간을 비워라."
- 10장면: "오늘 당장 시작해라."

**English** (반드시 이 형태를 따를 것)
- 2장면: "Stop copying others. Write down what you actually want right now."
- 8장면: "She woke at 6 every morning. Three years, not one missed day."
- 9장면: "Block one hour for yourself tonight."
- 10장면: "Start today."
- ⚠️ "Your time is yours." 같은 **서술형**으로 끝내면 안 된다.
  반드시 "Start / Write / Block / Quit" 같은 **동사 시작**으로 끝낸다.

**中文** (반드시 이 형태를 따를 것)
- 2장면: "别再模仿别人了。现在就写下你真正想要的。"
- 10장면: "今天就开始。"

**Français** (반드시 이 형태를 따를 것)
- 2장면: "Arrête de copier les autres. Écris ce que tu veux vraiment."
- 10장면: "Commence aujourd'hui."

## 주인공
동물 1마리를 창의적으로 정하고 `characters`에 영어 외형 묘사를 한 줄로 쓴다.
**형식: "<종명>, <분류>, <신체 특징1>, <신체 특징2>, <신체 특징3>"** (최대 6개 단어)
  ✅ "a mole, a small subterranean mammal, pointed snout, long whiskers, tiny eyes, wide paws"
  ✅ "a tortoise, a slow shelled reptile, wrinkled neck, cracked shell, thick legs"
  ❌ "about the size of a teacup"  ← 비교 대상(찻잔 등)을 쓰면 모델이 그 물체를 그린다
이 묘사는 우화 장면의 이미지 프롬프트에 자동 삽입되므로 장면 묘사에 반복할 필요 없다.

⚠️ 실측으로 확인된 flux 규칙 (2026-10-07, 5차례 시행):
1. **분류어**(subterranean mammal / shelled reptile)가 종을 확실히 고정한다.
   종명만 ("a mole") 은 고양이/여우로 새는 경우가 있다.
2. **신체 특징은 3~5개가 한계.** 그 이상(코 방석·귀 없음 등) 쓰면 잡음이 되어
   오히려 토끼/여우처럼 그린다. 간결하게 유지한다.
3. **의류·안장 금지** — "with round glasses" 를 넣으면 **사람(여성)** 이 나온다.
4. **부정 표현 금지** — "not a cat" 를 넣으면 **고양이** 가 나온다.
   flux 는 'not X' 를 'X' 로 읽는 경향이 있다. 긍정형 묘사만 쓸 것.
5. **얼굴이 종을 결정한다** — 몸(털·크기)이 맞아도 얼굴이 여우면 여우로 보인다.
   얼굴 특징이 헷갈리지 않을 종을 고른다
   (예: 두더지=긴 주둥이·작은 눈 / 토끼=긴 귀 / 거북이=딱딱한 껍질).

→ flux(stable) 로는 100% 종 고정 불가. 위 규칙으로 "대부분이 같은 동물" 수준까지 확보하고,
   종이 흔들리는 장면은 자동 검수 재생성으로 걸러낸다.

## 규칙
- narration: 각 언어당 1~2문장, 낭독 6~8초 분량. **나레이션은 3인칭 기록체로 쓰지 않는다.**
- **narration 도 지시형으로 쓴다.** 2·9·10장면은 반드시 명령형(~해라/~하라)으로 끝난다.
  관찰이나 설명으로 끝내지 않는다.
  (예: "시간을 아끼지 마라. 지금 당장 폰을 집어 들고 나가라.")
  3인칭 서술("The turtle got up again")은 유튜브 요약 채널처럼 들린다. 2인칭("누구/당신/you/tu/你")
  을 Throw in 하거나, 동작만 던지고 감정은 뉘앙스로 남긴다. 단 real·outro 장면은 반드시 2인칭으로 끝낸다.
- subtitle: 화면 하단 자막. ko/zh-cn 16자 이내, en/fr 42자 이내. 조사를 붙이지 않는다(명사형).
- image_prompt: **영문. 주격 명사구(fragment)로 쓴다** — 완전한 서술문("Morning light. The mole
  stands...")이나 문장으로 쓰면 flux 가 개념을 못 잡고 추상 형태를 그린다(실측 사례).
  **"누가 + 무엇을 + 하는 장면"** 을 명사구로 압축하고, 서술/서사 없이 시각 정보만.
  - ✅ "a small mole with round glasses digging under a big boulder on a forest path,
     ferns and bushes around, side view, full body visible"
  - ✅ "a young man at a small desk late at night, laptop open, one hand on his forehead,
     notebooks stacked, pencil sketch portrait, waist up"
  - ❌ "Morning light. The small mole stands at the base of the boulder, shovel tiny in
     its paws, digging at the rock's edge. Wide shot showing..."  → 추상 타원 출력됨
  - ❌ "an abstract symmetrical pattern, geometric texture" (절대 금지)
  - 동물이 작게 나오면 사라지므로 `full body visible` 또는 `wide shot` 을 반드시 포함.
  - **색은 지정하지 않는다** (색 단어 금지 — 장면마다 색이 갈라진다).
  - ⚠️ **절대로 두 동물을 함께 그리지 말 것** (`two characters`, `talking to the mole` 등).
    두 번째 동물이 있으면 flux 가 주인공 자리를 차지해 **캐릭터가 뒤섞인다**
    (실측: 두더지 주인공인데 거북이가 단독으로 나옴). 조언이 필요한 장면도
    **주인공의 표정/행동만으로 표현**한다(예: "the mole pausing, thinking, alone").
- hook.lines: 각 언어 2줄. 한 줄당 ko/zh-cn 16자, en/fr 40자 이내.
  **각 줄은 끝에 마침표를 찍은 완전한 문장**으로 쓴다(나레이션에서 이어 읽는다).
- hook.highlight: lines 안에 실제로 포함된 강조 단어 1개(주황색 표시용). 각 언어별.
- moral: 아웃트로 카드에 크게 띄울 교훈 문장. 각 언어 1문장, 낭독 5~7초. **2인칭으로 끝낸다.**
- title: 각 언어 짧은 제목.
- caption: 각 언어 게시 캡션 — 첫 줄은 제목(유튜브 제목으로 쓰임), 이어서 우화 한 줄 요약 + 질문. 해시태그는 넣지 마라(자동 추가됨).

{voice}

{fb}순수 JSON 하나만 반환하라:
""" + _SCHEMA_EXAMPLE

    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _load_voice_rules() -> str:
    """config/prompts/fable_voice.md — 언어별 필사 규칙(자연스러운 표현용).

    파일이 없으면 빈 문자열(파이프라인 중단 금지). 프롬프트에 통째로 주입한다.
    """
    p = ROOT / "config" / "prompts" / "fable_voice.md"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


# 스키마 예시 — f-string 이 아닌 일반 문자열 (이중 중괄호 처리 불필요)
_SCHEMA_EXAMPLE = """{
 "title": {"ko": "", "en": "", "zh-cn": "", "fr": ""},
 "caption": {"ko": "", "en": "", "zh-cn": "", "fr": ""},
 "hook": {"lines": {"ko": ["", ""], "en": ["", ""], "zh-cn": ["", ""], "fr": ["", ""]},
          "highlight": {"ko": "", "en": "", "zh-cn": "", "fr": ""}},
 "moral": {"ko": "", "en": "", "zh-cn": "", "fr": ""},
 "characters": "english one-line description",
 "scenes": [
   {"act": "quote", "image_prompt": "english",
    "narration": {"ko": "(시스템이 명언 원문으로 교체)", "en": "", "zh-cn": "", "fr": ""},
    "subtitle": {"ko": "", "en": "", "zh-cn": "", "fr": ""}},
   {"act": "hook", "image_prompt": "english",
    "narration": {"ko": "", "en": "", "zh-cn": "", "fr": ""},
    "subtitle": {"ko": "", "en": "", "zh-cn": "", "fr": ""}},
   {"act": "fable", ...}, {"act": "fable", ...}, {"act": "fable", ...},
   {"act": "fable", ...}, {"act": "fable", ...},
   {"act": "real", ...}, {"act": "real", ...},
   {"act": "outro", ...}
 ]
}"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e > s:
            return json.loads(text[s:e + 1])
        raise


def generate(quote: Quote, theme: str, mock: bool = False) -> dict:
    """명언 → 우화 스토리 JSON. mock=True 면 고정 샘플(파이프라인 점검용).

    자연스름 문제가 검출되면(예: ko '자신감도 바닥이었어요', fr 성 수일치)
    문제 목록을 피드백으로 넣고 최대 max_attempts 회까지 다시 생성한다.
    """
    if mock or not os.getenv("DEEPSEEK_API_KEY"):
        return _validate(_mock_story(quote, theme), quote, theme)
    last_err: Exception = RuntimeError("생성 실패")
    max_attempts = 8      # 지시형 규칙이 엄격해 재생성 횟수를 늘림 (3 → 6 → 8)
    feedback: list[str] = []
    for attempt in range(1, max_attempts + 1):
        resp = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}",
                     "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": _build_messages(quote, theme, feedback),
                "response_format": {"type": "json_object"},
                "temperature": 0.9,
                "max_tokens": 5000,
            },
            timeout=240,
        )
        resp.raise_for_status()
        try:
            data = _extract_json(resp.json()["choices"][0]["message"]["content"])
            story = _validate(data, quote, theme)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            last_err = e
            print(f"  [fable] 스토리 파싱 실패 (시도 {attempt}/{max_attempts}): {e}")
            # 검증 실패 내용을 다음 시도 피드백에 넣는다.
            # (지시형 톤 같은 규칙은 모델이 실수하기 쉬우므로 반복해서 알려줘야 함)
            msg = str(e).strip().splitlines()[0][:180]
            feedback = [f"직전 시도 검증 실패: {msg}"] + feedback[:5]
            continue
        issues = story.get("naturalness_issues") or []
        if not issues:
            return story
        # 문제가 있으면 피드백으로 만들어 다음 시도에서 교정시킨다
        last_err = ValueError("자연스름 검사 미통과: " + "; ".join(issues[:5]))
        feedback = issues[:12]
        print(f"  [fable] 자연스름 미통과 (시도 {attempt}/{max_attempts}):")
        for p in feedback:
            print(f"    - {p}")
        if attempt < max_attempts:
            print("       → 해당 표현을 고쳐 다시 생성합니다")
    # 최종 시도 결과라도 반환(파이프라인 중단 방지) — issues 남아 있을 수 있음
    try:
        return story
    except NameError:
        raise last_err


# ─────────────────────────────────────────────────────────────
# 검증 + 코드 강제 사항
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# 언어별 자연스름 검증 — AI가 "그럴듯하게" 넘겨도 걸러낸다
# ─────────────────────────────────────────────────────────────
# 각 항목 = (언어, 금지 패턴, 사유). 검출 시 해당 필드를 재생성하도록 강제한다.
# 상세 근거는 config/prompts/fable_voice.md 참조.
_BAD_PHRASES: dict[str, list[tuple[str, str]]] = {
    "ko": [
        ("바닥에 닿", "영하식 직역 관용구(구어체에 없음)"),
        ("바닥이었", "영하식 직역 관용구(구어체에 없음)"),
        ("바닥에 닿았", "영하식 직역 관용구(구어체에 없음)"),
        ("읽어보", "해설/서술 톤"),
        ("말이다", "해설 톤"),
    ],
    "en": [
        (" In conclusion", "서술형 결론 문구"),
        (" is known as", "문서체"),
        (" is considered", "문서체 수동형"),
        ("Let that sink in", "클리셰"),
        ("In today's world", "클리셰 도입"),
    ],
    "zh-cn": [
        ("锲而不舍", "书面语成語 — 쇼츠에 부적합"),
        ("持之以恒", "书面语成語 — 쇼츠에 부적합"),
        ("总而言之", "书面语总结"),
        ("请大家", "높임 표현"),
    ],
    "fr": [
        ("Ce n'était", "과도한 접속 구조"),
        ("Il est important de noter", "문서체"),
        ("En conclusion", "서술형 결론"),
        ("il est à noter", "문서체"),
    ],
}


def _ends_with_cjk(s: str) -> bool:
    """끝글자가 CJK(한/중/일)인지 — 한글이면 ' '(스페이스)로 잇지 않는다."""
    return bool(s) and ord(s[-1]) > 0x2E80


def _sentence_sep(lang: str) -> str:
    """언어별 문장 구분자. 한국어는 '. '(영문 마침표), 중국어만 '。'를 쓴다."""
    return "。" if lang == "zh-cn" else ". "


def _strip_second_character(p: str) -> str:
    """두 번째 캐릭터 표현을 제거 — flux 가 주인공 자리를 빼앗는 것을 막는다.

    실측(2026-10-07): "an old tortoise leaning down talking to the mole" 라는 장면이
    'mole(두더지)' 프롬프트인데도 **거북이 단독으로** 렌더됐다. 두 동물이 있으면
    flux 가 주인공 자리를 차지한다. 다른 동물 조언은 주인공의 표정/행동으로 표현한다.
    제거 후 장면 묘사가 너무 짧아지면(빈 프롬프트) 주인공 기본 동작으로 대체한다.
    """
    import re as _re
    ANIMAL = (r"(?:owl|squirrel|fox|rabbit|hare|tortoise|turtle|deer|badger|hedgehog|"
              r"bird|crow|cat|dog|mouse|rat|wolf|fox|elk|deer)")
    out = p
    # "two characters" 류 지시
    out = _re.sub(r",?\s*(?:two characters|both characters|with another (?:animal|character))",
                  "", out, flags=_re.I)
    # 다른 동물을 언급하는 절 전체 삭제 (수식어가 몇 개든)
    out = _re.sub(rf"\b(?:an?|the)\s+(?:\w+\s+){{0,3}}{ANIMAL}\s+(?:\w+\s*){{0,5}}", " ", out, flags=_re.I)
    # 상호작용 동사구 제거 (the mole 를 주어로 하는 경우)
    out = _re.sub(rf"\b(?:talking to|speaking to|talking with|speaking with|telling|showing)\s+the\s+\w+",
                  "", out, flags=_re.I)
    out = " ".join(out.split()).strip().strip(",").strip()
    # 주동물이 빠진 경우 — 주인공 기본 동작으로 대체 (빈 프롬프트 방지)
    if len(out) < 30 or not re.search(r"\b(stand|sit|walk|look|rest|climb|dig|hold|"
                                      r"reach|pause|watch|lean|sleep|step|lie)\w*\b", out, re.I):
        out = ("the main character standing alone, thinking, looking ahead, "
               "full body visible, side view")
    return out.strip().strip(",").strip()


def _strip_sentence_end(s: str) -> str:
    """문장 끝 구두점(마침표/물음표/느낌표/중국어 전갈점/조르간 dot) 제거.

    2026-10-07: '求知若饥，虚心若愚。. — 史蒂夫·乔布斯' 처럼 마침표가 중복되던 문제 해결.
    """
    s = str(s).strip()
    return s.rstrip(".?!。．！…· ")


def _check_naturalness(story: dict) -> list[str]:
    """부자연스러운 표현 검출. 발견한 문제를 문자열 리스트로 반환(빈 리스트 = 통과)."""
    problems: list[str] = []
    scenes = story.get("scenes", [])
    for si, sc in enumerate(scenes):
        for lang in LANGS:
            narr = str(sc.get("narration", {}).get(lang, ""))
            sub = str(sc.get("subtitle", {}).get(lang, ""))
            for text, kind in ((narr, "narration"), (sub, "subtitle")):
                for pat, why in _BAD_PHRASES.get(lang, []):
                    if pat in text:
                        problems.append(f"scene{si + 1}.{kind}[{lang}]: '{pat.strip()}' — {why}")
    # 프렌치 성 수일치: 3인칭 여성 주어 + 남성 동사 어간 (la +Verb 어간+s 형태)
    for si, sc in enumerate(scenes):
        fr_narr = str(sc.get("narration", {}).get("fr", ""))
        # 'trouvaient' 류 실수: 주어가 'la/une' 인데 동사가 남성 복수/남성 단수 꼬리
        for stem in ("trouvaient", "était", "allait", "voulait", "savait", "pouvait"):
            if re.search(rf"\b(?:la|une|tortue|lapin) {stem}\b", fr_narr):
                problems.append(
                    f"scene{si + 1}.narration[fr]: '{stem}' 성 수일치 의심 — "
                    f"주어의 수(성/복수)에 맞춰 어간을 확인 필요")
    # 中文 어미 중복 (。. / 。。/ ！！)
    for si, sc in enumerate(scenes):
        for lang in ("zh-cn",):
            narr = str(sc.get("narration", {}).get(lang, ""))
            sub = str(sc.get("subtitle", {}).get(lang, ""))
            for text, kind in ((narr, "narration"), (sub, "subtitle")):
                if re.search(r"[。．.！!]{2,}", text):
                    problems.append(f"scene{si + 1}.{kind}[{lang}]: 구두점 중복")
    return problems


# ─────────────────────────────────────────────────────────────
# 지시형(命令형) 검사 — 2026-10-08 로이 요청
#
# "설명" 이 아니라 "지시" 하는 톤을 강제한다.
# 2장면 hook / 9장면 real / 10장면 moral(→outro) 가 대상.
# ─────────────────────────────────────────────────────────────
# 각 언어의 명령형 어미/형식. 앞쪽에 오면 명령형이다.
_IMPERATIVE_MARKS: dict[str, tuple[str, ...]] = {
    # 한국어: 어미가 앞쪽에 온다
    "ko": ("해라", "하라", "하거라", "하세요", "마라",
           "해", "해.", "서라", "어라", "으라", "가라", "오라", "누구나",
           "떠올려라", "시작해", "만들어", "실행해"),
    # 영어: imperative 는 두 번째 문장에 오는 경우가 많다
    #   ("Your time is yours. Start living your own life today.")
    # → 한 문장이라도 명령형이면 통과시킨다.
    "en": ("do not", "don't", "stop", "start", "go ", "take ", "put ", "make ",
           "keep ", "begin", "open ", "close ", "write ", "read ", "walk ",
           "run ", "turn ", "give up", "quit", "block ", "clear ", "set ",
           "pick ", "choose", "build", "cut ", "spend ", "protect", "guard ",
           "say no", "say yes", "spend", "prioritize", "commit", "protect",
           # 2인칭 주격 + 동사 (You block / You start) — 영어 imperatives 의 흔한 형태
           "you block", "you start", "you stop", "you take", "you put",
           "you make", "you keep", "you begin", "you open", "you write",
           "you read", "you walk", "you run", "you turn", "you spend",
           "you pick", "you choose", "you build", "you set", "you clear",
           "you cut", "you quit", "you give", "you protect", "you guard",
           "you say", "you must", "you need", "you should", "you can",
           "your first", "your next"),
    # 中文: 서술 + 지시의 2문장 형태가 많다.
    #   "过你自己的人生。今天就开始。" → 두 번째 문장이 지시형이다.
    #   문장을 나눠 **어느 하나라도** 명령형이면 참으로 본다.
    "zh-cn": ("不要", "别", "请", "要", "立刻", "马上", "现在", "去", "做",
              "开始", "记住", "放下", "拿起", "今天就", "从今天",
              "就", "开", "走", "写", "读", "挖", "拿起", "关上", "翻开",
              "别再", "停止", "放弃"),
    # 프랑스어: imperative (ne...pas + verbe, ou verbe direct)
    "fr": ("ne perds", "ne laisse", "arrête", "commence", "prends", "lâche",
           "fais", "va ", "pense", "choisis", "note", "ouvre", "ferme",
           "leve", "pose", "avance", "essaie", "n'hésite",
           # 1인칭 명령형 (tu 接尾)
           "écris", "écris ce", "lis", "écoute", "regarde", "sors",
           "marche", "travaille", "construis", "choisis", "réserve",
           "protège", "lance", "essaie", "arrête", "commence", "prends",
           "donne", "trouve", "gagne", "perds", "change", "nets",
           # 해동사 (sois / fais / prends / écris …)
           "sois", "fais", "prends", "écris", "lis", "écoute", "regarde",
           "sors", "marche", "travaille", "construis", "choisis",
           "réserve", "protège", "lance", "nets", "reprends", "creuse",
           "efface", "avance", "reviens", "continue", "cesse", "deviens",
           "reste", "vis", "gagne", "visse", "trace", "écris"),
           # 중국어 동사 (2자어)
    "zh-cn": ("不要", "别", "请", "要", "立刻", "马上", "现在", "去", "做",
              "开始", "记住", "放下", "拿起", "今天就", "从今天",
              "就", "开", "走", "写", "读", "挖", "关上", "翻开", "合上",
              "别再", "停止", "放弃", "拿起", "扔掉", "关掉", "定好",
              "倒", "拿", "跟", "做", "学", "问", "看", "听", "想",
              "空出", "划出", "留出", "定", "设", "排",
              # 把/将 = "…해라" 의 뉘앙스 (실측 2026-10-08: 大量 실패)
              "把", "将", "给", "让", "用", "从", "向", "跟"),
}


# 영어에서 부사/전치사 뒤에 명령형 동사가 오는 형태:
#   "Right now, write down what you want."
#   ("today" 같은 부사 + write/stop/start …)
_EN_LEADIN = {"right", "now", "today", "tonight", "tomorrow", "instead",
              "first", "please", "just", "go", "and"}
# 명령형으로 쓰이는 대표 동사 (앞에 부사가 있어도, 단독으로도 쓰인다)
_EN_VERBS = ("write", "stop", "start", "read", "take", "put", "make", "keep",
             "begin", "open", "close", "walk", "run", "turn", "block", "clear",
             "set", "pick", "choose", "build", "cut", "spend", "quit",
"protect", "guard", "commit", "do", "give", "say", "dig",
           "stand", "sit", "call", "send", "ask", "try", "learn",
           "plan", "track", "review", "focus", "finish", "start",
           "accept", "refuse", "ignore", "finish", "move", "act",
           # 절 imperative: "Look down at your own feet"
           "look", "listen", "check", "measure", "count", "compare",
           "remember", "notice", "watch", "face", "step", "reach",
           "grab", "hold", "pull", "push", "fill", "empty", "save",
           "throw", "drop", "lift", "carry", "leave", "return",
           "flip", "shut", "silence", "mute", "postpone", "delay",
           "schedule", "block", "cancel", "undo", "redo")


def _is_imperative(text: str, lang: str) -> bool:
    """문장이 명령형인지 판정 — 4개 언어 지원.

    영어/중문/프랑스어는 명령형이 **두 번째 문장**에 오는 경우가 많다
    ("Your time is yours. Start living your own life today.").
    → 여러 문장으로 나눠 **어느 하나라도** 명령형이면 참으로 본다.
    """
    t = (text or "").strip()
    if not t:
        return False
    marks = _IMPERATIVE_MARKS.get(lang, ())
    # 문장 단위로 검사 (영어/중문/프랑스어)
    if lang != "ko":
        parts = [s.strip() for s in re.split(r"[.!?。！？]\s*", t) if s.strip()]
        words_all = [w.strip(",.?!") for w in t.split()]
        for p in parts:
            if lang == "zh-cn":
                # 중국어는 어절 사이에 공백이 없어 문장 첫 단어만 보면 놓친다.
                # ("今晚，把手机扣在桌上" → 把 가 두 번째 어절)
                # → 문장 안의 **어느 어절이든** 지시 동사면 참.
                for mark in marks:
                    if mark in p:
                        return True
                continue
            low = p.lower()
            for mark in marks:
                if low.startswith(mark.lower()):
                    return True
            # "Right now, write down what you want" — 부사/전치사 뒤에 동사
            first = low.split(" ", 1)[0].strip(",.")
            if first in _EN_LEADIN and any(
                    f" {v}" in low[:26] or low.startswith(v) for v in _EN_VERBS):
                return True
            # "Dig your own path today." — 첫 단어가 곧 명령형 동사
            if first in _EN_VERBS:
                return True
            # "You block / You start / You must" — 2인칭 주격 + 동사
            if first == "you":
                second = low.split(" ")[1] if len(low.split(" ")) > 1 else ""
                if second in _EN_VERBS or second in ("must", "should", "need",
                                                     "can", "will", "have"):
                    return True
            # 3) **두 번째 단어가 동사** ("Erase their path…", "Reprends ta vie")
            words = low.replace(",", " ").split()
            if len(words) > 1 and words[1] in _EN_VERBS:
                return True
        # 4) **마지막 단어가 명령형 동사** ("…翻开你自己的。" / "…take your first step.")
        tail_words = [w.strip(",.?!") for w in words_all]
        if len(tail_words) > 1 and tail_words[-2] in _EN_VERBS:
            return True
        return False
    # 한국어는 어미가 앞쪽에 온다
    low = t.lower()
    for mark in marks:
        if low.startswith(mark.lower()):
            return True
        if mark.lower() in low[:24]:
            return True
    # 어미가 문장 끝에 오는 형태: "…써라" "…적어라" "…가라" "…오라"
    # → 마지막 3단어 안에 어미가 있으면 명령형이다.
    #   ("지금 당장 종이에 네가 원하는 걸 써라." → 끝에 '써라')
    # 2026-10-08 실측 실패: "한 줄 써라." 처럼 마침표가 붙으면 마지막 3어절만
    # 봐도 어미를 놓친다 → **문장 전체 어절**에서 검사한다.
    for w in t.replace(",", " ").replace("、", " ").split():
        w = w.rstrip(".,!?。！？")
        if len(w) < 2:
            continue
        for suf in ("해라", "하라", "어라", "으라", "가라", "오라", "서라",
                    "마라", "세요", "떠라", "찍어라", "만들어", "해봐",
                    "해 보라", "밀어라", "끝내라", "펴라", "입라", "벼라",
                    "늘라", "줄여라", "끊어라", "지우라", "버려라", "잊어라",
                    "기억해", "도전해"):
            if w.endswith(suf):
                return True
        # 한국어 명령형의 본질은 "동사 + 라" (해라·써라·파라·펴라·떠라 …).
        # 어미 종류가 많아 열거로 다 못 잡으므로 '라' 로 끝나면 참으로 본다.
        # 서술형(갔다·됐다·끝났다)을 걸러내기 위해 바로 앞 글자가 '다/나' 면 제외.
        if w.endswith("라") and w[-2] not in "다나":
            return True
    return False


def _validate(data: dict, quote: Quote, theme: str) -> dict:
    handles = load_handles(ROOT / "config")

    for key in ("title", "caption", "hook", "moral", "characters", "scenes"):
        if key not in data:
            raise ValueError(f"스토리에 {key} 누락")
    moral = data["moral"]
    for lang in LANGS:
        if not str(moral.get(lang, "")).strip():
            raise ValueError(f"moral[{lang}] 누락")
        moral[lang] = str(moral[lang]).strip()
    scenes = data["scenes"]
    if len(scenes) != len(SCENE_ACTS):
        raise ValueError(f"장면 수 오류: {len(scenes)} (->{len(SCENE_ACTS)} 필요)")
    for i, (sc, act) in enumerate(zip(scenes, SCENE_ACTS)):
        sc["act"] = act  # act 순서는 코드가 정의 — 모델이 보낸 값은 덮어씀
        if not str(sc.get("image_prompt", "")).strip():
            raise ValueError(f"scenes[{i}].image_prompt 누락")
        for lang in LANGS:
            n = str(sc.get("narration", {}).get(lang, "")).strip()
            s = str(sc.get("subtitle", {}).get(lang, "")).strip()
            if not n or not s:
                raise ValueError(f"scenes[{i}] {lang} narration/subtitle 누락")

    hook = data["hook"]
    for lang in LANGS:
        lines = [str(x).strip() for x in (hook.get("lines", {}).get(lang) or []) if str(x).strip()]
        if len(lines) != 2:
            raise ValueError(f"hook.lines[{lang}] 2줄 필요 (현재 {len(lines)}줄)")
        hook["lines"][lang] = lines
        hl = str(hook.get("highlight", {}).get(lang, "")).strip()
        # 강조어가 실제 줄 안에 없으면 버린다(렌더러가 안전하게 무시)
        if hl and not any(hl in ln for ln in lines):
            hook["highlight"][lang] = ""
            hl = ""
        hook.setdefault("highlight", {})[lang] = hl

    # ── 지시형 강제 (2026-10-08 로이 요청) ─────────────────────────────
    # "설명" 이 아니라 "지시" 하는 톤. 2·9·10장면은 명령형으로 끝나야 한다.
    for lang in LANGS:
        lines = hook["lines"].get(lang) or []
        if not any(_is_imperative(lines[0], lang) for _ in (0,)):
            raise ValueError(
                f"hook.lines[{lang}] 첫 줄이 명령형이 아닙니다: '{lines[0][:60]}'\n"
                f"  → 반드시 '~해라' / '~하라' / '~하세요' 로 시작해야 합니다."
            )
        if not _is_imperative(lines[-1], lang):
            raise ValueError(
                f"hook.lines[{lang}] 마지막 줄이 명령형이 아닙니다: '{lines[-1][:60]}'\n"
                f"  → '지금 무엇을 해야 하는지' 지시형으로 끝나야 합니다."
            )
        # 10장면(outro)은 moral 이 대체되므로 moral 자체를 검사한다
        m = str(moral.get(lang, "")).strip()
        if not _is_imperative(m, lang):
            raise ValueError(
                f"moral[{lang}] 가 지시형으로 끝나지 않습니다: '{m[:60]}'\n"
                f"  → 교훈 설명이 아니라 '~해라' 형태의 행동 지시여야 합니다."
            )
        # 9장면(real 교훈 대입)도 명령형이어야 한다
        n9 = str(scenes[8].get("narration", {}).get(lang, "")).strip()
        if not _is_imperative(n9, lang):
            raise ValueError(
                f"scenes[8](real) narration[{lang}] 가 지시형이 아닙니다: '{n9[:60]}'\n"
                f"  → 9장면은 '당신이 지금 할 일' 이므로 명령형이어야 합니다."
            )

    for lang in LANGS:
        if not str(data["title"].get(lang, "")).strip():
            raise ValueError(f"title[{lang}] 누락")
        cap = str(data["caption"].get(lang, "")).strip()
        if not cap:
            cap = f"{data['title'][lang]}\n\n{quote.text_of(lang)}"
        # 해시태그: AI가 달아도 제거 후 언어별 5개 고정으로 항상 통일
        body = "\n".join(
            ln for ln in cap.splitlines() if not ln.strip().startswith("#")
        ).rstrip()
        data["caption"][lang] = body + "\n\n" + FABLE_TAGS[lang]

    characters = str(data["characters"]).strip()
    # 2026-10-07 실측: 크기 비교 표현은 모델이 그 물체를 그린다
    # ("about the size of a teacup" → 사람 얼굴 나옴). 형용사만 남긴다.
    characters = re.sub(r",?\s*about the size of[^,]*", "", characters).strip(" ,")
    # ⚠️ 의류/안장 표현 제거 — flux 가 사람을 그린다 (실측: round glasses → 여성 anthropomorph)
    characters = re.sub(r"\s*(?:with| wearing| in)\s+(?:tiny |small |round |big )?"
                        r"(?:round )?glasses\b", "", characters, flags=re.I)
    characters = re.sub(r"\s*(?:with| wearing| in)\s+(?:a |an |the )?"
                        r"(?:red |blue |green |yellow |white |black |striped |plaid )?"
                        r"(?:scarf|hat|cap|helmet|gloves|boots|sweater|shirt|coat|robe|cloak)\b",
                        "", characters, flags=re.I)
    characters = " ".join(characters.split()).strip(" ,")
    # ⚠️ 부정 표현 제거 — flux 는 'not a cat' 을 'cat' 으로 읽는다 (실측: 고양이 유도됨)
    characters = re.sub(r",?\s*not\s+(?:a|an|the)\s+\w+", "", characters, flags=re.I)
    characters = " ".join(characters.split()).strip(" ,")
    if not characters:
        characters = "a small furry animal"

    # ── 코드 강제: 확정된 대사/프롬프트로 덮어쓴다 ──
    for i, sc in enumerate(scenes):
        # 1) 명언 오프닝(quote) 낭독 = 명언 원문 + 화자 (은행 값 그대로 — 윤색 금지)
        if sc["act"] == "quote":
            for lang in LANGS:
                author = quote.author_of(lang)
                qt = _strip_sentence_end(quote.text_of(lang))
                sc["narration"][lang] = (f"{qt}. — {author}." if author else f"{qt}.")
        # 2) 훅 장면 낭독 = 훅 2줄을 완전한 문장으로 이어 읽는다.
        #    (예: "앞을 막는 돌을 봤어요. 돌아가면 길은 사라져요")
        if sc["act"] == "hook":
            for lang in LANGS:
                parts = [_strip_sentence_end(x) for x in hook["lines"][lang] if str(x).strip()]
                if not parts:
                    continue
                sc["narration"][lang] = _sentence_sep(lang).join(parts)
        # 3) 아웃트로 낭독 = 교훈 문장 (quote 는 이미 오프닝에서 낭독됨)
        if sc["act"] == "outro":
            for lang in LANGS:
                sc["narration"][lang] = moral[lang]
        # 4) 이미지 프롬프트 일관성 — 흑백 스타일 강제 삽입 (로이 지시 2026-10-07)
        #    real 장면은 사람이 중심이므로 동물을 넣지 않는다.
        #
        #    ⚠️ 조립 순서 (2026-10-07 실측):
        #      - 스타일은 짧게 유지 (길면 flux 가 장면 내용을 버린다)
        #      - **장면 묘사가 characters 보다 먼저** (캐릭터가 앞이면 클로즈업에 고정)
        #    ⚠️ 캐릭터 일관성 (2026-10-07 실측):
        #      characters 를 한 번만 넣으면 flux 가 다른 동물/사람으로 그린다
        #      (실측: 두더지인데 여우·사람이 나옴). **앞뒤로 중복 삽입**해
        #      정체성 강도를 올린다. + "same character as the other scenes" 힌트.
        p = _strip_sentence_end(str(sc["image_prompt"]))
        # 두 동물 동시 등장 표현 제거 — 두 번째 동물이 주인공 자리를 차지한다
        # (실측: 두더지 주인공인데 거북이 단독으로 나옴)
        p = _strip_second_character(p)
        if sc["act"] in NO_CHARACTER_ACTS:
            sc["image_prompt"] = f"{STYLE_PREFIX}, {p}, {STYLE_SUFFIX}"
        else:
            sc["image_prompt"] = (
                f"{STYLE_PREFIX}, {characters}, {p}, {characters}, "
                f"same character as every other scene, {STYLE_SUFFIX}")

    story = {
        "date": datetime.now(quotes.KST).date().isoformat(),
        "theme": theme,
        "theme_label": THEME_LABELS.get(theme, theme),
        "quote": {"id": quote.id, "author": quote.author, "text": quote.text},
        "title": data["title"],
        "caption": data["caption"],
        "hook": hook,
        "moral": moral,
        "characters": characters,
        "cta": {lang: CTA_TEXTS[lang].format(h=handles[lang]) for lang in LANGS},
        "scenes": scenes,
    }
    # 자연스름 검증 결과 기록 (로이 검수용 — 문제가 있어도 파이프라인은 계속 진행)
    story["naturalness_issues"] = _check_naturalness(story)
    return story


def save_story(story: dict, data_dir: Path, date: str | None = None) -> Path:
    """스토리 저장.

    2026-10-08 수정: 모델이 story['date'] 를 오늘 날짜로 채워 넣는 경우가 있어
    --date 로 지정한 날짜(예: 2026-10-09)가 무시되었다.
    → date 인자를 명시하면 그것을 강제로 쓴다.
    """
    if date:
        story["date"] = date
    out = story_dir(data_dir, story["date"]) / "story.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ─────────────────────────────────────────────────────────────
# 목 스토리 — API 없이 전 파이프라인 점검 (토끼와 높은 언덕)
# ─────────────────────────────────────────────────────────────
def _mock_story(quote: Quote, theme: str) -> dict:
    T = {
        "ko": {
            "h1": "토끼는 언덕 위 해돋이를", "h2": "매일 포기하며 꿈만 꿨어요",
            "hl": "포기",
            "n1": "작은 토끼 한 마리가 언덕 위 해돋이를 보고 싶어했어요.",
            "n2": "첫날엔 씩씩 뛰어 올랐는데, 금방 숨이 차서 주저앉았어요.",
            "n3": "다람쥐가 그러더라고요. 한 번에 다 오르려 하지 말고, 아침마다 조금씩만 가보라고요.",
            "n4": "사흘 동안 비를 맞으면서, 그만두고 싶은 마음을 이겨냈어요.",
            "n5": "그리고 어느 새벽, 정상이 눈앞에 그냥 서 있었어요.",
            "n6": "언덕 위에서 본 해돋이는, 상상했던 것보다 훨씬 컸어요.",
            "n7": "우리 모두 저런 언덕이 있어요. 오늘 딱 한 걸음만 더 디디면 돼요.",
            "n8": "정상에 도착하는 날은 결국, 작은 걸음이 쌓여서 오는 거예요.",
            "n9": "outro",
            "t": "토끼와 높은 언덕",
            "s": ["오늘의 명언", "언덕 위 해돋이", "숨이 차서 주저앉음", "조금씩만 가보라고",
                  "그만두지 않는 마음", "정상이 눈앞에", "상상보다 컸음",
                  "한 걸음만 더", "작은 걸음의 힘", "오늘 한 걸음"],
        },
        "en": {
            "h1": "The rabbit dreamed of the sunrise.", "h2": "It gave up halfway, every single day.",
            "hl": "gave up",
            "n1": "A little rabbit really wanted to see the sunrise from the top of that hill.",
            "n2": "She sprinted up on the first day — and collapsed a minute later, out of breath.",
            "n3": "A squirrel told her something. Don't try to do it all at once. Just a little, every morning.",
            "n4": "For three rainy days she fought the urge to quit.",
            "n5": "And then, one dawn, the summit was just there.",
            "n6": "The sunrise from up there was bigger than she'd ever pictured it.",
            "n7": "You've got a hill too. Just take one more step today.",
            "n8": "You reach the top on the day your small steps add up.",
            "n9": "outro",
            "t": "The Rabbit and the Tall Hill",
            "s": ["TODAY'S QUOTE", "Wanted that sunrise", "Collapsed, out of breath", "A little, every morning",
                  "Fighting the urge to quit", "The summit, just there", "Bigger than pictured",
                  "One more step", "Small steps add up", "Your one step today"],
        },
        "zh-cn": {
            "h1": "兔子每天都梦想着山上的日出", "h2": "却每次都在半路放弃",
            "hl": "放弃",
            "n1": "一只小兔子，特别想看看山顶上的日出。",
            "n2": "第一天它一口气往上冲，很快就喘得坐在地上起不来了。",
            "n3": "松鼠跟它说：别想着一口气就登顶，每天早上只走一点点就行。",
            "n4": "连着下了三天雨，它一直在跟想放弃的念头较劲。",
            "n5": "然后某个清晨，山顶忽然就出现在眼前了。",
            "n6": "从山顶看到的日出，比它想象的还要大。",
            "n7": "你也有这样一座山。今天就多走一步吧。",
            "n8": "走到山顶的那一天，就是这些小步子攒够的那一天。",
            "n9": "outro",
            "t": "兔子与高高的山坡",
            "s": ["今日名言", "想看山顶日出", "喘得坐在地上", "每天只走一点点",
                  "跟放弃较劲", "山顶忽然出现", "比想象更大",
                  "再多走一步", "小步子攒够了", "今天你的一步"],
        },
        "fr": {
            "h1": "Le lapin rêvait du lever de soleil.", "h2": "Il abandonnait à mi-chemin, chaque jour.",
            "hl": "abandonnait",
            "n1": "Un petit lapin rêvait vraiment de voir le lever du soleil depuis le sommet de la colline.",
            "n2": "Premier jour, il est parti à toute vitesse — et s'écroule au bout d'une minute.",
            "n3": "Un écureuil lui a dit un truc : n'essaie pas tout d'un coup. Juste un peu, chaque matin.",
            "n4": "Trois jours de pluie, il a lutté contre l'envie de s'arrêter.",
            "n5": "Et puis, un matin, le sommet était juste là.",
            "n6": "Le lever de soleil vu d'en haut dépassait tout ce qu'il avait imaginé.",
            "n7": "Toi aussi, tu as ta colline à gravir. Fais juste un pas de plus aujourd'hui.",
            "n8": "On arrive en haut le jour où les petits pas se sont additionnés.",
            "n9": "outro",
            "t": "Le Lapin et la Grande Colline",
            "s": ["CITATION DU JOUR", "Rêvait de ce lever de soleil", "Essoufflé, il s'écroule", "Juste un peu, chaque matin",
                  "Lutter pour ne pas arrêter", "Le sommet, juste là", "Plus grand que prévu",
                  "Un pas de plus", "Les petits pas s'additionnent", "Ton pas d'aujourd'hui"],
        },
    }
    prompts = [
        "a small white rabbit with a red scarf sitting quietly on a mossy stone at dawn, "
        "watching the quiet horizon",
        "the rabbit standing at the base of a tall hill, looking up, seen from a low angle",
        "the rabbit sprinting up the hillside, determined, seen from the side",
        "the rabbit sitting exhausted halfway up the path, catching breath, head lowered",
        "the rabbit sitting still and thinking, looking up, seen from the front",
        "the rabbit walking slowly upward, clinging to the cliff edge, small in the frame",
        "the rabbit sitting still and thinking, looking up at the sky, alone, seen from the front",
        "the rabbit reaching the hilltop, arms open, seen from behind",
        "a quiet modern desk beside a window, notebook and a cup, a person sitting down",
        "a person silhouette climbing stairs, seen from behind, early morning",
        "the rabbit standing at the hilltop looking out at the horizon, calm and still",
    ]
    scenes = []
    for i, act in enumerate(SCENE_ACTS):
        scenes.append({
            "act": act,
            "image_prompt": prompts[i],
            "narration": {l: T[l].get(f"n{i + 1}", "(자동 생성)") for l in LANGS},
            "subtitle": {l: T[l]["s"][i] for l in LANGS},
        })
    return {
        "title": {l: T[l]["t"] for l in LANGS},
        "caption": {
            "ko": f"{T['ko']['t']}\n\n매일 한 걸음이 쌓이는 이야기. 오늘 당신의 한 걸음은 무엇인가요?",
            "en": f"{T['en']['t']}\n\nA story about small steps that add up. What is your one step today?",
            "zh-cn": f"{T['zh-cn']['t']}\n\n小步子慢慢积累的故事。今天你的一步是什么？",
            "fr": f"{T['fr']['t']}\n\nUne histoire de petits pas qui s'additionnent. Quel est ton pas aujourd'hui ?",
        },
        "hook": {"lines": {l: [T[l]["h1"], T[l]["h2"]] for l in LANGS},
                 "highlight": {l: T[l]["hl"] for l in LANGS}},
        "moral": {
            "ko": "조금씩이라도 매일 오른 사람은, 꼭대기의 아침을 봅니다.",
            "en": "If you climb a little every day, you'll see the morning up there.",
            "zh-cn": "每天往上走一点的人，终会看到山顶的早晨。",
            "fr": "Si tu grimpes un peu chaque jour, tu verras le matin tout en haut.",
        },
        "characters": "a small white rabbit with a red scarf",
        "scenes": scenes,
    }
