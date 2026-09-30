"""분리된 스크리닝 계산 회귀 테스트."""
import pandas as pd

import data
import screener


def sample():
    return pd.DataFrame({
        "ticker": ["A", "B", "C", "D"], "country": ["US", "US", "KR", "KR"],
        "market": ["NYSE", "NYSE", "KOSPI", "KOSPI"], "kind": ["EQUITY"] * 4,
        "sector": ["전자·반도체", "은행·증권", "전자·반도체", "보험"],
        "market_cap": [100, 200, 100, 200], "market_cap_usd": [100, 200, 100, 200],
        "rev_up_3y": [True] * 4, "turnaround": [False] * 4,
        "pbr": [1.0, 2.0, 3.0, 4.0], "roe": [10.0, 20.0, 30.0, 40.0],
        "op_growth": [1.0, 2.0, 3.0, 4.0], "debt_ratio": [10.0, 900.0, 30.0, 800.0],
        "flow_net": [None, None, 1.0, 2.0],
    })


def test_prepare_and_percentiles_respect_applicability():
    universe = screener.prepare_universe(sample(), ["NYSE", "KOSPI"])
    pct, applicable = screener.percentiles(universe, data.CORE, by_sector=False)
    assert pct.loc[universe.country.eq("US"), "flow_net"].isna().all()
    assert pct.loc[universe.sector.isin(data.FINANCIAL_SECTORS), "debt_ratio"].isna().all()
    assert not applicable["debt_ratio"].loc[1]


def test_inapplicable_filter_is_skipped():
    universe = screener.prepare_universe(sample(), ["NYSE", "KOSPI"])
    pct, applicable = screener.percentiles(universe, data.CORE, by_sector=False)
    filters = [("수급", "flow_net", "min", None, 50)]
    steps = screener.apply_filters(universe, filters, {"flow_net": 0.0}, pct, applicable, False)
    assert set(steps[-1][1].ticker) == {"A", "B", "C", "D"}


if __name__ == "__main__":
    test_prepare_and_percentiles_respect_applicability()
    test_inapplicable_filter_is_skipped()
    print("ok")
