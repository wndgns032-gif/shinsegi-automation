"""나스닥 시총 TOP 10 — 무료 실시간 조회 + 무작위 1개 선정.

2026-10-10 실측 검증 완료.
- 인증: 쿠키 → crumb 순서로 발급 (헤더/body 에 crumb 넣으면 401)
- 스크리너 API(POST /v1/finance/screener)는 401 → 티커 목록 + v7 quote 로 대체
- NASDAQ = exchange 'NMS'
"""
from __future__ import annotations

import random
import time

import requests

BASE = "https://query1.finance.yahoo.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 나스닥 시총 상위권 후보 (시총 상위 10 은 항상 이 안에서 나온다)
CANDIDATES = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "AVGO",
    "TSLA", "COST", "NFLX", "AMD", "PEP", "ADBE", "CSCO", "TMUS", "LIN",
    "INTU", "QCOM", "AMGN", "PFE", "BKNG", "TXN", "ISRG", "VRTX", "XOM",
    "CMCSA", "MU", "HON", "UBER", "ABBV", "WMT", "T", "VZ", "LOW", "ORCL",
    "CAT", "CVX", "NEE", "SBUX", "PLTR",
]


def _session() -> tuple[requests.Session, str]:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*"})
    for u in ("https://fc.yahoo.com", "https://finance.yahoo.com/quote/AAPL"):
        try:
            s.get(u, timeout=15)
        except Exception:  # noqa: BLE001
            pass
    crumb = s.get(f"{BASE}/v1/test/getcrumb", timeout=15).text.strip()
    return s, crumb


def top10(tries: int = 3) -> list[dict]:
    """나스닥 시총 TOP 10 (실시간). 실패 시 빈 리스트."""
    for a in range(tries):
        try:
            s, crumb = _session()
            if not crumb or "<" in crumb:
                time.sleep(2)
                continue
            r = s.get(f"{BASE}/v7/finance/quote",
                       params={"symbols": ",".join(CANDIDATES), "crumb": crumb},
                       timeout=30)
            if not r.ok:
                time.sleep(2)
                continue
            rows = []
            for q in r.json()["quoteResponse"]["result"]:
                mc = q.get("marketCap") or 0
                if mc <= 0 or q.get("exchange") != "NMS":
                    continue
                rows.append({
                    "symbol": q.get("symbol"),
                    "name": q.get("longName") or q.get("shortName") or "",
                    "market_cap": mc,
                    "price": q.get("regularMarketPrice"),
                    "change_pct": q.get("regularMarketChangePercent"),
                    "high_52w": q.get("fiftyTwoWeekHigh"),
                    "low_52w": q.get("fiftyTwoWeekLow"),
                })
            rows.sort(key=lambda x: x["market_cap"], reverse=True)
            if len(rows) >= 10:
                return rows[:10]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)
    return []


def profile(symbol: str, tries: int = 3) -> dict:
    """개별 종목 상세 정보 — 사업개요 / 섹터 / 본사."""
    for _ in range(tries):
        try:
            s, crumb = _session()
            r = s.get(f"{BASE}/v10/finance/quoteSummary/{symbol}",
                      params={"modules": "assetProfile,summaryDetail",
                              "crumb": crumb},
                      timeout=25)
            if not r.ok:
                continue
            res = r.json().get("quoteSummary", {}).get("result")
            if not res:
                continue
            ap = res[0].get("assetProfile", {}) or {}
            return {
                "summary": (ap.get("longBusinessSummary") or "")[:700],
                "sector": ap.get("sector") or "",
                "industry": ap.get("industry") or "",
                "city": ap.get("city") or "",
                "country": ap.get("country") or "",
                "employees": ((res[0].get("summaryDetail") or {})
                              .get("fullTimeEmployees") or 0),
            }
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return {}


def growth_3y(symbol: str, tries: int = 2) -> float | None:
    """3년 주가 상승률(%). 실패 시 None."""
    import time as _t
    for _ in range(tries):
        try:
            s, crumb = _session()
            p1 = int(_t.time()) - 3 * 365 * 86400
            p2 = int(_t.time())
            r = s.get(f"{BASE}/v8/finance/chart/{symbol}",
                      params={"period1": p1, "period2": p2,
                              "interval": "1mo", "crumb": crumb},
                      timeout=25)
            if not r.ok:
                continue
            res = r.json()["chart"]["result"][0]
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c]
            if len(closes) >= 12:
                return round((closes[-1] / closes[0] - 1) * 100, 1)
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def pick_one(rng: random.Random | None = None) -> dict | None:
    """TOP 10 중 무작위 1개 + 상세 정보 + 3년 성장률."""
    rows = top10()
    if not rows:
        return None
    rng = rng or random.Random()
    pick = rng.choice(rows)
    info = profile(pick["symbol"])
    pick.update(info)
    pick["growth_3y"] = growth_3y(pick["symbol"])
    return pick


if __name__ == "__main__":
    rows = top10()
    if not rows:
        print("조회 실패")
    else:
        print(f"{'순위':<5}{'티커':<8}{'시총(조)':<11}{'종가':<10}{'3년':<9}회사")
        print("-" * 78)
        for i, r in enumerate(rows, 1):
            g = r.get("growth_3y")
            print(f"{i:<5}{r['symbol']:<8}{r['market_cap']/1e12:<11.2f}"
                  f"{str(r['price']):<10}"
                  f"{(str(g) + '%') if g is not None else '-':<9}"
                  f"{r['name'][:32]}")