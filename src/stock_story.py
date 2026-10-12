"""증권편 대본 생성 — 나스닥 시총 TOP 10 중 1개사의 "성공 이유". 08:07 슬롯.

2026-10-11 전면 재작성.
이전 버전의 문제:
  1. 프롬프트를 파일 안에 따로 들고 있어 참고 채널 규칙이 미적용
     → 실측: "오늘 다룰 회사는 애플이다. 티커는 AAPL, 나스닥 시총 2위다."
       (보고서체 — 참고 채널과 정반대)
  2. COMPANY_ANCHORS 텍스트가 깨져 있었다 (실측):
     - "服务器市場을 넓혀가고 있다"      ← 중국어 혼입
     - "반도체angg MIS/mo의 선구자다"   ← 무작위 문자
     - "AbbVie는백신·、医药품을 만든다" ← 중국어 혼입
     LLM 이 생성한 앵커를 검증 없이 넣은 결과. 전부 걷어냈다.

→ 이제 규칙은 story_core 가 갖고, 여긴 **실사 데이터(소재)만** 공급한다.
"""
from __future__ import annotations

import os
import random

from src import nasdaq, story_core

LANGS = story_core.LANGS

SYSTEM = ("당신은 기업의 성공 구조를 관찰해 짧게 풀어내는 쇼츠 대본 작가다. "
          "증권 리포트처럼 쓰지 않는다. 숫자를 나열하지 않고 장면을 던진다.")

# ⭐ LLM 환각 방지 앵커 — 2026-10-11 전부 재검수.
# 규칙: 한국어만. 이물질(중국어·영문 무작위) 절대 금지. 한 줄 요약만.
COMPANY_ANCHORS: dict[str, str] = {
    "NVDA":  "AI 학습과 그래픽 처리에 쓰는 반도체를 설계한다.",
    "AAPL":  "아이폰·맥·웨어러블을 만들고 서비스로 묶어 충성 고객을 만든다.",
    "MSFT":  "운영체제·오피스·클라우드를 기업에 판매한다.",
    "GOOGL": "검색 광고로 수익을 얻고 유튜브·클라우드를 함께 운영한다.",
    "GOOG":  "검색 광고로 수익을 얻고 유튜브·클라우드를 함께 운영한다.",
    "AMZN":  "전자상거래와 클라우드, 구독 서비스를 운영한다.",
    "META":  "소셜 네트워크를 운영하며 광고 수익으로 AI에 투자한다.",
    "AVGO":  "데이터센터용 맞춤 반도체와 인프라 소프트웨어를 판다.",
    "TSLA":  "전기차와 에너지 저장 장치를 만들고 자율주행을 개발한다.",
    "AMD":   "CPU와 GPU를 설계하며 데이터센터 시장을 넓히고 있다.",
    "NFLX":  "구독형 스트리밍 서비스를 운영하고 자체 콘텐츠를 만든다.",
    "COST":  "회원제 창고형 할인점을 운영한다.",
    "ADBE":  "사진·영상·문서 편집 소프트웨어를 만든다.",
    "QCOM":  "스마트폰용 칩과 이동통신 기술을 만든다.",
    "TXN":   "아날로그 반도체를 만들어 산업·자동차에 공급한다.",
    "ORCL":  "데이터베이스와 기업용 클라우드를 운영한다.",
    "CRM":   "고객 관리와 영업용 소프트웨어를 제공한다.",
    "PLTR":  "정부·기업용 데이터 분석 플랫폼을 만든다.",
    "INTC":  "반도체를 설계하고 직접 생산까지 하는 몇 안 되는 회사다.",
    "TSM":   "다른 회사가 설계한 반도체를 대신 만들어 주는 전문 공장이다.",
}


def _anchor(sym: str) -> str:
    for k in (sym, sym.strip(), sym.upper()):
        if k in COMPANY_ANCHORS:
            return COMPANY_ANCHORS[k]
    return ""


def _facts_block(company: dict) -> str:
    """nasdaq.py 실측 데이터 → LLM 에 넘길 소재 블록."""
    sym = str(company.get("symbol", "")).strip()
    lines = [
        f"티커: {sym}",
        f"회사명: {company.get('name', '')}",
    ]
    mc = company.get("market_cap")
    if mc:
        lines.append(f"시가총액: {mc / 1e12:.2f}조 달러 "
                     f"(나스닥 {company.get('rank', '?')}위)")
    if company.get("price") is not None:
        lines.append(f"현재 주가: ${company['price']}")
    g = company.get("growth_3y")
    if g is not None:
        lines.append(f"3년 주가 변화: {g:+.0f}%")
    if company.get("industry"):
        lines.append(f"산업: {company.get('sector', '')} / {company['industry']}")
    anchor = _anchor(sym)
    if anchor:
        lines.append(f"무엇을 하는 회사인가: {anchor}")
    s = company.get("summary")
    if s:
        lines.append(f"회사 소개: {str(s)[:400]}")
    return "\n".join(lines)


def generate(date: str, mock: bool = False,
             seed: int | None = None) -> dict:
    """증권편 대본 생성 → story.json 구조."""
    rng = random.Random(seed) if seed is not None else random.Random()

    company = nasdaq.pick_one(rng=rng)
    if not company:
        raise RuntimeError("나스닥 TOP10 조회 실패 — 증권편 생성 불가")

    if mock or not os.getenv("DEEPSEEK_API_KEY"):
        return _mock(company, date)

    topic = (
        f"# 오늘 관찰할 회사\n{_facts_block(company)}\n\n"
        "이 회사가 **왜 여기까지 왔는지** 를 다룬다.\n\n"
        "규칙:\n"
        "- 기업 홍보문·IR 자료처럼 쓰지 마라.\n"
        "- 시총·주가 숫자는 1장면에서 한 번만, 짧게 언급한다. "
        "나머지는 장면으로 보여라.\n"
        "- '이 회사처럼 하라' 는 식의 조언 금지.\n"
        "- 투자 권유·매수 추천으로 읽히는 표현 절대 금지.\n"
        "- 화자는 이 회사를 **멀리서 관찰한 사람**이다."
    )

    data = story_core.generate(SYSTEM, topic, verbose=True)

    sym = str(company.get("symbol", "")).strip()
    data["date"] = date
    data["theme"] = "stocks"
    data["symbol"] = sym
    data["quote"] = {"text": company.get("name", sym), "author": f"NASDAQ {sym}"}
    return data


def _mock(company: dict, date: str) -> dict:
    sym = str(company.get("symbol", "")).strip()
    name = company.get("name", sym)
    scenes = []
    for act, _ in story_core.SCENE_PLAN:
        scenes.append({
            "act": act,
            "subtitle": {k: name for k in LANGS},
            "narration": {k: f"{name}." for k in LANGS},
            "image_prompt": story_core._image_prompt("", act),
        })
    return {
        "title": {k: name for k in LANGS},
        "caption": {k: f"{name} ({sym})" for k in LANGS},
        "hook": {"lines": {k: [name, "Look closer."] for k in LANGS},
                 "highlight": {k: sym for k in LANGS}},
        "moral": {k: "Small moves compound." for k in LANGS},
        "cta": {k: "Follow for more." for k in LANGS},
        "scenes": scenes,
        "date": date, "theme": "stocks", "symbol": sym,
        "quote": {"text": name, "author": f"NASDAQ {sym}"},
        "naturalness_issues": ["mock"],
    }


if __name__ == "__main__":
    import json
    import sys
    d = generate(date=sys.argv[1] if len(sys.argv) > 1 else "2026-10-17",
                 mock="--mock" in sys.argv)
    print(json.dumps({"symbol": d.get("symbol"),
                      "issues": d.get("naturalness_issues"),
                      "hook": d["hook"]["lines"]["ko"],
                      "moral": d["moral"]["ko"]},
                     ensure_ascii=False, indent=2))
