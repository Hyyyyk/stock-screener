"""data.trend_label 추세 판정 자가검증.  실행: python test_trend.py"""
import pandas as pd

from data import trend_label


def test_trend_label():
    # 고점 바로 아래(-5%)이고 저점에서 많이 올라옴(+90%) → 상승 추세
    # 조정 중: 저점 대비 +30%↑ 이지만 고점 대비 -25% 밖 (고점 100, 현재 60 = -40%, 저점 40 → +50%)
    # 약세: 저점 근처 (고점 100, 저점 50, 현재 55 = 저점 +10% < 30%)
    df = pd.DataFrame([
        {"price": 95,  "high52": 100, "low52": 50},   # 상승 추세
        {"price": 60,  "high52": 100, "low52": 40},   # 조정 중
        {"price": 55,  "high52": 100, "low52": 50},   # 약세
        {"price": None, "high52": 100, "low52": 50},  # 유보(값 없음)
        {"price": 80,  "high52": 0,   "low52": 50},   # 유보(고점 0)
    ])
    got = list(trend_label(df))
    assert got[0] == "상승 추세", got
    assert got[1] == "조정 중", got
    assert got[2] == "약세", got
    assert pd.isna(got[3]) and pd.isna(got[4]), got

    # 경계: 정확히 고점 -25% & 저점 +30% → 상승 추세 (>= 이므로 포함)
    edge = pd.DataFrame([{"price": 75, "high52": 100, "low52": 75 / 1.30}])
    assert trend_label(edge).iloc[0] == "상승 추세"
    print("ok")


if __name__ == "__main__":
    test_trend_label()
