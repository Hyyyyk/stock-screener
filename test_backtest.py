"""backtest.run/summary 자가검증 (합성 가격).  실행: python test_backtest.py"""
import numpy as np
import pandas as pd

import backtest


def test_backtest():
    dates = pd.bdate_range("2023-01-02", periods=330)
    n = len(dates)
    prices = pd.DataFrame({
        "UP": 100 * (1.002 ** np.arange(n)),     # 꾸준히 상승 → 추세·RS 둘 다 뽑혀야
        "DN": 100 * (0.998 ** np.arange(n)),     # 하락
        "FLAT.KS": np.full(n, 100.0),            # 횡보(한국 티커 — 비용 분기 확인용)
    }, index=dates)

    m = backtest.run(prices, top_n=1, warmup=252)
    assert set(m.strategy) >= {"추세", "RS", "벤치(동일가중)"}, m.strategy.unique()
    assert m.net.notna().all()

    s = backtest.summary(m)
    # 오르는 종목만 고르는 전략이 동일가중 벤치(상승+하락+횡보 평균)보다 나아야 한다
    assert s.loc["RS", "연환산%"] > s.loc["벤치(동일가중)", "연환산%"], s
    assert s.loc["추세", "연환산%"] > s.loc["벤치(동일가중)", "연환산%"], s
    assert s.loc["벤치(동일가중)", "초과(연%p)"] == 0

    # 미래정보 차단: 첫 리밸런싱은 워밍업(252거래일) 이후여야
    assert backtest.rebalance_dates(prices)  # 월말 목록 존재
    assert backtest.country("FLAT.KS") == "KR" and backtest.country("UP") == "US"
    print("ok")


if __name__ == "__main__":
    test_backtest()
