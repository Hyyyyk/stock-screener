"""수집 결과와 통합 종목 데이터의 품질 검사. 네트워크 없이 실행된다."""
from dataclasses import dataclass
from datetime import date
import re

import pandas as pd


@dataclass(frozen=True)
class Finding:
    level: str       # ERROR / WARN / INFO
    code: str
    message: str
    count: int = 0


def _missing_columns(df, required):
    missing = sorted(set(required) - set(df.columns))
    return [Finding("ERROR", "missing_columns", "필수 컬럼 없음: " + ", ".join(missing), len(missing))] if missing else []


def validate_source(df, source):
    """DB에 저장하기 전 수집 결과 검사."""
    required = {
        "US": ["cik", "ticker", "name", "shares", "fiscal_year"],
        "KR": ["corp_code", "ticker", "name", "shares", "fiscal_year"],
        "PRICE": ["ticker", "price", "fetched_at"],
    }[source]
    out = _missing_columns(df, required)
    if out:
        return out

    key = "cik" if source == "US" else "corp_code" if source == "KR" else "ticker"
    duplicates = int(df[key].notna().sum() - df[key].dropna().nunique())
    if duplicates:
        out.append(Finding("ERROR", "duplicate_key", f"{key} 중복", duplicates))

    if "ticker" in df:
        blank = int(df.ticker.fillna("").astype(str).str.strip().eq("").sum())
        if blank:
            out.append(Finding("ERROR", "blank_ticker", "티커 없음", blank))
    if "shares" in df:
        shares = pd.to_numeric(df.shares, errors="coerce")
        negative, zero = int(shares.lt(0).sum()), int(shares.eq(0).sum())
        if negative:
            out.append(Finding("ERROR", "negative_shares", "주식 수가 음수", negative))
        if zero:
            out.append(Finding("WARN", "zero_shares", "주식 수가 0", zero))
    if "price" in df:
        price = pd.to_numeric(df.price, errors="coerce")
        negative, zero = int(price.lt(0).sum()), int(price.eq(0).sum())
        if negative:
            out.append(Finding("ERROR", "negative_price", "가격이 음수", negative))
        if zero:
            out.append(Finding("WARN", "zero_price", "가격이 0(거래정지·상장폐지 여부 확인)", zero))

    if source == "US":
        annual_years = sorted({int(m.group(1)) for c in df.columns
                               if (m := re.fullmatch(r"revenue_(\d{4})", c))})
        reported = set(pd.to_numeric(df.fiscal_year, errors="coerce").dropna().astype(int))
        if annual_years and reported != {max(annual_years)}:
            out.append(Finding("ERROR", "fiscal_year_mismatch",
                               "fiscal_year가 최신 연간 컬럼과 일치하지 않음"))
        if len(annual_years) >= 2 and annual_years != list(range(min(annual_years), max(annual_years) + 1)):
            out.append(Finding("ERROR", "nonconsecutive_years", "연간 재무 컬럼의 연도가 연속되지 않음"))
    return out


def validate_stocks(df, prices=None, expected_year=None):
    """화면에 쓰는 통합 데이터 검사. 경고는 이상 후보이며 반드시 오류라는 뜻은 아니다."""
    out = _missing_columns(df, ["ticker", "country", "fiscal_year", "pbr", "roe",
                                "debt_ratio", "market_cap_usd", "data_completeness"])
    if out:
        return out

    duplicates = int(df.ticker.notna().sum() - df.ticker.dropna().nunique())
    if duplicates:
        out.append(Finding("ERROR", "duplicate_ticker", "통합 티커 중복", duplicates))

    expected_year = expected_year or date.today().year - (1 if date.today().month >= 4 else 2)
    years = pd.to_numeric(df.fiscal_year, errors="coerce")
    future = int((years > expected_year).sum())
    stale = int((years < expected_year).sum())
    if future:
        out.append(Finding("ERROR", "future_fiscal_year", "기대 기준보다 미래인 재무연도", future))
    if stale:
        out.append(Finding("WARN", "stale_fiscal_year", "기대 기준보다 오래된 재무연도", stale))

    for col, limit, label in [("pbr", 1000, "PBR 절댓값 1,000 초과"),
                              ("roe", 1000, "ROE 절댓값 1,000% 초과"),
                              ("debt_ratio", 10000, "부채비율 절댓값 10,000% 초과")]:
        extreme = int(pd.to_numeric(df[col], errors="coerce").abs().gt(limit).sum())
        if extreme:
            out.append(Finding("WARN", f"extreme_{col}", label, extreme))

    cap = pd.to_numeric(df.market_cap_usd, errors="coerce")
    negative_cap, zero_cap = int(cap.lt(0).sum()), int(cap.eq(0).sum())
    if negative_cap:
        out.append(Finding("ERROR", "negative_market_cap", "시가총액이 음수", negative_cap))
    if zero_cap:
        out.append(Finding("WARN", "zero_market_cap", "시가총액이 0", zero_cap))

    low_coverage = int((pd.to_numeric(df.data_completeness, errors="coerce") < 50).sum())
    if low_coverage:
        out.append(Finding("WARN", "low_coverage", "핵심 데이터 완성도 50% 미만", low_coverage))

    if prices is not None and {"ticker", "price"}.issubset(prices.columns):
        fx = pd.to_numeric(prices.loc[prices.ticker.eq("KRW=X"), "price"], errors="coerce").dropna()
        if len(fx) != 1:
            out.append(Finding("ERROR", "missing_fx", "원/달러 환율은 정확히 1개여야 함", len(fx)))
        elif not 500 <= float(fx.iloc[0]) <= 3000:
            out.append(Finding("ERROR", "invalid_fx", f"비정상 원/달러 환율: {float(fx.iloc[0]):,.2f}", 1))
    return out


def print_report(title, findings, rows=None):
    """사람이 읽을 수 있는 수집 후 요약."""
    head = f"품질 검사 · {title}" + (f" · {rows:,}행" if rows is not None else "")
    print("\n" + head)
    if not findings:
        print("  OK · 발견된 문제 없음")
        return
    for item in findings:
        suffix = f" ({item.count:,}건)" if item.count else ""
        print(f"  {item.level} · {item.message}{suffix}")


def has_errors(findings):
    return any(item.level == "ERROR" for item in findings)


def require_no_errors(findings):
    """치명적 품질 오류가 있으면 기존 DB를 덮어쓰기 전에 중단한다."""
    errors = [item.message for item in findings if item.level == "ERROR"]
    if errors:
        raise ValueError("데이터 품질 오류: " + "; ".join(errors))
