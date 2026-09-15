"""한국 연도별 실적 파싱 자체 점검 (네트워크 없음).  실행: python test_history.py"""
import pandas as pd

from data import parse_kr_history


def r(sj, aid, cur, prev, prev2):
    return {"sj_div": sj, "account_id": aid,
            "thstrm_amount": cur, "frmtrm_amount": prev, "bfefrmtrm_amount": prev2}


reports = {
    2025: [
        r("IS", "ifrs-full_Revenue", "", "20000000000", "10000000000"),        # 당기 칸이 비어 있다
        r("IS", "dart_OperatingIncomeLoss", "5000000000", "4000000000", "3000000000"),
        r("IS", "ifrs-full_ProfitLoss", "3000000000", "2000000000", "-1000000000"),
        r("CF", "ifrs-full_ProfitLoss", "999900000000", "999900000000", "999900000000"),
        r("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "7000000000", "6000000000", "5000000000"),
        r("IS", "-표준계정코드 미사용-", "8800000000", "8800000000", "8800000000"),
    ],
    2022: [                                                                      # 금융사식 계정
        r("CIS", "ifrs-full_InterestRevenueExpense", "1000000000", "900000000", "800000000"),
        r("CIS", "ifrs-full_ProfitLossFromOperatingActivities", "500000000", "400000000", "-"),
    ],
}
h = parse_kr_history(reports).set_index("연도")

assert list(h.index) == [2020, 2021, 2022, 2023, 2024, 2025]      # 두 보고서로 여섯 해
assert pd.isna(h.at[2025, "매출액"]) and h.at[2024, "매출액"] == 200 and h.at[2023, "매출액"] == 100
assert h.at[2022, "매출액"] == 10 and h.at[2020, "매출액"] == 8   # 매출 없으면 순이자손익으로 대체 (억 원)
assert h.at[2021, "영업이익"] == 4 and pd.isna(h.at[2020, "영업이익"])   # '-' 는 값 없음
assert h.at[2023, "순이익"] == -10                                # 손익계산서 값. 현금흐름표 쪽(9,999억)이 아니다
assert h.at[2025, "영업CF"] == 70 and "투자CF" not in h
assert list(h.columns[:3]) == ["매출액", "영업이익", "순이익"]

assert parse_kr_history({2025: [], 2022: []}).empty              # 보고서가 없으면 빈 표

# 같은 해가 두 보고서에 겹치면 최신 보고서(수정 반영) 값이 이긴다. 넘기는 순서와 무관해야 한다
old = {2023: [r("IS", "ifrs-full_ProfitLoss", "1000000000", "900000000", "800000000")]}      # 2023·2022·2021
new = {2025: [r("IS", "ifrs-full_ProfitLoss", "3000000000", "2000000000", "1100000000")]}    # 2025·2024·2023(수정)
for merged in ({**old, **new}, {**new, **old}):
    m = parse_kr_history(merged).set_index("연도")
    assert list(m.index) == [2021, 2022, 2023, 2024, 2025]
    assert m.at[2023, "순이익"] == 11 and m.at[2022, "순이익"] == 9   # 2023 은 2025년 보고서 값

print("ok")
