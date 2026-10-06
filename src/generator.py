"""DeepSeek API 단일 호출로 4개 언어 콘텐츠 생성."""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests
import yaml

from .quotes import Quote, THEME_LABELS

LANGS = ["en", "ko", "zh-cn", "fr"]
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
THREADS_LIMIT = 300  # Bluesky 기준(3개 텍스트 플랫폼 중 가장 짧은 제한)
DEFAULT_TAGS = {
    "en": "#wisdom #quoteoftheday #lifelessons",
    "ko": "#명언 #오늘의문장 #배움",
    "zh-cn": "#名言 #今日一句 #感悟",
    "fr": "#citation #sagesse #lecondevie",
}
# 사이클별 주제 — 명언 풀에서 이 테마에 맞는 명언을 고른다.
THEME_BY_CYCLE = {
    "am": "growth",
    "pm": "courage",
    "ev": "hardship",
    "night": "attitude",
}

# 허브-스포크: 스포크 플랫폼 말미에 자동 추가되는 IG 유도 CTA (config/handles.yaml의 핸들 사용)
CTA_TEMPLATES = {
    "en": "\n\nThe rest of it is on IG @{h}",
    "ko": "\n\n나머지 글귀는 IG @{h}에서 볼 수 있어요",
    "zh-cn": "\n\n完整内容见 IG @{h}",
    "fr": "\n\nLe reste est sur IG : @{h}",
}


def load_handles(config_dir: Path) -> dict[str, str]:
    data = yaml.safe_load((config_dir / "handles.yaml").read_text(encoding="utf-8"))
    handles = data["ig_handles"]
    missing = [l for l in LANGS if l not in handles]
    if missing:
        raise ValueError(f"handles.yaml에 {missing} 핸들 누락")
    return handles


def _load_prompts(prompts_dir: Path) -> tuple[str, dict[str, str]]:
    base = (prompts_dir / "base.md").read_text(encoding="utf-8")
    rules = {l: (prompts_dir / f"{l}.md").read_text(encoding="utf-8") for l in LANGS}
    return base, rules


def _build_messages(quote: Quote, prompts_dir: Path, theme: str | None = None) -> list[dict]:
    base, rules = _load_prompts(prompts_dir)
    lang_rules = "\n\n".join(f"### {l}\n{rules[l]}" for l in LANGS)
    system = f"{base}\n\n## 언어별 작성 규칙\n{lang_rules}"

    quote_block = "\n\n".join(
        f"### {l}\n- 명언 원문: {quote.text_of(l)}\n- 화자 표기: {quote.author_of(l)}"
        for l in LANGS)
    theme_label = THEME_LABELS.get(theme or "", theme or "")
    user = (
        f"## 오늘의 테마\n{theme_label}\n\n"
        f"## 오늘의 명언 (반드시 이 문장 그대로 사용)\n{quote_block}\n\n"
        "각 언어의 ig_cards[0] 에는 위 명언 원문을, quote_author 에는 위 화자 표기를 "
        "**한 글자도 바꾸지 말고** 그대로 넣어라. (번역·윤색·축약 금지)\n"
        "그 명언을 오늘의 언어로 풀어 2~5번 카드(쉬운 풀이 → 일상 예시 → 오늘 한 가지 → 질문)를 "
        "base 프롬프트 규칙대로 작성하고 4개 언어 콘텐츠 JSON을 생성하라."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _extract_json(text: str) -> dict:
    """응답에서 JSON 본문 추출 — 코드펜스나 앞뒤 잡문을 허용한다."""
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


def generate(quote: Quote, prompts_dir: Path, mock: bool = False,
             theme: str | None = None) -> dict[str, dict]:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if mock or not api_key:
        return _mock_generate(quote)
    last_err: Exception = RuntimeError("생성 실패")
    for attempt in (1, 2):  # 간헐적 깨진 JSON 응답 방어: 1회 재시도
        resp = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": _build_messages(quote, prompts_dir, theme),
                "response_format": {"type": "json_object"},
                "temperature": 0.8,
            },
            timeout=180,
        )
        resp.raise_for_status()
        try:
            data = _extract_json(resp.json()["choices"][0]["message"]["content"])
            return _validate(data, prompts_dir.parent, quote)
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            print(f"DeepSeek 응답 파싱 실패 (시도 {attempt}/2): {e}")
    raise last_err


def _validate(data: dict, config_dir: Path, quote: Quote | None = None) -> dict[str, dict]:
    handles = load_handles(config_dir)
    for lang in LANGS:
        if lang not in data or not isinstance(data[lang], dict):
            raise ValueError(f"생성 결과에 {lang} 누락")
        c = data[lang]
        for key in ("ig_caption", "ig_cards", "threads_text"):
            if key not in c:
                raise ValueError(f"{lang}.{key} 누락")
        cards = [str(t).strip() for t in c["ig_cards"] if str(t).strip()]
        if not 4 <= len(cards) <= 6:
            raise ValueError(f"{lang}.ig_cards 장수 오류: {len(cards)}장 (4~6장 필요)")
        c["ig_cards"] = cards
        # 명언 화자: 1장 카드에 표기. 없으면 빈 문자열(표기 생략)
        c["quote_author"] = str(c.get("quote_author") or "").strip()
        # ── 명언 고정: 모델이 원문을 윤색했어도 은행의 문장·화자로 되돌린다 ──
        if quote is not None:
            c["ig_cards"][0] = quote.text_of(lang)
            c["quote_author"] = quote.author_of(lang)
        # 티저 캡션: 미생성 시 IG 캡션으로 폴백 후 CTA 자동 추가
        c["teaser_caption"] = str(c.get("teaser_caption") or c["ig_caption"]).rstrip()
        c["teaser_caption"] += CTA_TEMPLATES[lang].format(h=handles[lang])
        # 숏 티저: CTA 포함 300자 이내 보정
        handle = handles[lang]
        cta = CTA_TEMPLATES[lang].format(h=handle)
        body = str(c["threads_text"]).rstrip()
        if handle not in body:  # 모델이 CTA를 직접 안 쓴 경우에만 자동 추가
            if len(body) + len(cta) > THREADS_LIMIT:
                body = body[: THREADS_LIMIT - len(cta)].rstrip()
            body += cta
        c["threads_text"] = body[:THREADS_LIMIT]
        # 캡션에 해시태그 누락 시 기본 태그 보정 (PRD: 캡션 = 요약+질문+해시태그)
        if "#" not in c["ig_caption"]:
            c["ig_caption"] = c["ig_caption"].rstrip() + "\n\n" + DEFAULT_TAGS[lang]
        # Reels 나레이션 대본: 누락 시 카드 앞부분으로 폴백 (TTS 파이프라인 안전장치)
        script = str(c.get("reels_script") or "").strip()
        if not script:
            script = " ".join(cards[:3])
        c["reels_script"] = script
    return {l: data[l] for l in LANGS}


def _mock_generate(quote: Quote) -> dict[str, dict]:
    """API 키 없이 전체 파이프라인을 검증하기 위한 목 콘텐츠.

    은행에서 고른 명언(언어별 원문)을 1장에 그대로 얹고, 나머지 4장을 붙인다.
    """
    base = Path(__file__).resolve().parent.parent / "config"
    T = {
        "en": {
            "cap": "Today's line, and what it means on an ordinary day. #wisdom #quotes",
            "plain": "In plain words: a setback is information, not a verdict.",
            "scene": "You sent the email with a typo in it and spent an hour replaying it.",
            "act": "Note one line today: what that mistake taught you.",
            "ask": "What did the last thing you got wrong leave you with?",
            "thr": "A setback is information, not a verdict. What did the last thing you got wrong leave you with?",
        },
        "ko": {
            "cap": "오늘의 문장 하나, 그리고 평범한 하루에서의 뜻. #명언 #오늘의문장",
            "plain": "쉽게 말하면, 막힌 건 실패가 아니라 정보예요.",
            "scene": "오타 난 메일을 보내고 나서 한 시간 동안 그 문장만 다시 읽었어요.",
            "act": "오늘 그 일에서 건진 것 한 줄만 적어보세요.",
            "ask": "여러분이 마지막으로 틀린 일에서 남은 건 뭐였어요?",
            "thr": "막힌 건 실패가 아니라 정보예요. 여러분이 마지막으로 틀린 일에서 남은 건 뭐였어요?",
        },
        "zh-cn": {
            "cap": "今天的一句话，以及在平常日子里它的意思。#名言 #今日一句",
            "plain": "说白了：卡住不是失败，只是得到一条信息。",
            "scene": "邮件里打错一个字，发完之后反复看了整整一小时。",
            "act": "今天只写一句：这件事教会了我什么。",
            "ask": "你上次做的事最后给你留下了什么？",
            "thr": "卡住不是失败，只是得到一条信息。你上次做错的事，留下了什么给你？",
        },
        "fr": {
            "cap": "Une ligne pour aujourd'hui, et ce qu'elle veut dire un jour ordinaire. #citation #sagesse",
            "plain": "En clair : un blocage est une information, pas un verdict.",
            "scene": "Tu as envoyé le mail avec une faute, puis tu l'as relu pendant une heure.",
            "act": "Écris une seule ligne : ce que cette erreur t'a appris.",
            "ask": "Et toi, qu'est-ce que ta dernière erreur t'a laissé ?",
            "thr": "Un blocage est une information, pas un verdict. Et toi, qu'est-ce que ta dernière erreur t'a laissé ?",
        },
    }
    payload: dict[str, dict] = {}
    for lang in LANGS:
        t = T[lang]
        payload[lang] = {
            "ig_caption": f"{quote.text_of(lang)}\n\n{t['plain']}\n\n{t['ask']}\n\n"
                          + DEFAULT_TAGS[lang],
            "ig_cards": [quote.text_of(lang), t["plain"], t["scene"], t["act"], t["ask"]],
            "quote_author": quote.author_of(lang),
            "teaser_caption": f"{quote.text_of(lang)}\n\n{t['plain']}\n\n{t['ask']}",
            "threads_text": t["thr"],
        }
    return _validate(payload, base, quote)
