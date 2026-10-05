"""picks.performance 수익률·비용·생존편향 자가검증.  실행: python test_picks.py"""
import tempfile
from pathlib import Path

import pandas as pd

import picks


def test_performance():
    d = Path(tempfile.mkdtemp())
    picks.PICKS, picks.BENCH = d / "picks.csv", d / "bench.csv"
    pd.DataFrame([
        {"date": "2026-01-01", "ticker": "A", "name": "A", "country": "US", "entry_price": 100},
        {"date": "2026-01-01", "ticker": "B", "name": "B", "country": "US", "entry_price": 50},
    ]).to_csv(picks.PICKS, index=False, encoding="utf-8-sig")
    pd.DataFrame([{"date": "2026-01-01", "country": "US", "ticker": "SPY", "entry_price": 400}]
                 ).to_csv(picks.BENCH, index=False, encoding="utf-8-sig")

    # A는 2배(+100%), B는 현재가 없음(상폐 → -100%로 집계). 비용 US 0.1% 차감.
    perf = picks.performance({"A": 200}, {"SPY": 440})
    row = perf.iloc[0]
    assert row.종목수 == 2
    assert abs(row.전략수익률 - (-0.1)) < 1e-6, row.전략수익률   # (99.9 + -100.1)/2
    assert abs(row.벤치수익률 - 10.0) < 1e-6, row.벤치수익률     # 440/400-1
    assert abs(row.초과 - (-10.1)) < 1e-6, row.초과
    assert row.보유일 >= 0

    # 저장된 추천이 없으면 빈 결과
    picks.PICKS = d / "none.csv"
    assert picks.performance({}, {}).empty
    print("ok")


if __name__ == "__main__":
    test_performance()
