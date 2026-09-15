"""미국 재무 수집 - SEC EDGAR frames API.  실행: python collect_us.py

frames 는 "특정 계정 × 특정 기간"을 전 상장사에 대해 한 번에 준다.
그래서 6,000종목 × N지표가 호출 20번 남짓으로 끝난다.
받은 원본 JSON 은 cache/ 에 두고 재실행 시 재사용한다 (SEC 예의 + 빠름).
"""
import json
import sqlite3
import time
import urllib.request
from pathlib import Path

import pandas as pd

# SEC 는 접속 주체를 밝히는 User-Agent 를 요구한다. 연락처는 바꿔도 된다.
UA = {"User-Agent": "stock-screener gusrkds96@gmail.com"}
CACHE = Path("cache")
DB = "stocks.db"

# 재무상태표(시점) 항목 - 최신 분기부터 훑어 처음 나오는 값을 쓴다
INSTANT_PERIODS = ["CY2026Q2I", "CY2026Q1I", "CY2025Q4I", "CY2025Q3I"]
INSTANT = {
    "equity":      ("us-gaap", "StockholdersEquity", "USD"),
    "liabilities": ("us-gaap", "Liabilities", "USD"),
    "assets":      ("us-gaap", "Assets", "USD"),
    "shares":      ("dei", "EntityCommonStockSharesOutstanding", "shares"),
}
# 손익계산서(기간) 항목 - 성장률을 내려면 2개 연도가 필요하다
YEARS = ["CY2025", "CY2024"]
ANNUAL = {
    "net_income": [("us-gaap", "NetIncomeLoss", "USD")],
    # 금융사 등은 '영업이익'을 보고하지 않는다. 세전이익을 대용으로 뒤에 붙인다.
    "op_income":  [("us-gaap", "OperatingIncomeLoss", "USD"),
                   ("us-gaap", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "USD"),
                   ("us-gaap", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments", "USD")],
    # 매출은 회사마다 쓰는 태그가 갈린다. 앞에서부터 채워 넣는다.
    "revenue":    [("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
                   ("us-gaap", "Revenues", "USD")],
}


def fetch(url, path):
    """캐시에 있으면 그대로, 없으면 받아서 저장. 404 는 None."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            body = r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    time.sleep(0.15)                      # SEC 권고 10 req/s 아래로
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return json.loads(body)


def frame(tax, tag, unit, period):
    """{cik: 값} - 해당 기간에 그 계정을 보고한 전 상장사."""
    d = fetch(f"https://data.sec.gov/api/xbrl/frames/{tax}/{tag}/{unit}/{period}.json",
              CACHE / f"{tag}_{unit}_{period}.json")
    if not d:
        return {}
    return {r["cik"]: r["val"] for r in d["data"]}


def fill(series_list):
    """앞에 있는 것 우선으로 빈칸 채우기."""
    out = {}
    for s in reversed(series_list):       # 뒤에서부터 덮어써 앞의 것이 이긴다
        out.update(s)
    return out


def tickers():
    """cik → 티커·회사명·거래소. OTC 는 유동성이 낮아 화면에서 걸러낼 수 있게 남겨둔다."""
    d = fetch("https://www.sec.gov/files/company_tickers_exchange.json",
              CACHE / "company_tickers_exchange.json")
    df = pd.DataFrame(d["data"], columns=d["fields"])
    return df.drop_duplicates("cik").set_index("cik")     # 복수 티커면 대표 하나만


def collect():
    cols = {}
    for key, (tax, tag, unit) in INSTANT.items():
        cols[key] = fill([frame(tax, tag, unit, p) for p in INSTANT_PERIODS])
        print(f"  {key:12s} {len(cols[key]):>6,}개사")

    for key, specs in ANNUAL.items():
        for year in YEARS:
            cols[f"{key}_{year[-4:]}"] = fill([frame(*s, year) for s in specs])
            print(f"  {key}_{year[-4:]:9s} {len(cols[f'{key}_{year[-4:]}']):>6,}개사")

    df = pd.DataFrame(cols)
    df.index.name = "cik"
    return df.join(tickers(), how="inner")


def derive(df):
    """5축 중 주가가 필요 없는 것들을 여기서 계산한다. PBR 은 시세 붙일 때."""
    eq = df.equity.where(df.equity > 0)                   # 자본잠식이면 비율 지표가 무의미
    df["liabilities"] = df.liabilities.fillna(df.assets - df.equity)   # 부채 미보고분은 자산-자본으로
    df["roe"] = df.net_income_2025 / eq * 100
    df["roa"] = df.net_income_2025 / df.assets.where(df.assets > 0) * 100
    df["debt_ratio"] = df.liabilities / eq * 100
    df["opm"] = df.op_income_2025 / df.revenue_2025.where(df.revenue_2025 > 0) * 100

    prev = df.op_income_2024.where(df.op_income_2024 > 0)  # 적자→흑자는 증가율이 무의미
    df["op_growth"] = (df.op_income_2025 / prev - 1) * 100
    prev_rev = df.revenue_2024.where(df.revenue_2024 > 0)
    df["rev_growth"] = (df.revenue_2025 / prev_rev - 1) * 100

    # 전년 이익이 0에 가까우면 증가율이 수만 %로 튄다. 순위는 그대로 두고 표시만 자른다.
    df["op_growth"] = df.op_growth.clip(-100, 300)
    df["rev_growth"] = df.rev_growth.clip(-100, 300)
    df["opm"] = df.opm.clip(-100, 100)          # 매출 태그 오인식으로 100%를 넘는 경우 방어
    return df


def main():
    print("SEC EDGAR 수집 중...")
    df = derive(collect()).reset_index()
    with sqlite3.connect(DB) as con:
        df.to_sql("us_fundamentals", con, if_exists="replace", index=False)
    print(f"\n{DB} · us_fundamentals · {len(df):,}개사 저장")
    have = {c: int(df[c].notna().sum()) for c in ["roe", "debt_ratio", "op_growth", "opm", "shares"]}
    print("지표별 값이 있는 종목 수:", have)
    return df


if __name__ == "__main__":
    main()
