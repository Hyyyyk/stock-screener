"""market_data.stage_analysis / moving_averages 자가검증.  실행: python test_stage.py"""
import pandas as pd

from market_data import STAGE_MA, SLOPE_LOOKBACK, moving_averages, stage_analysis

N = STAGE_MA + SLOPE_LOOKBACK + 10


def hist(prices):
    return pd.DataFrame({"날짜": pd.date_range("2025-01-01", periods=len(prices)), "종가": prices})


def test_stage():
    rising = hist([100 + i for i in range(N)])            # 꾸준히 오름 → 이평 상승·가격 위
    label, slope = stage_analysis(rising)
    assert label == "2단계 · 상승" and slope > 1, (label, slope)

    falling = hist([100 + (N - i) for i in range(N)])     # 꾸준히 내림 → 이평 하락·가격 아래
    label, slope = stage_analysis(falling)
    assert label == "4단계 · 하락" and slope < -1, (label, slope)

    flat = hist([100] * N)                                # 평탄 → 가격=이평(>=) → 3단계
    label, slope = stage_analysis(flat)
    assert label.startswith("3단계") and abs(slope) <= 1, (label, slope)

    assert stage_analysis(hist([100] * 50)) is None        # 이력 부족 → 판단 유보

    ma = moving_averages(hist([100 + i for i in range(N)]))
    assert "50일" in ma and "150일" in ma
    assert ma["150일"].isna().sum() == STAGE_MA - 1        # 앞쪽 149개는 아직 평균 못 냄
    print("ok")


if __name__ == "__main__":
    test_stage()
