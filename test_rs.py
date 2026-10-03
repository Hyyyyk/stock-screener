"""data.relative_strength RS 백분위 자가검증.  실행: python test_rs.py"""
import pandas as pd

from data import relative_strength


def test_rs():
    df = pd.DataFrame({
        "country": ["KR", "KR", "KR", "US", "US"],
        "ret_3m": [10, 0, -10, 50, 5],
        "ret_6m": [20, 0, -20, 40, 10],
    })
    rs = relative_strength(df)
    # 나라별로 따로 순위: KR 안에서 0번이 최상(100), 2번이 최하
    assert rs[0] > rs[1] > rs[2]
    assert rs[0] == 100 and rs[3] == 100          # 각 나라 1등은 100
    # 미국 50%가 한국 10%보다 절대수익은 높아도, 순위는 나라 안에서만 매긴다
    assert rs[4] < rs[3]

    # 한쪽 결측은 있는 값으로 메움, 둘 다 없으면 NaN
    df2 = pd.DataFrame({"country": ["KR", "KR"], "ret_3m": [5, None], "ret_6m": [None, None]})
    rs2 = relative_strength(df2)
    assert rs2[0] == 100 and pd.isna(rs2[1])

    # ret 컬럼 자체가 없으면 전부 NA(옛 DB 대비)
    rs3 = relative_strength(pd.DataFrame({"country": ["KR"]}))
    assert pd.isna(rs3.iloc[0])
    print("ok")


if __name__ == "__main__":
    test_rs()
