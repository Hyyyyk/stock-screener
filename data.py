"""화면이 쓰는 데이터 계층. app.py 는 여기만 본다.

stocks.db 의 미국 재무(SEC) · 한국 재무(DART) · 시세(Yahoo) · 업종을 합쳐 내보낸다.
"""
import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date

import pandas as pd
import streamlit as st
import repository
from settings import CACHE, DB

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
FINANCIAL_SECTORS = {"은행·증권", "보험"}


def metric_applicable(df, col):
    """종목별로 점수/필터에 적용할 수 있는 축인지 반환한다.

    미국에는 일별 투자자 수급이 없고, 은행·보험의 부채는 영업 원재료에 가까워
    제조업식 부채비율을 안전성 점수로 쓰지 않는다.
    """
    applicable = pd.Series(True, index=df.index)
    if col == "flow_net":
        applicable &= df["country"].eq("KR")
    elif col == "debt_ratio":
        applicable &= ~df["sector"].isin(FINANCIAL_SECTORS)
    return applicable


def expected_annual_year(today=None):
    """사업보고서 제출 시기를 고려해 기대할 수 있는 최신 완료연도."""
    today = today or date.today()
    return today.year - (1 if today.month >= 4 else 2)


@st.cache_data(ttl=600)
def data_freshness():
    """화면에 표시할 소스별 기준일/연도."""
    tables = repository.load_snapshot_tables()
    us, kr = tables["us_fundamentals"], tables["kr_fundamentals"]
    years = []
    for frame in (us, kr):
        if "fiscal_year" in frame:
            years.extend(pd.to_numeric(frame.fiscal_year, errors="coerce").dropna().astype(int).tolist())
    if not years:  # 기존 DB: 미국 컬럼명의 연도에서 안전하게 추론한다
        years = [int(m.group(1)) for c in us.columns
                 if (m := re.fullmatch(r"revenue_(\d{4})", c))]
    return {"price": repository.scalar("select max(fetched_at) from prices"),
            "flow": repository.scalar("select max(flow_asof) from flows"),
            "fiscal_year": max(years) if years else None}


def data_asof():
    """기존 호출부 호환용: (시세 갱신일, 수급 기준일)."""
    fresh = data_freshness()
    return fresh["price"], fresh["flow"]


def _annual_years(columns, prefix="revenue_"):
    return sorted((int(m.group(1)) for c in columns
                   if (m := re.fullmatch(fr"{re.escape(prefix)}(\d{{4}})", c))), reverse=True)


@st.cache_data(ttl=600)
def load_stocks() -> pd.DataFrame:
    """한국(DART) + 미국(SEC) 재무에 시세를 붙인 전 종목 스냅샷. 1행 = 1종목."""
    tables = repository.load_snapshot_tables()
    us, kr, px, sic, flows = (tables[name] for name in
                              ("us_fundamentals", "kr_fundamentals", "prices", "sectors", "flows"))

    # 미국은 DB에 실제 존재하는 최신 3개 연도를 찾아 공통 이름으로 맞춘다.
    us_years = _annual_years(us.columns)
    if us_years:
        latest = us_years[0]
        us = us.rename(columns={f"net_income_{latest}": "net_income",
                                f"revenue_{latest}": "revenue",
                                f"op_income_{latest}": "op_income", "exchange": "market"})
        us["fiscal_year"] = us.get("fiscal_year", latest)
    if not sic.empty:
        us = us.merge(sic, on="cik", how="left")
    us["country"] = "US"
    us["business"] = us.get("sic_desc")           # 미국은 SEC 업종 상세를 '뭘 하는지'로 쓴다
    # 3년 매출·흑자전환 판정을 나라 무관하게 하려고 공통 컬럼으로 맞춘다 (연도명이 서로 다르다)
    if len(us_years) >= 3:
        us["rev_y1"], us["rev_y2"], us["rev_y3"] = (us.get(f"revenue_{y}") for y in reversed(us_years[:3]))
    else:
        us["rev_y1"], us["rev_y2"], us["rev_y3"] = pd.NA, pd.NA, us.get("revenue")
    us["ni_prev"] = us.get(f"net_income_{us_years[1]}") if len(us_years) >= 2 else pd.NA

    kr["country"] = "KR"                          # market 은 이미 KOSPI/KOSDAQ
    oldest_col = "revenue_oldest" if "revenue_oldest" in kr else "revenue_2023"
    kr["rev_y1"], kr["rev_y2"], kr["rev_y3"] = kr.get(oldest_col), kr.get("revenue_prev"), kr["revenue"]
    kr["ni_prev"] = kr.get("net_income_prev")
    if "fiscal_year" not in kr:
        kr["fiscal_year"] = us_years[0] if us_years else pd.NA

    df = pd.concat([us, kr], ignore_index=True)
    if not px.empty:
        cols = ["ticker", "price", "currency", "change_pct", "high52", "low52", "kind"]
        cols += [c for c in ("ret_3m", "ret_6m") if c in px]   # 예전 prices(ret 없음)여도 안 깨지게
        df = df.merge(px[cols], on="ticker", how="left")
    if not flows.empty:
        df = df.merge(flows[["ticker", "flow_net_amt", "foreign_hold_ratio", "flow_asof"]], on="ticker", how="left")
    for col in ["price", "currency", "change_pct", "high52", "low52", "kind", "ret_3m", "ret_6m",
                "sector", "sic_desc", "business", "cik", "flow_net_amt", "foreign_hold_ratio", "flow_asof"]:
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

    # 사용자 관심 패턴 두 가지 (값이 빠지면 자동으로 False → 필터에서 제외)
    r1, r2, r3 = (pd.to_numeric(df[c], errors="coerce") for c in ("rev_y1", "rev_y2", "rev_y3"))
    df["rev_up_3y"] = (r1 > 0) & (r1 < r2) & (r2 < r3)                      # 매출 3년 연속 증가
    df["turnaround"] = (pd.to_numeric(df.ni_prev, errors="coerce") < 0) & \
                       (pd.to_numeric(df.net_income, errors="coerce") >= 0)  # 흑자전환(전기 적자→당기 흑자)
    # 종목별로 적용 가능한 핵심 축만 완성도 분모로 삼는다.
    core_cols = [c for _, c, *_ in CORE]
    applicable = pd.DataFrame({c: metric_applicable(df, c) for c in core_cols})
    present = df[core_cols].notna() & applicable
    df["data_axes"] = present.sum(axis=1)
    df["data_expected"] = applicable.sum(axis=1)
    df["data_completeness"] = (df.data_axes / df.data_expected.replace(0, pd.NA) * 100).round()
    df["financial_stale"] = pd.to_numeric(df.fiscal_year, errors="coerce") < expected_annual_year()
    return df.dropna(subset=["ticker"]).reset_index(drop=True)


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


# ---------------- 회사 소개 (Yahoo assetProfile, 영어) ----------------
YAHOO_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


@st.cache_resource
def _yahoo_session():
    """Yahoo 는 쿠키+crumb 가 있어야 quoteSummary 를 준다. 세션당 한 번 받아 재사용한다."""
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    try:
        op.open(urllib.request.Request("https://fc.yahoo.com", headers=YAHOO_UA), timeout=10).read()
    except Exception:
        pass                                      # 404 여도 A3 쿠키는 세팅된다
    crumb = op.open(urllib.request.Request(
        "https://query2.finance.yahoo.com/v1/test/getcrumb", headers=YAHOO_UA), timeout=15).read().decode()
    return op, crumb


def _trim(s, limit=420):
    """긴 회사 소개를 3~4문장 정도로 자른다. 마지막 마침표에서 끊어 문장을 안 끊는다."""
    s = " ".join(s.split())
    if len(s) <= limit:
        return s
    cut = s[:limit]
    return cut[:cut.rfind(". ") + 1] if ". " in cut else cut + "…"


def _translate(text):
    """영어 → 한글. 구글 무료 엔드포인트(비공식). 실패하면 원문 그대로 돌려준다."""
    try:
        url = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q="
               + urllib.parse.quote(text))
        d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=YAHOO_UA), timeout=15))
        return "".join(seg[0] for seg in d[0])
    except Exception:
        return text


@st.cache_data(ttl=86400, show_spinner="회사 정보를 받는 중…")
def load_business(ticker: str) -> str | None:
    """종목 하나의 회사 소개(한글). Yahoo 에서 영어를 받아 번역한다. 상세 열 때만. 실패하면 None."""
    try:
        op, crumb = _yahoo_session()
        url = (f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(ticker)}"
               f"?modules=assetProfile&crumb={urllib.parse.quote(crumb)}")
        d = json.load(op.open(urllib.request.Request(url, headers=YAHOO_UA), timeout=15))
        s = d["quoteSummary"]["result"][0].get("assetProfile", {}).get("longBusinessSummary")
        return _translate(_trim(s)) if s else None
    except Exception:
        return None                               # 차단·형식변경 등 - 화면은 KRX/SEC 한 줄로 폴백


@st.cache_data(ttl=1800, show_spinner="수급을 받는 중…")
def load_flow_daily(stock_code: str, days=12) -> pd.DataFrame:
    """한국 종목 일별 외국인·기관 순매수(억 원 = 순매수량×종가). 오래된→최신 순. 열 때만 네이버 조회."""
    from collect_flow import to_int

    url = f"https://m.stock.naver.com/api/stock/{stock_code}/trend?pageSize={days}"
    try:
        rows = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=YAHOO_UA), timeout=15))
    except Exception:
        return pd.DataFrame()
    recs = []
    for r in rows:
        c, f, o = (to_int(r.get(k)) for k in ("closePrice", "foreignerPureBuyQuant", "organPureBuyQuant"))
        if None in (c, f, o):
            continue
        d = str(r.get("bizdate", ""))
        recs.append({"날짜": f"{d[4:6]}/{d[6:8]}",
                     "외인_주": f, "외인_억": f * c / 1e8,     # 순매수 주식수 · 금액(억)
                     "기관_주": o, "기관_억": o * c / 1e8})
    return pd.DataFrame(recs[::-1])                # 네이버는 최신이 앞 → 뒤집어 시간순


def flow_streak(series):
    """최신(마지막)부터 같은 방향으로 며칠 연속인지. +N 순매수 연속, -N 순매도 연속, 0 없음."""
    n, last = 0, 0
    for v in reversed(list(series)):
        sign = 1 if v > 0 else -1 if v < 0 else 0
        if sign == 0 or (last and sign != last):
            break
        n, last = n + 1, sign
    return n * last


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


def _dart_report(corp_code, year, reprt="11011"):
    """전체 재무제표 행. reprt: 11011 사업보고서(연간) · 11013 1Q · 11012 반기 · 11014 3Q.
    연결(CFS)이 없으면 별도(OFS).

    지난 연도의 '없음'(013) 응답은 캐시해 다시 묻지 않는다. 최신 연도는 아직 공시 전일 수 있어
    '없음'을 캐시하면 나중에 보고서가 올라와도 영영 안 보이므로 캐시하지 않는다.
    """
    from collect_kr import YEAR, api

    for fs in ("CFS", "OFS"):
        path = CACHE / f"dart_full_{corp_code}_{year}_{reprt}_{fs}.json"
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
        else:
            d = json.loads(api("fnlttSinglAcntAll.json", corp_code=corp_code, bsns_year=str(year),
                               reprt_code=reprt, fs_div=fs))      # 네트워크 오류는 그대로 올려 캐시하지 않는다
            time.sleep(0.5)                                      # DART 는 순간 속도를 내면 연결을 끊는다
            if d.get("status") == "000" or (d.get("status") == "013" and int(year) < int(YEAR)):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        if d.get("status") == "000":
            return d["list"]
    return []


# ---------------- 분기 실적 ----------------
QUARTER_REPRT = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}   # 분기 → DART 보고서코드
_IS_LABELS = ("매출액", "영업이익", "순이익")                        # 손익: thstrm = 당분기값
_CF_LABELS = ("영업CF", "투자CF", "재무CF")                         # 현금흐름: thstrm = 누적 → 차감


def _extract_kr(rows):
    """DART 행 → {label: (당기금액, 누적금액)}. 계정 ID 로 찾는다 (연결/손익 우선순위는 처음 것)."""
    from collect_kr import num

    found = {}
    for r in rows:
        if r.get("sj_div") in ("IS", "CIS", "CF"):
            found.setdefault((r["sj_div"] == "CF", r.get("account_id")), r)
    out = {}
    for label, ids in KR_HISTORY_IDS.items():
        for aid in ids:
            r = found.get((label.endswith("CF"), aid))
            if r:
                out[label] = (num(r.get("thstrm_amount")), num(r.get("thstrm_add_amount")))
                break
    return out


@st.cache_data(ttl=3600, show_spinner="DART에서 분기 실적을 받는 중… (10초쯤)")
def load_history_kr_quarter(corp_code: str, n=8) -> pd.DataFrame:
    """한국 분기 실적(억 원). 손익은 당분기값, 현금흐름은 누적을 차감해 당분기로 만든다.

    최근 연도들의 1Q·반기·3Q·사업보고서를 받아 엮는다(연도당 4호출). 그래서 느리다.
    """
    from collect_kr import YEAR

    rep = {}                                          # (연도, 분기) → {label: (당기, 누적)}
    for y in (int(YEAR), int(YEAR) - 1, int(YEAR) - 2):
        for q, rc in QUARTER_REPRT.items():
            rows = _dart_report(corp_code, y, rc)
            if rows:
                rep[(y, q)] = _extract_kr(rows)

    def val(key, label, idx):                         # rep 에서 안전하게 꺼내기
        return (rep.get(key) or {}).get(label, (None, None))[idx]

    out = {}                                          # (연도, 분기) → {label: 당분기값}
    for (y, q), _ in rep.items():
        cell = {}
        for label in _IS_LABELS:                      # 손익: 당분기 = thstrm. Q4 = 연간 - 3Q누적
            cell[label] = (val((y, 4), label, 0) - val((y, 3), label, 1)
                           if q == 4 and val((y, 4), label, 0) is not None
                           and val((y, 3), label, 1) is not None
                           else val((y, q), label, 0))
        for label in _CF_LABELS:                      # 현금흐름: 당분기 = 이번 누적 - 직전 분기 누적
            cur = val((y, q), label, 0)
            prev = val((y, q - 1), label, 0) if q > 1 else 0
            cell[label] = cur - prev if cur is not None and prev is not None else None
        out[(y, q)] = cell

    if not out:
        return pd.DataFrame()
    df = pd.DataFrame([{"연도": f"{y % 100:02d}", "분기": f"{q}Q", "_key": y * 10 + q, **c}
                       for (y, q), c in out.items()])
    df = df.sort_values("_key").tail(n)
    df["연도"] = df["연도"] + " " + df["분기"]         # 라벨: "25 2Q"
    return (df.drop(columns=["분기", "_key"]).set_index("연도").dropna(axis=1, how="all")
            .div(1e8).reset_index())


@st.cache_data(ttl=3600, show_spinner="SEC에서 분기 실적을 받는 중…")
def load_history_us_quarter(cik: int, n=8) -> pd.DataFrame:
    """미국 분기 실적(백만 달러). 손익만 — SEC 는 분기 현금흐름을 캘린더 분기로 주지 않는다."""
    try:
        facts = _fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json",
                       CACHE / f"facts_{int(cik):010d}.json").get("facts", {}).get("us-gaap", {})
    except Exception:
        return pd.DataFrame()

    out = {}
    for label in _IS_LABELS:
        for tag in HISTORY_TAGS[label]:
            vals = {x["frame"]: x["val"]
                    for x in facts.get(tag, {}).get("units", {}).get("USD", [])
                    if re.fullmatch(r"CY\d{4}Q\d", x.get("frame", ""))}
            if vals:
                out[label] = vals
                break
    if not out:
        return pd.DataFrame()
    idx = sorted(set().union(*[v.keys() for v in out.values()]))   # 있는 분기만, 시간순
    h = pd.DataFrame(out).reindex(idx)
    h.index = [f"{f[4:6]} Q{f[7]}" for f in idx]      # CY2025Q2 → "25 Q2"
    return (h.tail(n) / 1e6).reset_index(names="연도")


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


def weighted_score(pct, weights, min_axes=1):
    """축별 백분위의 가중평균.

    값이 없는 축은 그 종목의 분모에서도 뺀다. 그냥 합치면 없는 축이 0점으로 들어가서
    수급 데이터가 없는 미국 종목의 점수가 이유 없이 깎인다.
    """
    w = pd.Series({k: v for k, v in weights.items() if k in pct})
    p = pct[w.index]
    score = (p * w).sum(axis=1) / (p.notna() * w).sum(axis=1)
    return score.where(p.notna().sum(axis=1) >= min_axes)


def score_reason(pct_row, metrics=CORE, limit=2):
    """백분위가 가장 좋은 축을 사람이 읽는 짧은 선정 이유로 바꾼다."""
    labels = {col: label for label, col, *_ in metrics}
    ranked = [(col, float(pct_row[col])) for col in labels
              if col in pct_row and pd.notna(pct_row[col])]
    ranked.sort(key=lambda item: item[1], reverse=True)
    parts = []
    for col, percentile in ranked[:limit]:
        top = max(1, min(100, round(100 - percentile)))
        parts.append(f"{labels[col]} 상위 {top}%")
    return " · ".join(parts) if parts else "계산 가능한 핵심 지표 부족"


# 저평가 해석 규칙: (실제 값 기준) 강점·약점 한 줄.  임계값은 상대(백분위)가 아닌 절대 기준이라
# 검색으로 연 모집단 밖 종목도 그대로 해석된다. 투자 자문이 아니라 숫자를 말로 풀어주는 것뿐이다.
def interpret(row):
    """종목의 실제 지표를 읽어 '싸고 잘 벌지만 성장이 꺾였다' 식 한 줄 해석을 만든다."""
    ok = lambda x: x is not None and pd.notna(x)
    pbr, roe = row.get("pbr"), row.get("roe")
    growth, debt, flow = row.get("op_growth"), row.get("debt_ratio"), row.get("flow_net")
    strong, weak = [], []

    if ok(pbr):
        if pbr < 1:   strong.append(f"순자산보다 싼 가격(PBR {pbr:.2f})")
        elif pbr > 5: weak.append(f"순자산 대비 비쌈(PBR {pbr:.1f})")
    if ok(roe):
        if roe >= 15:  strong.append(f"자본 대비 잘 번다(ROE {roe:.0f}%)")
        elif roe < 5:  weak.append(f"수익성이 낮다(ROE {roe:.0f}%)")
    if ok(growth):
        if growth >= 20: strong.append(f"이익이 빠르게 큰다(영업익 +{growth:.0f}%)")
        elif growth < 0: weak.append(f"영업이익이 줄고 있다({growth:.0f}%)")
    if ok(debt):
        if debt <= 50:    strong.append(f"빚이 적어 안전(부채 {debt:.0f}%)")
        elif debt >= 200: weak.append(f"부채가 많다({debt:.0f}%)")
    if ok(flow):
        if flow > 0.1:    strong.append("외국인·기관이 사는 중")
        elif flow < -0.1: weak.append("외국인·기관이 파는 중")

    head = ", ".join(strong[:2]) if strong else "두드러지는 강점은 적음"
    return head + (" — 주의: " + ", ".join(weak[:2]) if weak else "")


# 추세 위치: 52주 고·저 대비 어디에 있나 → 상승 추세 구간인가.
# 미너비니 '추세 템플릿' 8대 기준 중 가격 위치 두 가지(고점 -25% 이내 / 저점 +30% 이상)만 쓴
# 부분집합이다(이동평균·거래량은 빠짐). 임계값은 제 제안이며, 유효성은 백테스트로 검증해야 한다.
# price·high52·low52 가 다 있어야 하고 없으면 판단 유보(<NA>)로 둔다.
def trend_label(df):
    """행별 추세 라벨 Series: 상승 추세 / 조정 중 / 약세 / <NA>(유보)."""
    p, hi, lo = df.price, df.high52, df.low52
    ok = p.notna() & hi.notna() & lo.notna() & (hi > 0) & (lo > 0)
    within25 = p >= 0.75 * hi            # 52주 고점 대비 -25% 이내
    above30 = p >= 1.30 * lo             # 52주 저점 대비 +30% 이상
    label = pd.Series(pd.NA, index=df.index, dtype="object")
    label[ok & within25 & above30] = "상승 추세"
    label[ok & above30 & ~within25] = "조정 중"
    label[ok & ~above30] = "약세"
    return label


# 상대강도(RS): 오닐·미너비니가 쓰는 "시장 대비 얼마나 센가". 절대 수익률이 아니라
# 같은 나라 종목들 사이의 '순위'다(한·미는 통화·국면이 달라 섞지 않는다).
# 최근 3개월에 2배 가중한 3·6개월 수익률을 블렌딩(제 제안). 둘 다 없으면 <NA>(판단 유보).
def naver_url(ticker, country, market):
    """네이버 증권 종목 페이지 URL. 한국은 종목코드, 미국은 해외증권(거래소코드 O/N)."""
    if country == "KR":
        return f"https://finance.naver.com/item/main.naver?code={str(ticker).split('.')[0]}"
    exch = {"Nasdaq": "O", "NYSE": "N"}.get(market, "O")
    return f"https://m.stock.naver.com/worldstock/stock/{ticker}.{exch}/total"


def relative_strength(df):
    """RS 백분위 Series(0~100, 높을수록 강함). 같은 country 안에서 순위."""
    r3, r6 = df.get("ret_3m"), df.get("ret_6m")
    if r3 is None or r6 is None:
        return pd.Series(float("nan"), index=df.index)
    r3, r6 = pd.to_numeric(r3, errors="coerce"), pd.to_numeric(r6, errors="coerce")
    raw = 2 * r3.fillna(r6) + r6.fillna(r3)        # 한쪽만 있으면 그 값으로 메움, 둘 다 없으면 NaN
    return raw.groupby(df.country).rank(pct=True) * 100


# 그레이엄 수(Graham Number): 방어적 투자자용 적정가 어림. 적정가 ≈ √(22.5·EPS·BPS).
# 22.5 = PER 15 × PBR 1.5 — 그레이엄이 『현명한 투자자』에서 방어적 종목의 상한 '엄지손가락 규칙'
# 으로 제시한 값이다(그의 주장). 안전마진 %는 적정가 대비 현재가가 얼마나 싼가(내 계산).
# EPS·BPS·현재가가 모두 양(+)일 때만 뜻이 있고(적자·자본잠식·마이너스가격 → 판단 유보),
# 성장주·금융업·무형자산 중심 기업에는 맞지 않는다(호출부에서 따로 거른다).
def graham(df):
    """적정가(fair)와 안전마진 %(margin) DataFrame. 계산 불가 행은 NaN(판단 유보)."""
    need = ("net_income", "equity", "shares", "price")
    if any(c not in df for c in need):
        return pd.DataFrame({"fair": float("nan"), "margin": float("nan")}, index=df.index)
    ni, eq, sh, price = (pd.to_numeric(df[c], errors="coerce") for c in need)
    eps, bps = ni / sh, eq / sh
    valid = (sh > 0) & (eps > 0) & (bps > 0) & (price > 0)
    fair = ((22.5 * eps * bps).where(valid)) ** 0.5
    return pd.DataFrame({"fair": fair, "margin": (fair / price - 1) * 100}, index=df.index)
