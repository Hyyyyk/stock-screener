"""collect_kr.latest_quarter_report 분기 선택 자가검증.  실행: python test_quarter.py"""
from datetime import date

from collect_kr import latest_quarter_report


def test_latest_quarter_report():
    # (월, 기대 reprt_code, 기대 연도offset) — 제출 마감 고려
    cases = {
        10: ("11012", 2026),   # 반기(6월말) ~8월 중순 제출 → 10월엔 반기가 최신
        11: ("11014", 2026),   # 3분기(9월말) ~11월 중순
        9:  ("11012", 2026),
        6:  ("11013", 2026),   # 1분기(3월말) ~5월 중순
        2:  ("11014", 2025),   # 1~4월: 작년 3분기가 가장 최신 분기
    }
    for m, (code, yr) in cases.items():
        y, r, lbl = latest_quarter_report(date(2026, m, 15))
        assert r == code and y == yr, (m, y, r, lbl)
    print("ok")


if __name__ == "__main__":
    test_latest_quarter_report()
