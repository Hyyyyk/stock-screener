"""비교 그룹 등수 자체 점검.  실행: python test_peers.py"""
import pandas as pd
from datetime import date

from data import (SHRINK_K, expected_annual_year, metric_applicable, mid_pct,
                  peer_pct, score_reason, size_bucket, weighted_score)
from collect_us import latest_annual_year, recent_instant_periods

# 1) 중간순위 백분위는 종목 수가 적어도 위아래가 대칭이다
two = pd.DataFrame({"g": [0, 0], "v": [1.0, 2.0]})
assert list(mid_pct(two.groupby("g").v, True)) == [25.0, 75.0]
assert list(mid_pct(two.groupby("g").v, False)) == [75.0, 25.0]
assert (mid_pct(two.groupby("g").v, True) >= 50).sum() == 1      # 2종목 그룹의 '상위 50%' 는 1개

# 2) 값이 없으면 등수도 없고, 남은 종목끼리 매긴다
gap = pd.DataFrame({"g": [0, 0, 0], "v": [1.0, None, 3.0]})
p = mid_pct(gap.groupby("g").v, True)
assert pd.isna(p[1]) and list(p.dropna()) == [25.0, 75.0]

# 3) 규모 3등분: 고르게 나누고, 시총이 없거나 3개 미만이면 비운다
b = size_bucket(pd.Series([1, 2, 3, 4, 5, 6, None]))
assert list(b[:6]) == ["소형", "소형", "중형", "중형", "대형", "대형"] and pd.isna(b[6])
assert size_bucket(pd.Series([1.0, None])).isna().all()

# 4) 작은 그룹은 부모(같은 나라·규모) 등수 쪽으로 당겨진다
#    한국 소형 60종목 중 리츠는 2개. 리츠 안에선 1등(75점)이지만 소형 전체에선 중간쯤이다.
rows = [{"country": "KR", "size_bucket": "소형", "sector": "제조", "roe": float(i)} for i in range(58)]
rows += [{"country": "KR", "size_bucket": "소형", "sector": "리츠", "roe": 28.75},   # 제조 값(0~57)과
         {"country": "KR", "size_bucket": "소형", "sector": "리츠", "roe": 28.25}]   # 동점이 안 나게
df = pd.DataFrame(rows)
top_reit = peer_pct(df, "roe", True, by_peer=True)[58]
in_group, in_parent = 75.0, (31 - 0.5) / 60 * 100               # 28.75 는 60종목 중 31번째
assert abs(top_reit - (2 * in_group + SHRINK_K * in_parent) / (2 + SHRINK_K)) < 1e-9
assert in_parent < top_reit < 55, top_reit                      # 75점이 아니라 52점 근처로 내려온다

# 5) 비교 그룹을 끄면 전체 표본 등수 그대로
assert peer_pct(df, "roe", True, by_peer=False)[58] == in_parent

# 6) 공시 전인 1~3월에는 전전년, 4월부터는 전년을 최신 완료연도로 본다
assert expected_annual_year(date(2027, 3, 31)) == 2025
assert expected_annual_year(date(2027, 4, 1)) == 2026
assert latest_annual_year(date(2027, 4, 1)) == 2026
assert recent_instant_periods(date(2026, 9, 30)) == ["CY2026Q2I", "CY2026Q1I", "CY2025Q4I", "CY2025Q3I"]

# 7) 미국 수급과 금융사 부채비율은 적용하지 않는다
rules = pd.DataFrame({"country": ["US", "KR", "KR"],
                      "sector": ["전자·반도체", "은행·증권", "전자·반도체"]})
assert metric_applicable(rules, "flow_net").tolist() == [False, True, True]
assert metric_applicable(rules, "debt_ratio").tolist() == [True, False, True]

# 8) 적용하지 않는 축(NaN)은 점수 분모에서 빠지고, 선정 이유는 강한 축부터 설명한다
scores = pd.DataFrame({"pbr": [90.0], "roe": [70.0], "debt_ratio": [None]})
assert weighted_score(scores, {"pbr": 1, "roe": 1, "debt_ratio": 1}).iloc[0] == 80
assert score_reason(scores.iloc[0]) == "PBR 상위 10% · ROE 상위 30%"
one_axis = pd.DataFrame({"pbr": [99.0], "roe": [None]})
assert pd.isna(weighted_score(one_axis, {"pbr": 1, "roe": 1}, min_axes=2).iloc[0])

print("ok")
