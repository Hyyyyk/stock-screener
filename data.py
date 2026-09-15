"""화면이 쓰는 데이터 계층. app.py 는 여기만 본다.

stocks.db 의 미국 재무(SEC) · 한국 재무(DART) · 시세(Yahoo) · 업종을 합쳐 내보낸다.
"""
import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

import pandas as pd
import streamlit as st

DB = "stocks.db"
CACHE = Path("cache")
UA = {"User-Agent": "stock-screener gusrkds96@gmail.com"}

# 저평가주 발굴에 쓰는 핵심 5축. (표시명, 컬럼, 단위, 클수록좋은가, 한줄설명)
CORE = [
    ("PBR",        "pbr",        "배", False, "주가가 순자산의 몇 배인가. 낮을수록 싸다"),
    ("ROE",        "roe",        "%",  True,  "자기자본으로 얼마를 벌었나. 높을수록 알짜"),
    ("영업익증가율", "op_growth",  "%",  True,  "이익이 늘고 있나. 재평가의 근거"),
    ("부채비율",    "debt_ratio", "%",  False, "빚이 자본의 몇 배인가. 낮을수록 안전"),
    ("수급",       "flow_net",   "%",  True,  "외국인+기관 20거래일 순매수 금액 ÷ 시가총액. 남들도 사고 있나 (한국만)"),
]

# 상세 화면에서만 참고로 보여주는 보조 지표
EXTRA = [
    ("PER",       "per",        "배", "주가가 순이익의 몇 배인가 (적자면 없음)"),
    ("PSR",       "psr",        "배", "주가가 매출의 몇 배인가"),
    ("ROA",       "roa",        "%",  "총자산 대비 수익률"),
    ("영업이익률", "opm",        "%",  "매출에서 남는 비율"),
    ("매출증가율", "rev_growth", "%",  "외형 성장 속도"),
]

# 아직 소스가 없어 비어 있는 축 → 화면에서 자동으로 빠진다
PENDING = {}


@st.cache_data(ttl=600)
def load_stocks() -> pd.DataFrame:
    """한국(DART) + 미국(SEC) 재무에 시세를 붙인 전 종목 스냅샷. 1행 = 1종목."""
    with sqlite3.connect(DB) as con:
        us = _read(con, "us_fundamentals")
        kr = _read(con, "kr_fundamentals")
        px = _read(con, "prices")
        sic = _read(con, "sectors")
        flows = _read(con, "flows")               # 한국 수급 (collect_flow.py, 네이버 비공식)

    # 미국은 연도가 컬럼명에 붙어 있어 한국과 이름을 맞춘다
    us = us.rename(columns={"net_income_2025": "net_income", "revenue_2025": "revenue",
                            "op_income_2025": "op_income", "exchange": "market"})
    if not sic.empty:
        us = us.merge(sic, on="cik", how="left")
    us["country"] = "US"

    kr["country"] = "KR"                          # market 은 이미 KOSPI/KOSDAQ

    df = pd.concat([us, kr], ignore_index=True)
    if not px.empty:
        df = df.merge(px[["ticker", "price", "currency", "change_pct", "high52", "low52", "kind"]],
                      on="ticker", how="left")
    if not flows.empty:
        df = df.merge(flows[["ticker", "flow_net_amt", "foreign_hold_ratio", "flow_asof"]], on="ticker", how="left")
    for col in ["price", "currency", "change_pct", "high52", "low52", "kind",
                "sector", "sic_desc", "cik", "flow_net_amt", "foreign_hold_ratio", "flow_asof"]:
        if col not in df:
            df[col] = pd.NA
    df["sector"] = df.sector.fillna("미분류")
    df["market"] = df.market.fillna("기타")
    df["currency"] = df.currency.fillna(df.country.map({"US": "USD", "KR": "KRW"}))

    # 밸류에이션은 시가총액 ÷ 재무 수치. 분모가 0 이하면 배수가 뜻을 잃으므로 비운다.
    df["market_cap"] = df.price * df.shares
    # 시가총액 하한 같은 '크기' 필터는 통화를 맞춰야 한다 ($100M 을 원화 숫자에 대면 1억 원이 된다)
    fx = px.loc[px.ticker == "KRW=X", "price"] if not px.empty else pd.Series(dtype=float)
    krw_per_usd = float(fx.iloc[0]) if len(fx) else 1400.0   # collect_price.py 를 돌리면 실제 환율로 채워진다
    df["market_cap_usd"] = df.market_cap / df.currency.map({"KRW": krw_per_usd}).fillna(1.0)
    df["pbr"] = df.market_cap / df.equity.where(df.equity > 0)
    df["per"] = df.market_cap / df.net_income.where(df.net_income > 0)
    df["psr"] = df.market_cap / df.revenue.where(df.revenue > 0)
    # 수급은 순매수 금액을 시가총액으로 나눠야 크기가 다른 종목끼리 비교된다. 미국은 값이 없다(NaN)
    df["flow_net"] = pd.to_numeric(df.flow_net_amt, errors="coerce") / df.market_cap * 100
    return df.dropna(subset=["ticker"]).reset_index(drop=True)


def _read(con, table):
    try:
        return pd.read_sql(f"select * from {table}", con)
    except pd.errors.DatabaseError:               # 해당 수집기를 아직 안 돌린 경우
        return pd.DataFrame()


def available(df, metrics):
    """값이 하나도 없는 축은 화면에서 뺀다."""
    return [m for m in metrics if df[m[1]].notna().any()]


def _fetch(url, path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        body = r.read().decode()
    time.sleep(0.15)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return json.loads(body)


# 연도별 추이에 쓸 계정. 회사마다 태그가 갈려서 앞에서부터 찾는다.
HISTORY_TAGS = {
    "매출액":   ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
    "영업이익": ["OperatingIncomeLoss",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"],
    "순이익":   ["NetIncomeLoss"],
    "영업CF":   ["NetCashProvidedByUsedInOperatingActivities",
                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "투자CF":   ["NetCashProvidedByUsedInInvestingActivities",
                "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"],
    "재무CF":   ["NetCashProvidedByUsedInFinancingActivities",
                "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"],
}


@st.cache_data(ttl=3600, show_spinner="SEC에서 이 회사 이력을 받는 중…")
def load_history(cik: int, years: int = 6) -> pd.DataFrame:
    """종목 하나의 연도별 실적. 열어볼 때만 SEC 에서 받아온다(회사당 1회, 캐시됨)."""
    try:
        facts = _fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json",
                       CACHE / f"facts_{int(cik):010d}.json").get("facts", {}).get("us-gaap", {})
    except Exception:
        return pd.DataFrame()

    out = {}
    for label, tags in HISTORY_TAGS.items():
        for tag in tags:
            # SEC 가 붙여준 frame='CY2024' 인 값만 쓰면 연간치가 중복 없이 하나씩 나온다
            vals = {int(x["frame"][2:6]): x["val"]
                    for x in facts.get(tag, {}).get("units", {}).get("USD", [])
                    if re.fullmatch(r"CY\d{4}", x.get("frame", ""))}
            if vals:
                out[label] = vals
                break
    if not out:
        return pd.DataFrame()
    h = pd.DataFrame(out).sort_index().tail(years) / 1e6      # 백만 달러 단위
    h.index.name = "연도"
    return h.reset_index()


def money(v, currency="USD"):
    """통화가 섞일 예정이라 시가총액은 문자열로 통일해 보여준다."""
    if pd.isna(v):
        return "–"
    if currency == "KRW":
        return f"{v / 1e12:.1f}조" if v >= 1e12 else f"{v / 1e8:,.0f}억"
    return f"${v / 1e9:.1f}B" if v >= 1e9 else f"${v / 1e6:,.0f}M"


# ---------------- 비교 그룹 안에서의 등수 ----------------
SIZE_LABELS = ["소형", "중형", "대형"]
SHRINK_K = 30      # 종목이 이 정도보다 적은 그룹은 같은 나라·규모 전체 등수 쪽으로 당겨진다


def size_bucket(cap):
    """나라 안에서 시가총액 3등분.

    한국은 작을수록 PBR 이 구조적으로 낮다(시총 5분위 PBR 중앙값 소형 0.97 · 대형 1.97).
    같은 규모끼리 비교하지 않으면 '싼가' 단계가 소형주로 쏠린다.
    """
    out = pd.Series(pd.NA, index=cap.index, dtype="object")
    ok = cap.notna()
    if ok.sum() >= len(SIZE_LABELS):
        out[ok] = pd.qcut(cap[ok].rank(method="first"), len(SIZE_LABELS), labels=SIZE_LABELS).astype(str)
    return out


def mid_pct(grouped, higher_better):
    """그룹 안 백분위 0~100 (100 = 가장 좋음).

    중간순위 (순위-0.5)/종목수 로 매겨야 종목이 몇 개 안 되는 그룹에서도 위아래가 대칭이다.
    순위/종목수 로 매기면 2종목 그룹에서 둘 다 '상위 50%' 를 통과해버린다.
    """
    return (grouped.rank(ascending=higher_better) - 0.5) / grouped.transform("count") * 100


def peer_pct(df, col, higher_better, by_peer):
    """비교 대상 안에서의 백분위.

    by_peer 면 같은 나라·업종·규모 안에서 매긴다. 그런 그룹은 종목이 적을 때가 많아
    (한국 업종 27개 중 15개가 30종목 미만) 등수가 튄다. 그래서 그룹 종목 수 n 이 적을수록
    같은 나라·규모 전체의 등수 쪽으로 당긴다: (n·그룹등수 + K·부모등수) / (n + K)
    """
    if not by_peer:
        return mid_pct(df.groupby(pd.Series(0, index=df.index))[col], higher_better)
    group = df.groupby(["country", "sector", "size_bucket"], observed=True)[col]
    parent = df.groupby(["country", "size_bucket"], observed=True)[col]
    n = group.transform("count")
    return (n * mid_pct(group, higher_better) + SHRINK_K * mid_pct(parent, higher_better)) / (n + SHRINK_K)


# ---------------- 한국 연도별 실적 (DART 전체 재무제표) ----------------
# fnlttSinglAcntAll 은 한 번에 당기·전기·전전기 3년치를 현금흐름까지 준다.
# 그래서 2025년·2022년 보고서 두 번이면 2020~2025 여섯 해가 나온다.
KR_HISTORY_IDS = {
    "매출액":   ["ifrs-full_Revenue",
                "ifrs-full_InterestRevenueExpense", "ifrs-full_RevenueFromInterest"],   # 금융사는 매출이 없다
    "영업이익": ["dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"],
    "순이익":   ["ifrs-full_ProfitLoss"],
    "영업CF":   ["ifrs-full_CashFlowsFromUsedInOperatingActivities"],
    "투자CF":   ["ifrs-full_CashFlowsFromUsedInInvestingActivities"],
    "재무CF":   ["ifrs-full_CashFlowsFromUsedInFinancingActivities"],
}
_PERIODS = ("thstrm_amount", "frmtrm_amount", "bfefrmtrm_amount")     # 당기, 전기, 전전기


def parse_kr_history(reports):
    """{보고서연도: DART 행 목록} → 연도별 실적 (단위 억 원). 네트워크 없이 테스트할 수 있게 분리했다."""
    from collect_kr import num

    out = {}
    # 같은 해가 두 보고서에 나오면(2025년 보고서의 전전기 = 2023년 보고서의 당기) 최신 보고서의
    # 값이 이긴다 - 나중 보고서에는 수정·재작성이 반영돼 있다
    for year, rows in sorted(reports.items(), reverse=True):
        found = {}
        for r in rows:
            if r.get("sj_div") in ("IS", "CIS", "CF"):
                # 순이익은 손익계산서와 현금흐름표에 둘 다 나온다. 표를 구분해서 먼저 나온 것만 쓴다
                found.setdefault((r["sj_div"] == "CF", r.get("account_id")), r)
        for label, ids in KR_HISTORY_IDS.items():
            for aid in ids:
                r = found.get((label.endswith("CF"), aid))
                if r is None:
                    continue
                for back, field in enumerate(_PERIODS):
                    v = num(r.get(field))
                    if v is not None:
                        out.setdefault(label, {}).setdefault(int(year) - back, v / 1e8)
                break
    if not out:
        return pd.DataFrame()
    h = pd.DataFrame(out).sort_index().dropna(how="all")     # 보고서는 있는데 당기 칸이 빈 해가 있다
    h.index.name = "연도"
    return h.reset_index()


def _dart_report(corp_code, year):
    """사업보고서 전체 재무제표 행. 연결(CFS)이 없으면 별도(OFS).

    지난 연도의 '없음'(013) 응답은 캐시해 다시 묻지 않는다. 최신 연도는 아직 공시 전일 수 있어
    '없음'을 캐시하면 나중에 보고서가 올라와도 영영 안 보이므로 캐시하지 않는다.
    """
    from collect_kr import YEAR, api

    for fs in ("CFS", "OFS"):
        path = CACHE / f"dart_full_{corp_code}_{year}_{fs}.json"
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
        else:
            d = json.loads(api("fnlttSinglAcntAll.json", corp_code=corp_code, bsns_year=str(year),
                               reprt_code="11011", fs_div=fs))   # 네트워크 오류는 그대로 올려 캐시하지 않는다
            time.sleep(0.5)                                      # DART 는 순간 속도를 내면 연결을 끊는다
            if d.get("status") == "000" or (d.get("status") == "013" and int(year) < int(YEAR)):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        if d.get("status") == "000":
            return d["list"]
    return []


@st.cache_data(ttl=3600, show_spinner="DART에서 이 회사 이력을 받는 중…")
def load_history_kr(corp_code: str) -> pd.DataFrame:
    """한국 종목 하나의 연도별 실적. 열어볼 때만 DART 에서 받는다(회사당 최대 4호출, 파일 캐시)."""
    from collect_kr import YEAR

    latest = int(YEAR)
    reports = {}
    # 최신 보고서 → 3년 전 보고서 두 장이면 여섯 해가 나온다. 그 해 보고서가 없으면 한 해 옆 것으로 메운다:
    #  - 최신이 없음: 아직 공시 전인 회사 → 1년 전 보고서
    #  - 3년 전이 없음: 금융사는 IFRS17 전환(2023) 이전 보고서가 이 API에 없다 → 2년 전 보고서의 전기·전전기
    for candidates in ((latest, latest - 1), (latest - 3, latest - 2)):
        for y in candidates:
            rows = _dart_report(corp_code, y)
            if rows:
                reports[y] = rows
                break
    return parse_kr_history(reports)


def weighted_score(pct, weights):
    """축별 백분위의 가중평균.

    값이 없는 축은 그 종목의 분모에서도 뺀다. 그냥 합치면 없는 축이 0점으로 들어가서
    수급 데이터가 없는 미국 종목의 점수가 이유 없이 깎인다.
    """
    w = pd.Series({k: v for k, v in weights.items() if k in pct})
    p = pct[w.index]
    return (p * w).sum(axis=1) / (p.notna() * w).sum(axis=1)
