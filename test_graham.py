"""data.graham 그레이엄 수 적정가·안전마진 자가검증.  실행: python test_graham.py"""
import math

import pandas as pd

from data import graham


def test_graham():
    df = pd.DataFrame([
        {"net_income": 50, "equity": 200, "shares": 10, "price": 30},   # EPS5·BPS20 → 적정가 47.43
        {"net_income": -10, "equity": 200, "shares": 10, "price": 30},  # 적자 → 유보
        {"net_income": 50, "equity": -5, "shares": 10, "price": 30},    # 자본잠식 → 유보
        {"net_income": 50, "equity": 200, "shares": 10, "price": 100},  # 고평가 → 마진 음수
    ])
    g = graham(df)
    assert math.isclose(g.fair.iloc[0], (22.5 * 5 * 20) ** 0.5, rel_tol=1e-6)
    assert round(g.margin.iloc[0]) == 58                 # 47.43/30-1 ≈ +58%
    assert pd.isna(g.fair.iloc[1]) and pd.isna(g.margin.iloc[1])   # 적자
    assert pd.isna(g.fair.iloc[2])                                 # 자본잠식
    assert g.margin.iloc[3] < 0                                    # 적정가 위

    # 필수 컬럼이 없으면 전부 NaN(옛 데이터·일부 종목 대비)
    assert graham(pd.DataFrame({"price": [10]})).margin.isna().all()
    print("ok")


if __name__ == "__main__":
    test_graham()
