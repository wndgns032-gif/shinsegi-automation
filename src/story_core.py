"""우화 쇼츠 통일 대본 엔진 — 3개 장르(명언/증권/사업가)가 공유하는 단일 규칙.

2026-10-11 전면 재구축 (로이 요청: "그냥 처음부터 다시 만들어봐").

## 왜 이 파일이 필요한가

기존 구조의 근본 결함:
  fable.py(1147줄) 와 stock_story.py / biz_story.py 가 **각자 따로 프롬프트**를
  들고 있었다. 참고 채널(인생지혜) 분석 결과를 fable.py 에만 반영했더니
  08시·16시 편은 여전히 설교체·보고서체로 나왔다.

  실측 (2026-10-11):
    biz  1장면: "대부분은 준비가 부족해서 시작하지 못한다고 믿는다. 실제로는
                결정을 미루는 습관이 발목을 잡는다. 완벽한 타이밍을 기다리는
                동안 판은 이미 바뀐다."   ← 86자 설교체
    주식 1장면: "오늘 다룰 회사는 애플이다. 티커는 AAPL, 나스닥 시총 2위다."
                                          ← 보고서체

→ **규칙을 한 곳에 두고, 장르는 "素材"만 공급한다.**

## 참고 채널 실측 규격 (yt-dlp + 프레임 계측, 2026-10-11)

화면 (360x640 기준):
    상단 제목바 7.8% (0~50px)   ← 노란색 굵은 글씨
    이미지 영역 72.2% (51~512px, 종횡비 0.779)
    하단 바     19.8% (513~640px)
색상 비율: 노란 픽셀 7.18% / 흰 픽셀 1.87%

대본:
    - 동물 우화가 아니라 **1인칭 관찰자**의 짧은 문장 나열
    - 문장 10~18자
    - 짧은 문장 + 쉼 + 짧은 문장
    - 어미 혼용 (~이다 / ~이었다 / ~한다 / ~된다)
    - 존댓말·경어 없음
    - 마지막은 담담한 반지 ("괜찮은 사람이다")

## ⚠️ 가장 중요한 교훈 (검증 로직이 창의성을 죽인다)

이전 버전은 `_is_imperative()` 를 **통과 조건**으로 걸었다.
그러자 LLM 이 "~해라" 로 시작해 "~해라" 로 끝나는 대본만 만들었다.
100편이 다 똑같이 생겼다.

→ **강제하지 말고 차단만 한다.** 이 파일의 모든 검사는
   "틀린 것을 걸러내는" 방향으로만 쓰고, "맞는 것을 요구"하지 않는다.
"""
from __future__ import annotations

import json
import os
import random
import re
from typing import Any, Callable

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"          # ⚠️ deepseek-chat 은 없는 모델명(404)
LANGS = ["ko", "en", "zh-cn", "fr"]

# ---------------------------------------------------------------------------
# 1. 통일 장면 구조 — 3개 장르가 전부 이 10장을 쓴다.
#    (기존: fable 10 / biz 9 / stocks 9 → 제각각이라 스타일이 안 맞았다)
# ---------------------------------------------------------------------------
SCENE_PLAN: list[tuple[str, str]] = [
    ("hook",    "시선을 잡는다. 아직 설명하지 않는다."),
    ("tension", "갈등·막힘을 보여준다. 장면으로."),
    ("body",    "전개 1 — 구체적인 장면"),
    ("body",    "전개 2 — 시간이 흐른다"),
    ("body",    "전개 3 — 반복되거나 어긋난다"),
    ("turn",    "어긋남에서 뭔가 보이기 시작한다"),
    ("turn",    "깨달음 — 깨달았다는 말을 하지 않고 보여준다"),
    ("real",    "현실로 들어온다. 지금 이 순간."),
    ("now",     "오늘의 장면 하나"),
    ("moral",   "담담한 반지. 지시하지 않는다."),
]

N_SCENES = len(SCENE_PLAN)

# 장면별 이미지 힌트 — LLM 이 image_prompt 를 비웠을 때의 안전망.
# ⚠️ 2026-10-11 개선: **공간·사물 중심**으로 바꿨다.
#    이전엔 "person standing alone window" 처럼 인물을 앞세워서
#    열 장면이 전부 얼굴 클로즈업으로 나왔다. 참고 채널은 배경이 보이는
#    넓은 구도다 — 인물이 필요하면 "distant figure" 로 작게 둔다.
ACT_IMAGE_HINT: dict[str, str] = {
    "hook":    "empty street at dawn, one person walking away, seen from behind",
    "tension": "narrow alley with closed shutters, one person standing still, seen from behind",
    "body":    "cluttered desk by a window at night, one person sitting at it, seen from behind",
    "turn":    "open field at sunrise, one person standing on a long road, seen from behind",
    "real":    "busy city crosswalk seen from above, one still figure among the crowd",
    "now":     "quiet room with a chair by the window, one person sitting, seen from behind",
    "moral":   "empty road stretching to the horizon, one small figure in the middle distance",
}

# image_prompt 에는 스타일 토큰을 붙이지 **않는다**. 관련 이유는
# `_image_prompt()` 주석 참고. 경로별로 스타일을 붙이는 곳이 따로 있다.
IMAGE_STYLE = ("black and white manga illustration, monochrome, "
               "clean line art, flat shading, detailed background, "
               "cinematic wide shot, full body visible, environment visible, "
               "no text, no frame, no watermark")


# ---------------------------------------------------------------------------
# 2. 통일 목소리 규칙 — 참고 채널 실측 기반. 3개 장르 전부 이걸 쓴다.
# ---------------------------------------------------------------------------
VOICE_RULES = """
## 🔥 대본 규칙 — 참고 채널(인생지혜) 프레임 실측 기반

이 채널의 영상은 동물 우화가 아니다.
**1인칭 관찰자가 짧은 문장을 던지는 형식**이다. 이 형식을 그대로 따른다.

### 1) 문장 길이 — 가장 중요하다
**한국어 기준 한 문장 10~18자.** 이걸 넘기면 그 문장은 실패다.
마침표로 짧게 끊어라. 한 장면의 narration 은 짧은 문장 1~3개다.

  ✅ "정답이 어딘가에 있다."
  ✅ "혼자가 아니길 잘했다."
  ✅ "그때였습니다."
  ❌ "대부분은 준비가 부족해서 시작하지 못한다고 믿는다. 실제로는 결정을 미루는 습관이 발목을 잡는다."
     (86자 — 이렇게 쓰면 실패)

영어는 4~10단어, 중국어는 8~15자, 프랑스어는 5~12단어 정도가 같은 리듬이다.

### 2) 리듬
짧은 문장 + 쉼 + 짧은 문장.
같은 길이의 문장을 연속으로 붙이지 마라.

### 3) 1인칭 관찰자 — 동물 주인공 금지
주인공은 **이름 없는 '나'** 다. 두더지·비버·토끼 같은 동물 우화를 쓰지 마라.
우리가 관찰하는 건 사람의 일상이다.

  ✅ "나는 아직 그 자리에 있었다."
  ❌ "두더지는 사흘째 그 자리에서 팠다."

### 4) 어미 혼용
~이다 / ~이었다 / ~한다 / ~된다 를 자연스럽게 섞는다.
같은 어미를 반복하면 번역투처럼 들린다.

### 5) 존댓말·경어 금지
"~습니다" "~하세요" 쓰지 마라. 혼잣말에 가깝게.

### 6) 🚫 명령형 금지 — 이전 버전의 가장 큰 실패
**"~해라" "~하세요" "~하라" 로 끝나는 문장을 쓰지 마라.**
교훈을 설명하거나 행동을 지시하면 대본이 즉시 촌스러워진다.

  ❌ "오늘 당장 첫 한 걸음을 떼세요."
  ❌ "준비될 때까지 기다리지 마라."
  ✅ "첫 걸음의 크기는 의미가 없다. 방향만 있으면 된다."
  ✅ "기다림도 준비의 일부였다."

마지막 장면(moral)은 **담담한 반지나 단정**으로 끝낸다.
"~이다" "~이었다" 로 닫아라.

### 7) 🚫 클리셰 금지 — 이것들이 "구린" 대본의 정체다
- "당신도" 로 시작하는 문장
- "지금 당장" / "작은 것의 힘" / "작은 승리" / "매일 조금씩"
- "한 여자는 매일 새벽 5시에 일어났다. 3년 동안 한 번도 안 틀렸다."
  ← 이 문장이 매번 반복됐다. 금지.
- 숫자 나열 (3년, 1000번, 5시) → 대신 **장면 하나**를 보여라
  ❌ "매일 5시에 일어나 3년간 천 번을 썼다"
  ✅ "책상 구석에 종이가 매일 한 장씩 쌓여 있었다."
- 질문형 종결, "여러분", "우리 모두", 구독 유도

### 8) 화법 4가지 — 매 편 하나를 골라 10장면 내내 유지한다
| 화법 | 예시 (한국어) |
|---|---|
| 단정형 | "준비는 언젠가 끝나지 않는다. 손을 펴는 순간 시작이다." |
| 반전형 | "너무 많이 준비하면, 시작할 순간이 오지 않는다." |
| 질문 출발형 | "준비한다는 핑계가 될 게 뭐가 있나. 펜을 드는 순간 끝난다." |
| 관찰 후 찌르기 | "내일부터 하겠다. 그 말, 이미 백 번 들었다." |

### 9) 장면별 톤
- **1장면(hook)**: 위 화법 중 하나. 강해야 한다. 설명은 아직.
- **2~7장면**: 건조하게. 감정을 설명하지 말고 장면만 던져라.
- **8~9장면(real/now)**: ⭐ 가장 중요. 여기서 패턴을 깬다.
  "당신도 ~해라" 금지. 구체적 장면 하나.
- **10장면(moral)**: ⭐ 명령형 금지. 반지·단정으로 닫는다.

### 10) 언어별 규칙 (번역투 방지 — 각 언어를 원어민처럼 따로 쓴다)

**[한국어]**
- 띄어쓰기 100% 정확하게. ("한거북이가" ❌)
- 조사(은/는, 이/가) 정확히.
- 영어식 직역 관용구 금지 ("자신감도 바닥이었다" ❌)

**[English]**
- 3인칭 기록체 금지. ("The turtle got up again." ❌ — 유튜브 요약 채널 톤)
- 축약형 사용 (didn't, couldn't, wasn't)
- 문서체 수동형 금지 ("is considered", "is known as" ❌)
- 도입 클리셰 금지 ("In today's world", "In conclusion" ❌)

**[中文(简体)]**
- 口语체로 쓴다. 成語·书面语 금지 ("锲而不舍" ❌)
- 마침표 중복 금지 ("。." ❌)
- 앞 문장과 주어 반복 금지

**[Français]**
- **성·수·어간 일치** 최우선. ("Tous la trouvaient folle" ❌)
- 접속 구조 최소화 ("Ce n'était pas grave si…" ❌)
- tu / vous 한 편에서 하나로 통일
- 직역 금지 ("C'est pareil pour nous" ❌)
"""

# ---------------------------------------------------------------------------
# 3. 검증 — "강제"가 아니라 "차단"만 한다. (교훈: 강제하면 대본이 죽는다)
# ---------------------------------------------------------------------------

# 한국어만 명령형 어미를 정규식으로 본다.
# ⚠️ 영어까지 어미 규칙을 적용하면 "What you put in it is yours" 처럼
#     명사를 명령형으로 오판해 8회 연속 실패한 사고가 있었다.
_KO_IMPERATIVE = re.compile(r"(해라|하라|하지마라|마세요|하세요|십시오|합시다)\s*[.。!?]?\s*$")

_CLICHE_KO = ("당신도", "지금 당장", "작은 승리", "작은 것의 힘", "매일 조금씩",
              "여러분", "우리 모두", "구독", "좋아요")
_CLICHE_EN = ("in today's world", "in conclusion", "is considered",
              "is known as", "remember that", "follow for more")
_CLICHE_ZH = ("请大家", "锲而不舍", "只要功夫深")
_CLICHE_FR = ("il est important de noter", "n'oubliez pas de")

# 장면당 허용 최대 문자 수 (한국어 기준). 참고 채널 실측 10~18자 × 3문장 + 여유.
_MAX_NARRATION_KO = 90


def _ko_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.。!?])\s*", str(text).strip())
            if s.strip()]


def check_story(data: dict, scenes_key: str = "scenes") -> list[str]:
    """대본을 검사해 문제 목록을 돌려준다. 차단만 하고 강제는 하지 않는다."""
    issues: list[str] = []

    scenes = data.get(scenes_key) or []
    if len(scenes) < N_SCENES:
        issues.append(f"장면 수 부족: {len(scenes)}개 — {N_SCENES}개 필요")

    for i, sc in enumerate(scenes, start=1):
        narr = sc.get("narration") or {}
        ko = str(narr.get("ko") or "")
        if not ko:
            issues.append(f"{i}장면 한국어 narration 없음")
            continue

        # 1) 길이 — 한국어 기준
        if len(ko) > _MAX_NARRATION_KO:
            issues.append(f"{i}장면이 너무 길다({len(ko)}자): '{ko[:40]}…' "
                          f"— 문장을 10~18자로 쪼개라")

        # 2) 명령형 종결 차단 (한국어만)
        if _KO_IMPERATIVE.search(ko):
            issues.append(f"{i}장면이 명령형으로 끝난다: '{ko[-30:]}' "
                          f"— 반지나 단정으로 닫아라")

        # 3) 클리셰
        low = ko.lower()
        for c in _CLICHE_KO:
            if c in low:
                issues.append(f"{i}장면 금지 표현 '{c}': '{ko[:40]}…'")

        # 4) 언어별 클리셰
        en = str(narr.get("en") or "").lower()
        for c in _CLICHE_EN:
            if c in en:
                issues.append(f"{i}장면 영어 문서체/클리셰 '{c}'")
        zh = str(narr.get("zh-cn") or "")
        for c in _CLICHE_ZH:
            if c in zh:
                issues.append(f"{i}장면 중국어 금지 표현 '{c}'")
        fr = str(narr.get("fr") or "").lower()
        for c in _CLICHE_FR:
            if c in fr:
                issues.append(f"{i}장면 프랑스어 금지 표현 '{c}'")

        # 5) 4개 언어 다 채워졌는지
        for lg in LANGS:
            if not str(narr.get(lg) or "").strip():
                issues.append(f"{i}장면 {lg} narration 비어 있음")

    # 6) moral 은 특히 명령형을 엄격히 차단
    moral = data.get("moral") or {}
    if _KO_IMPERATIVE.search(str(moral.get("ko") or "")):
        issues.append(f"moral 이 명령형으로 끝난다: '{str(moral.get('ko'))[-30:]}'")

    return issues


# ---------------------------------------------------------------------------
# 4. LLM 호출 + 재작성 루프
# ---------------------------------------------------------------------------
SCHEMA = """
반드시 아래 JSON 형식으로만 답하라. 설명문·코드블록 없이 JSON 만.

{
  "title":    {"ko":"...","en":"...","zh-cn":"...","fr":"..."},
  "caption":  {"ko":"...","en":"...","zh-cn":"...","fr":"..."},
  "hook": {
    "lines":     {"ko":["짧은 문장","짧은 문장"],"en":[...],"zh-cn":[...],"fr":[...]},
    "highlight": {"ko":"강조 단어","en":"...","zh-cn":"...","fr":"..."}
  },
  "moral": {"ko":"...","en":"...","zh-cn":"...","fr":"..."},
  "cta":   {"ko":"...","en":"...","zh-cn":"...","fr":"..."},
  "scenes": [
    {"act":"hook",
     "subtitle":  {"ko":"...","en":"...","zh-cn":"...","fr":"..."},
     "narration": {"ko":"...","en":"...","zh-cn":"...","fr":"..."},
     "image_hint":{"en":"english noun phrase for image search"}},
    ... 10개
  ]
}

image_hint 는 영어 **명사구**로 쓴다 (예: "cluttered desk by a window at night").

⭐ 구도 규칙 — 이게 어긋나면 영상이 전부 똑같아 보인다:
- 형식 = **"<장소·사물·시간>, <사람이 그곳에서 하는 동작 — 뒷모습/멀리>"**
  ✅ "subway platform at dawn, one person waiting, seen from behind, long shot"
  ✅ "kitchen table at night, one person sitting alone, back to the camera"
- **장소가 앞, 사람이 뒤.** 장소 없이 사람만 쓰면 얼굴 클로즈업이 나온다.
- **매 장면에 사람 1명을 넣는다** (1장면 quote 만 예외). 사람이 없으면
  빈 방 사진처럼 나와서 영상이 죽는다 — 실측.
- **얼굴 클로즈업 금지.** portrait / close-up / face / headshot / over the shoulder /
  upper body / medium shot 쓰지 마라. 넣으면 열 장이 전부 얼굴이 된다.
- 사람은 **작게**: "seen from behind", "distant figure", "small figure in the middle distance".
- 장면마다 장소를 다르게 한다 (같은 방·같은 거리 반복 금지).
- 스타일 수식어(pencil drawing / monochrome / manga 등)는 넣지 마라 — 시스템이 붙인다.
"""


def build_messages(system: str, topic_block: str) -> list[dict]:
    """장르가 system(역할) + topic_block(素材) 만 주면 규칙은 전부 공통."""
    plan = "\n".join(f"  {i}. act='{a}' — {d}"
                     for i, (a, d) in enumerate(SCENE_PLAN, start=1))
    user = (f"{topic_block}\n\n{VOICE_RULES}\n\n"
            f"## 장면 구성 — 순서 고정, {N_SCENES}개\n{plan}\n\n{SCHEMA}")
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def _extract_json(text: str) -> dict:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text).strip(), flags=re.S)
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        pass
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        return json.loads(t[i:j + 1])
    raise ValueError("JSON 파싱 실패")


def call_llm(messages: list[dict], timeout: int = 300) -> dict:
    import requests
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY 없음")
    r = requests.post(
        DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={"model": MODEL, "max_tokens": 16000, "messages": messages,
              "response_format": {"type": "json_object"}},
        timeout=timeout)
    r.raise_for_status()
    return _extract_json(r.json()["choices"][0]["message"]["content"])


def _image_prompt(hint: str, act: str) -> str:
    """image_hint → **순수 장면 묘사**. 힌트가 비면 act 기본값.

    ⚠️ 2026-10-11 핵심 버그 수정 (실측):
    이전엔 IMAGE_STYLE 을 앞에 붙인 완성 프롬프트를 저장했다.

        "black and white manga illustration, monochrome, clean line art,
         flat shading, detailed background, person standing alone..."

    그런데 `anime.build_anime_prompt()` 는 **콤마 기준 앞 5개만** 취한다.
    → 앞 5개가 전부 스타일 토큰이라 **정작 장면 묘사가 잘려나갔다.**
    결과: 열 장면이 전부 인물 얼굴 클로즈업으로만 생성됨.

    스타일은 각 경로가 따로 붙인다 (anime 는 ANIME_SUFFIX, 실사는 검색어로).
    → 여기선 **순수 장면 묘사만** 저장한다. 실사 검색에도 이게 맞다
      (스타일 수식어가 섞이면 검색이 산으로 간다 — 실측 경험).
    """
    h = str(hint or "").strip().strip(".,")
    if len(h) < 8:
        h = ACT_IMAGE_HINT.get(act, "quiet everyday scene")
    return _strip_portrait(h)


# ⚠️ 2026-10-11 실측: 규칙을 프롬프트에 써도 LLM 이 "over the shoulder" 같은
#    초상 유발 표현을 계속 넣는다. 그 한 토큰이 열 장을 전부 얼굴로 고정시켰다.
#    → 코드에서 결정적으로 제거한다. (anime.py 와 같은 목록)
_PORTRAIT_WORDS = (
    "close-up", "closeup", "close up", "portrait", "headshot", "bust shot",
    "face", "facial", "over the shoulder", "over-the-shoulder",
    "looking at the camera", "looking into the camera",
    "his eyes", "her eyes", "upper body", "medium shot", "chest up",
)


def _strip_portrait(text: str) -> str:
    """초상 클로즈업 유발 토큰 제거(콤마 단위)."""
    kept = [c.strip() for c in (text or "").split(",")
            if c.strip() and not any(w in c.lower() for w in _PORTRAIT_WORDS)]
    return ", ".join(kept)


def generate(system: str, topic_block: str, extra_meta: dict | None = None,
            max_attempts: int = 4, verbose: bool = True) -> dict:
    """통일 생성 루프 — 규칙 위반을 검출해 프롬프트에 되먹여 재작성한다.

    핵심: 검출한 문제를 **그대로 다음 프롬프트에 실어 보낸다.**
    그냥 "다시 써라" 만 하면 같은 실수를 반복한다 (실측 확인).
    """
    feedback: list[str] = []
    data: dict = {}
    issues: list[str] = []
    call_ok = False          # 2026-10-12: 단 한 번이라도 LLM 호출이 성공했는가

    for attempt in range(1, max_attempts + 1):
        fb = ""
        if feedback:
            fb = ("\n\n## 🔴 직전 시도에서 걸린 문제 — 반드시 고쳐라\n"
                  + "\n".join(f"- {x}" for x in feedback[:14]) + "\n")
        msg = build_messages(system, topic_block + fb)
        try:
            data = call_llm(msg)
            call_ok = True
        except Exception as e:  # noqa: BLE001
            issues = [f"LLM 호출 실패: {str(e)[:180]}"]
            if verbose:
                print(f"  [core] 시도 {attempt} 호출 실패: {str(e)[:120]}")
            continue

        issues = check_story(data)
        if not issues:
            if verbose:
                print(f"  [core] 시도 {attempt} — 통과")
            break
        if verbose:
            print(f"  [core] 시도 {attempt} — 문제 {len(issues)}건")
            for x in issues[:5]:
                print(f"         · {x}")
        feedback = issues

    # ⚠️ 2026-10-12 교훈 (DeepSeek 잔액 소진 사고):
    # 호출이 단 한 번도 안 됐으면 data 는 {} 다. 이걸 "최선본"으로
    # 반환하면 쓰레기 story.json 이 저장되고 렌더만 전멸한 채
    # workflow 는 exit 0 "성공" 으로 위장한다 (조용한 누락).
    # → 호출 성공 없으면 반드시 죽인다. 잔액/키/네트워크를 확인하게 한다.
    if not call_ok:
        raise RuntimeError(
            f"LLM 호출 {max_attempts}회 전체 실패 — DeepSeek 잔액/키/네트워크 확인 필요 "
            f"(마지막 오류: {issues[-1] if issues else '없음'})")

    # 끝까지 규칙 위반이 남아도, **호출은 성공한** 최선본을 쓴다.
    data["naturalness_issues"] = issues

    # image_prompt 확정 — hint 를 조립하고 없으면 act 기본값
    for i, sc in enumerate(data.get("scenes") or []):
        act = sc.get("act") or (
            SCENE_PLAN[i][0] if i < N_SCENES else "body")
        sc["act"] = act
        if not sc.get("image_prompt"):
            sc["image_prompt"] = _image_prompt(sc.get("image_hint", {}).get("en")
                                               if isinstance(sc.get("image_hint"), dict)
                                               else sc.get("image_hint"), act)

    if extra_meta:
        data.update(extra_meta)
    return data


def fallback(**kw) -> Callable:
    """LLM 실패 시 최소 형태의 대본. 렌더가 죽지 않게 하는 안전망."""
    raise NotImplementedError
