"""증권편 대본 생성 — 나스닥 시총 TOP 10 중 무작위 1개사의 "성공 이유".

2026-10-10 신설. fable_story 와 같은 story.json 구조를 만들어
fablevideo.make_fable() 이 그대로 렌더할 수 있게 한다.
"""
from __future__ import annotations

import os
import random
import re

import requests

from src import nasdaq

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"

STYLE = ("black and white pencil drawing, monochrome, graphite sketch, "
         "hand-drawn line art, no color, no border, no frame, no text")

# 회사가 무엇을 하는지 한 줄 요약 (티커별 — LLM 환각 방지용 앵커)
COMPANY_ANCHORS = {
    "NVDA": "GPU(그래픽 처리 장치)와 AI 가속 칩을 설계한다. "
            "게임·데이터센터·AI 학습에 쓰인다.",
    "AAPL": "아이폰·아이패드·맥을 만들고 애플 생태계를 운영한다. "
            "하드웨어와 서비스를 묶어 충성 고객을 만든다.",
    "MSFT": "윈도우·오피스와 클라우드(Azure)를 운영한다. "
            "기업용 소프트웨어와 AI를 함께 팔는다.",
    "GOOGL": "검색 엔진과 광고로 돈을 버는 인터넷 기업이다. "
             " 유튜브와 안드로이드, 클라우드도 운영한다.",
    "GOOG": "검색 엔진과 광고로 돈을 버는 인터넷 기업이다. "
             "유튜브와 안드로이드, 클라우드도 운영한다.",
    "AMZN": "온라인 쇼핑몰과 클라우드 사업, Prime 구독을 운영한다.",
    "META": "페이스북·인스타그램 등 소셜 네트워크를 운영한다. "
            "광고로 수익을 얻고 AI 투자에 시간을 쓴다.",
    "AVGO": "반도체와 소프트웨어를 함께 파는 회사다. "
            "데이터센터용 커스텀 칩을 만든다.",
    "TSLA": "전기 자동차와 에너지 저장 장치를 만든다. "
            "자율주행 소프트웨어에도 투자한다.",
    "MU": "메모리 반도체(DRAM·NAND)를 만든다. "
          ".smartphone·PC·데이터센터가 주된 고객이다.",
    "AMD": "CPU·GPU 등 프로세서를 만든다. "
           "인텔의 경쟁자로服务器市場을 넓혀가고 있다.",
    "NFLX": "넷플릭스 스트리밍 서비스를 운영한다.",
    "COST": "창고형 회원제 할인점(코스트코)을 운영한다.",
    "ADBE": "포토샵 등 창작·디자인 소프트웨어를 만든다.",
    "INTC": "컴퓨터.cpu를 만든다. 반도체angg MIS/mo의 선구자다.",
    "CSCO": "라우터·스위치 등 네트워크 장비를 만든다.",
    "QCOM": "스마트폰용 칩과 무선 통신 기술을 만든다.",
    "TXN": "아날로그 반도체를 만든다. 산업·차량용이 주력이다.",
    "AMD ": "프로세서를 만든다.",
    "ORCL": "데이터베이스와 기업용 클라우드 서비스를 운영한다.",
    "AMGN": "바이오 의약품 회사로 항암제를 개발·판매한다.",
    "PLTR": "데이터 분석 소프트웨어를 만든다. AI 도구를 제공한다.",
    "CRM": "고객 관리 소프트웨어를 만든다.",
    "UBER": "택시·배달 플랫폼을 운영한다.",
    "ABBV": "AbbVie,Including AbbVie는백신·、医药품을 만든다.",
    "PFE": "Pfizer, 제약·백신 회사다.",
    "CMCSA": "케이블 통신과 인터넷 인프라를 운영한다.",
    "HON": "에어컨·공기조화 장비를 만든다.",
    "VRTX": "바이오 회사다. Vertex, 희귀질환 신약을 만든다.",
    "ISRG": "로봇 수술 장비를 만든다. Intuitive Surgical.",
    "BKNG": "온라인 여행 예약 사이트를 운영한다.",
    "TSM ": "반도체를 fab로 만드는 회사로 TSMC,，代工를 맡는다.",
    "TSM": "반도체 제조 전문(foundry) 회사다. TSMC, "
           "다른 칩 회사가 설계한 것을 실제로 만들어 준다.",
}

# 장면 구성 — 각 장면의 역할과 이미지 검색 키워드
ACTS = [
    ("hook",    "오늘 다룰 회사를 제시한다"),
    ("scale",   "규모를 수치로 보여준다"),
    ("what",    "무엇을 파는지 설명한다"),
    ("why",     "왜 잘 팔렸는지 1가지"),
    ("risk",    "어려웠던 시기를 언급한다"),
    ("turn",    "돌아든 전환점을 말한다"),
    ("moat",    "복잡한 경쟁우위를 말한다"),
    ("lesson",  "배울 교훈을 준다"),
    ("act",     "구체적 행동을 지시한다"),
]

# act 별 이미지 검색 키워드 — LLM이 image_prompt 를 누락해도
# 장면 맥락에 맞는 실사 사진을 찾을 수 있게 하는 안전망.
ACT_IMAGES = {
    "hook":    "corporate headquarters building exterior",
    "scale":   "aerial view city skyline skyscrapers",
    "what":    "modern factory production line",
    "why":     "retail store customers shopping",
    "risk":    "empty industrial warehouse interior",
    "turn":    "server room data center corridor",
    "moat":    "network cables connection technology",
    "lesson":  "old notebook handwritten planning desk",
    "act":     "person writing notes notebook desk",
}


def _anchor(sym: str) -> str:
    return COMPANY_ANCHORS.get(sym, COMPANY_ANCHORS.get(sym.strip(), ""))


def build_prompt(company: dict) -> list[dict]:
    """DeepSeek 프롬프트 — 4개 언어 대본을 한 번에 생성."""
    sym = company["symbol"]
    anchor = _anchor(sym)
    facts = (
        f"티커: {sym}\n"
        f"회사명: {company['name']}\n"
        f"시총: {company['market_cap']/1e12:.2f}조 달러 "
        f"(나스닥 전체 {company.get('rank', '?')}위)\n"
        f"현재 주가: ${company.get('price')}\n"
    )
    g = company.get("growth_3y")
    if g is not None:
        facts += f"3년 주가 변화: {g:+.0f}%\n"
    if company.get("industry"):
        facts += f"섹터/산업: {company['sector']} / {company['industry']}\n"
    if company.get("summary"):
        facts += f"회사 소개: {company['summary'][:500]}\n"

    schema = """
반드시 아래 JSON 형식으로만 답하라. 설명문·코드블록 없이 JSON 만.

{
  "title": {"ko":"...","en":"...","zh-cn":"...","fr":"..."},
  "caption": {"ko":"...","en":"...","zh-cn":"...","fr":"..."},
  "hook": {
    "lines": {"ko":["한 문장","한 문장"],"en":[...],"zh-cn":[...],"fr":[...]},
    "highlight": {"ko":"강조할 단어","en":"...","zh-cn":"...","fr":"..."}
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
1. **4개 언어(ko/en/zh-cn/fr) 모두 작성.** 각 언어는 그 언어의 자연스러운 문장으로.
2. **한국어 존댓말을 쓰지 말고 해라체·명사형 위주.** 예: "그는 ~했다", "그 회사는 ~했다".
   ('~하세요' 같은 해라체를 쓰면 실패다.)
3. **구어체.** "~입니다" 금지. "~한다" "~했다" "~이다" "~이었다" 로 끝나라.
4. 각 장면 narration 은 2~3문장, 총 60~100자 내외. 짧을수록 낭독이 자연스럽다.
5. **subscribe/구독 유도 금지.** 행동 지시만 넣는다 (예: "오늘 그 회사의 수치를 찾아봐라").
6. **투자 권유 금지.** 어떤 주식을 사라고 말하지 마라. 성공 요인 관찰로 끝낸다.
7. 사실이 모르는 수치·연도·실명은 절대 만들어내지 마라. 주어진 정보만 쓴다.
8. hook.lines 는 짧고 강한 2문장. 첫 문장이 시선을 잡아야 한다.
9. moral 은 구사절. **명령형("~해라") 으로 끝내지 마라.**
   반지나 단정으로 끝낸다. 예: "팔리는 회사와 오래가는 회사는 다르다.
   둘을 가르는 건 속도가 아니라 반복이다."
   ❌ "오늘 그 회사의 수치를 찾아봐라." (이건 명령형이라 실패)
10. 각 언어의 톤은 그 언어의 문화에 맞게 (영어는 impactful, 중국어는 간결하고 강한).
"""
    user = (
        f"다음 회사의 '성공 이유'를 다루는 9장면 쇼츠 대본을 써라.\n\n"
        f"{facts}\n"
        f"[이 회사에 대한 확인된 정보 — 반드시 근거로만 사용]\n{anchor}\n"
        f"{rules}\n"
        f"장면 구성(순서 고정):\n"
        + "\n".join(f"  {i+1}. act='{a}' — {d}" for i, (a, d) in enumerate(ACTS))
        + f"\n\n{schema}"
    )
    return [{"role": "system",
             "content": "당신은 경제·기업 분석을 전문으로 하는 쇼츠 대본 작가다."},
            {"role": "user", "content": user}]


def _extract_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    for cand in (t,):
        try:
            return __import__("json").loads(cand)
        except Exception:  # noqa: BLE001
            pass
    # { } 가장 바깥 부분만
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        return __import__("json").loads(t[i:j + 1])
    raise ValueError("JSON 파싱 실패")


def generate(date: str, mock: bool = False,
             seed: int | None = None) -> dict:
    """증권편 대본 생성 → story.json 구조로 반환."""
    rng = random.Random(seed) if seed is not None else random.Random()
    company = nasdaq.pick_one(rng)
    if company is None:
        raise RuntimeError("야후 API 조회 실패 — NASDAQ TOP 10 을 못 가져왔다")

    ranks = {r["symbol"]: i + 1 for i, r in enumerate(nasdaq.top10())}
    company["rank"] = ranks.get(company["symbol"], "?")

    if mock or not os.getenv("DEEPSEEK_API_KEY"):
        data = _mock(company)
    else:
        r = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}"},
            json={"model": MODEL, "max_tokens": 16000,
                  "messages": build_prompt(company),
                  "response_format": {"type": "json_object"}},
            timeout=300)
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
        data = _extract_json(raw)

    data["date"] = date
    data["theme"] = "stocks"
    data["theme_label"] = "나스닥 시총 TOP 10"
    data["quote"] = {"text": f"{company['symbol']} — {company['name']}",
                     "author": "NASDAQ TOP 10"}
    data["characters"] = company["name"]
    # LLM 이 image_prompt 를 누락하는 경우가 있어 act 기반으로 채운다.
    # (make_fable 이 sc["image_prompt"] 를 필수로 읽으므로 KeyError 방지)
    for sc in data.get("scenes", []):
        if not sc.get("image_prompt"):
            sc["image_prompt"] = f"{STYLE}, {ACT_IMAGES.get(sc.get('act'), 'business office')}"
    data["stock_company"] = company["symbol"]
    data["stock_company_name"] = company["name"]
    data["stock_market_cap"] = company["market_cap"]
    data["stock_price"] = company.get("price")
    data["stock_growth_3y"] = company.get("growth_3y")
    data["stock_rank"] = company.get("rank")
    data["naturalness_issues"] = []
    return data


def _mock(company: dict) -> dict:
    """키가 없을 때 쓰는 최소 구조."""
    sym = company["symbol"]
    langs = ["ko", "en", "zh-cn", "fr"]
    out = {
        "title": {"ko": f"{sym}의 성공", "en": f"{sym} success",
                  "zh-cn": f"{sym} 的成功", "fr": f"{sym} reussite"},
        "caption": {k: f"{sym} story." for k in langs},
        "hook": {"lines": {k: [f"{sym}", "Watch this."] for k in langs},
                 "highlight": {k: sym for k in langs}},
        "moral": {k: "Observe, then act." for k in langs},
        "cta": {k: "Follow for more." for k in langs},
        "scenes": [],
    }
    for i, (act, _) in enumerate(ACTS):
        out["scenes"].append({
            "act": act,
            "subtitle": {k: f"{sym}" for k in langs},
            "narration": {k: f"{company['name']} scene {i+1}." for k in langs},
            "image_prompt": f"{STYLE}, {sym} company office",
        })
    return out


if __name__ == "__main__":
    import json
    import sys
    d = generate(date="test", mock="--mock" in sys.argv)
    print(json.dumps({k: v for k, v in d.items()
                      if k in ("title", "hook", "moral", "stock_company")},
                     ensure_ascii=False, indent=2)[:1200])