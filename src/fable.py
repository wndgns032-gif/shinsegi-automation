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
# 주인공 동물 외형(characters)도 코드에서 강제 삽입한다 (모델 망각 방지).
STYLE_PREFIX = "children's storybook watercolor illustration, soft warm muted colors"
STYLE_SUFFIX = ("gentle atmospheric light, cozy detailed background, "
               "no text, no letters, no watermark, no logo")

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
def _build_messages(quote: Quote, theme: str) -> list[dict]:
    quote_block = "\n".join(
        f"- {l}: {quote.text_of(l)} ({quote.author_of(l)})" for l in LANGS)
    system = (
        "당신은 자기계발 우화 숏츠 채널의 작가다. "
        "동물 우화로 인생의 교훈을 전달하고, 마지막에 명언으로 마무리하는 "
        "60~75초 세로 영상 대본을 쓴다. 어떤 언어로 대답하든 JSON 값은 "
        "각 언어에 맞는 자연스러운 문장으로 작성한다(기계번역투 금지)."
    )
    user = f"""## 오늘의 명언 (이 교훈을 우화로 풀 것)
{quote_block}

테마: {THEME_LABELS.get(theme, theme)}

## 구조 (총 10장면 — 명언이 영상을 연다)
1장면 quote: 명언 원문을 화면 가운데 크게 보여주며 낭독. (낭독은 시스템이 명언 원문으로 자동 교체 — image_prompt만 작성: 명언의 분위기를 상징하는 고요한 장면, 주인공 동물 등장 가능)
2장면 hook: 시청자를 붙잡는 문장 2줄. 도발적 질문이나 반전 예고. (낭독은 이 2줄을 읽는다)
3~7장면 fable: 주인공 동물이 목표를 갖고 → 실패와 시행착오 → 다른 동물의 조언이나 사건 → 깨달음. 이야기가 흐르게.
8~9장면 real: 우화의 교훈을 현대인의 일상(출근, 공부, 관계, 새벽 루틴, 포기하고 싶은 순간)에 대입.
10장면 outro: 교훈 한 문장 낭독으로 마무리. (낭독은 시스템이 moral로 자동 교체 — image_prompt만 작성)

## 주인공
동물 1마리를 창의적으로 정하고 `characters`에 영어 외형 묘사를 한 줄로 쓴다.
(예: "a small white rabbit with a red scarf"). 이 묘사는 모든 이미지 프롬프트에
자동 삽입되므로 장면 묘사에 반복할 필요 없다.

## 규칙
- narration: 각 언어당 1~2문장, 낭독 6~8초 분량(짧고 아주 자연스럽게). 구어체.
- subtitle: 화면 하단 자막. ko/zh-cn 16자 이내, en/fr 42자 이내.
- image_prompt: 영문. 해당 장면의 상황을 그림으로. 주인공 동물이 등장하는 행동 묘사. 텍스트·글자 없는 그림.
- hook.lines: 각 언어 2줄. 한 줄당 ko/zh-cn 16자, en/fr 40자 이내.
- hook.highlight: lines 안에 실제로 포함된 강조 단어 1개(주황색 표시용). 각 언어별.
- moral: 아웃트로 카드에 크게 띄울 교훈 문장. 각 언어 1문장, 낭독 5~7초.
- title: 각 언어 짧은 제목.
- caption: 각 언어 게시 캡션 — 첫 줄은 제목(유튜브 제목으로 쓰임), 이어서 우화 한 줄 요약 + 질문. 해시태그는 넣지 마라(자동 추가됨).

순수 JSON 하나만 반환하라:
""" + _SCHEMA_EXAMPLE

    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


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
    """명언 → 우화 스토리 JSON. mock=True 면 고정 샘플(파이프라인 점검용)."""
    if mock or not os.getenv("DEEPSEEK_API_KEY"):
        return _validate(_mock_story(quote, theme), quote, theme)
    last_err: Exception = RuntimeError("생성 실패")
    for attempt in (1, 2, 3):
        resp = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}",
                     "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": _build_messages(quote, theme),
                "response_format": {"type": "json_object"},
                "temperature": 0.9,
                "max_tokens": 5000,
            },
            timeout=240,
        )
        resp.raise_for_status()
        try:
            data = _extract_json(resp.json()["choices"][0]["message"]["content"])
            return _validate(data, quote, theme)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            last_err = e
            print(f"  [fable] 스토리 파싱 실패 (시도 {attempt}/3): {e}")
    raise last_err


# ─────────────────────────────────────────────────────────────
# 검증 + 코드 강제 사항
# ─────────────────────────────────────────────────────────────
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

    # ── 코드 강제: 확정된 대사/프롬프트로 덮어쓴다 ──
    for i, sc in enumerate(scenes):
        # 1) 명언 오프닝(quote) 낭독 = 명언 원문 + 화자 (은행 값 그대로 — 윤색 금지)
        if sc["act"] == "quote":
            for lang in LANGS:
                author = quote.author_of(lang)
                qt = quote.text_of(lang).strip().rstrip(".")   # 마침표 중복 방지
                sc["narration"][lang] = (f"{qt}. — {author}." if author else f"{qt}.")
        # 2) 훅 장면 낭독 = 훅 2줄 그대로 읽기 (화면 텍스트·음성 일치 보장)
        if sc["act"] == "hook":
            for lang in LANGS:
                sc["narration"][lang] = " ".join(hook["lines"][lang])
        # 3) 아웃트로 낭독 = 교훈 문장 (quote 는 이미 오프닝에서 낭독됨)
        if sc["act"] == "outro":
            for lang in LANGS:
                sc["narration"][lang] = moral[lang]
        # 4) 이미지 프롬프트 일관성 — 스타일 + 주인공 외형 강제 삽입
        p = str(sc["image_prompt"]).strip().rstrip(".")
        sc["image_prompt"] = f"{STYLE_PREFIX}, {characters}, {p}, {STYLE_SUFFIX}"

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
    return story


def save_story(story: dict, data_dir: Path) -> Path:
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
            "n1": "작은 토끼 한 마리가 언덕 위 해돋이를 보고 싶었어요.",
            "n2": "첫날은 씩씩하게 뛰어 올라갔지만, 곧 숨이 차서 주저앉고 말았죠.",
            "n3": "다람쥐가 말했어요. 한 번에 다 오르려 하지 말고, 아침마다 조금씩만 가보라고.",
            "n4": "토끼는 사흘간 비를 맞으며, 포기하고 싶은 마음과 싸웠어요.",
            "n5": "그리고 어느 새벽, 문득 정상이 눈앞에 있었어요.",
            "n6": "언덕 위에서 본 해돋이는, 상상보다 훨씬 컸답니다.",
            "n7": "당신의 언덕도 마찬가지예요. 오늘 딱 한 걸음만 더 디디면 돼요.",
            "n8": "큰 성공은 결국, 작은 걸음이 쌓인 날 옵니다.",
            "n9": "outro",
            "t": "토끼와 높은 언덕",
            "s": ["오늘의 명언", "해돋이를 보고 싶었어", "숨이 차서 주저앉고 말았죠", "조금씩만 가보라고",
                  "포기하고 싶은 마음과 싸웠어요", "정상이 눈앞에 있었어요", "해돋이는 더 컸어요",
                  "한 걸음만 더", "작은 걸음이 쌓여요", "매일 한 걸음씩"],
        },
        "en": {
            "h1": "The rabbit dreamed of the sunrise", "h2": "but gave up halfway, every single day",
            "hl": "gave up",
            "n1": "A little rabbit wanted to see the sunrise from the top of the hill.",
            "n2": "On day one she sprinted up — and collapsed, out of breath.",
            "n3": "A squirrel told her: don't climb it all at once. Just a little, every morning.",
            "n4": "For three rainy days she fought the urge to quit.",
            "n5": "Then one dawn, the summit was suddenly right there.",
            "n6": "The sunrise from the top was bigger than she had imagined.",
            "n7": "Your hill is the same. Just one more small step today.",
            "n8": "Big wins arrive on the day small steps pile up.",
            "n9": "outro",
            "t": "The Rabbit and the Tall Hill",
            "s": ["TODAY'S QUOTE", "She wanted the sunrise", "She collapsed, out of breath", "A little, every morning",
                  "Fighting the urge to quit", "The summit, suddenly near", "Bigger than imagined",
                  "One more step", "Small steps pile up", "One step a day"],
        },
        "zh-cn": {
            "h1": "兔子每天都梦想着山上的日出", "h2": "却每次都在半路放弃",
            "hl": "放弃",
            "n1": "一只小兔子想看山坡上的日出。",
            "n2": "第一天它猛地往上冲，很快就喘得坐在了地上。",
            "n3": "松鼠告诉它：别想一次登顶，每天早上只走一点点。",
            "n4": "连着三个雨天，它和想放弃的念头搏斗着。",
            "n5": "然后某个清晨，山顶忽然就在眼前了。",
            "n6": "山顶的日出，比它想象的还要大。",
            "n7": "你的山坡也一样。今天只要再多走一步。",
            "n8": "大的成功，是小步子垒起来的那天到来的。",
            "n9": "outro",
            "t": "兔子与高高的山坡",
            "s": ["今日名言", "想看日出的兔子", "喘得坐在地上", "每天只走一点点",
                  "和放弃的念头搏斗", "山顶就在眼前", "比想象更大",
                  "再多走一步", "小步子垒起来", "每天一小步"],
        },
        "fr": {
            "h1": "Le lapin rêvait du lever de soleil", "h2": "mais abandonnait à mi-chemin, chaque jour",
            "hl": "abandonnait",
            "n1": "Un petit lapin voulait voir le lever du soleil du haut de la colline.",
            "n2": "Le premier jour, il grimpa à toute vitesse — et s'effondra, essoufflé.",
            "n3": "Un écureuil lui dit : n'essaie pas tout d'un coup. Un peu, chaque matin.",
            "n4": "Pendant trois jours de pluie, il lutta contre l'envie d'abandonner.",
            "n5": "Puis un matin, le sommet était soudain juste là.",
            "n6": "Le lever de soleil vu d'en haut était plus grand qu'il ne l'avait imaginé.",
            "n7": "Ta colline est pareille. Juste un petit pas de plus, aujourd'hui.",
            "n8": "Les grandes victoires arrivent le jour où les petits pas s'additionnent.",
            "n9": "outro",
            "t": "Le Lapin et la Grande Colline",
            "s": ["CITATION DU JOUR", "Il voulait le lever du soleil", "Essoufflé, il s'effondre", "Un peu, chaque matin",
                  "Lutter contre l'envie d'abandonner", "Le sommet, soudain proche", "Plus grand qu'imaginé",
                  "Un pas de plus", "Les petits pas s'additionnent", "Un pas par jour"],
        },
    }
    prompts = [
        "a small white rabbit with a red scarf sitting quietly on a mossy stone at dawn, watching the horizon, soft golden light",
        "the rabbit sprinting up the hillside, determined, morning light",
        "the rabbit sitting exhausted halfway up the path, catching breath",
        "a friendly squirrel talking to the rabbit on a tree branch",
        "the rabbit walking slowly in the rain, holding a big leaf over the head",
        "the rabbit reaching the hilltop at first light, arms open",
        "a vast golden sunrise seen from the hilltop, the rabbit small in the frame",
        "a quiet modern desk at dawn, notebook and a cup of tea, city lights outside the window",
        "a person silhouette climbing stairs at sunrise, warm light from above",
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
            "ko": "매일 한 걸음씩 오른 사람만, 정상의 아침을 봅니다.",
            "en": "Only those who climb a little every day see the morning at the top.",
            "zh-cn": "每天多走一步的人，才能看到山顶的早晨。",
            "fr": "Seuls ceux qui grimpent un peu chaque jour voient le matin au sommet.",
        },
        "characters": "a small white rabbit with a red scarf",
        "scenes": scenes,
    }
