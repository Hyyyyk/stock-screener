"""데이터 품질 규칙 점검. pytest와 `python test_quality.py` 양쪽에서 실행 가능."""
import pandas as pd

from quality import has_errors, validate_source, validate_stocks


def valid_stocks():
    return pd.DataFrame({
        "ticker": ["A", "B"], "country": ["US", "KR"], "fiscal_year": [2025, 2025],
        "pbr": [2.0, 1.0], "roe": [10.0, 20.0], "debt_ratio": [30.0, 40.0],
        "market_cap_usd": [1e9, 2e9], "data_completeness": [100.0, 80.0],
    })


def test_clean_data_passes():
    px = pd.DataFrame({"ticker": ["KRW=X"], "price": [1400.0]})
    assert validate_stocks(valid_stocks(), px, expected_year=2025) == []


def test_duplicate_future_and_bad_fx_are_errors():
    df = valid_stocks()
    df.loc[1, "ticker"] = "A"
    df.loc[1, "fiscal_year"] = 2026
    px = pd.DataFrame({"ticker": ["KRW=X"], "price": [10.0]})
    found = validate_stocks(df, px, expected_year=2025)
    assert has_errors(found)
    assert {x.code for x in found} >= {"duplicate_ticker", "future_fiscal_year", "invalid_fx"}


def test_source_rejects_negative_shares():
    us = pd.DataFrame({"cik": [1], "ticker": ["A"], "name": ["A Inc"],
                       "shares": [-1], "fiscal_year": [2025]})
    found = validate_source(us, "US")
    assert any(x.code == "negative_shares" for x in found)


if __name__ == "__main__":
    test_clean_data_passes()
    test_duplicate_future_and_bad_fx_are_errors()
    test_source_rejects_negative_shares()
    print("ok")
