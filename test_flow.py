"""수급 계산 자체 점검 (네트워크 없음).  실행: python test_flow.py"""
import pandas as pd

from collect_flow import summarize_trend, to_int
from data import weighted_score


def day(d, f, o, c, hold="10.00%"):
    return {"bizdate": d, "foreignerPureBuyQuant": f, "organPureBuyQuant": o,
            "closePrice": c, "foreignerHoldRatio": hold}


# 1) 네이버 숫자 문자열
assert to_int("+1,379,866") == 1379866 and to_int("-1,088,039") == -1088039 and to_int("") is None

# 2) 순매수량 × 그날 종가를 20거래일 더한다 (최신 행이 앞)
rows = [day("20260915", "+100", "-40", "1,000", "46.55%"),
        day("20260914", "-20", "+10", "2,000")] + [day(f"202608{i:02d}", "0", "0", "3,000") for i in range(18)]
s = summarize_trend(rows, days=20)
assert s["flow_foreign_amt"] == 100 * 1000 - 20 * 2000          # 60,000
assert s["flow_inst_amt"] == -40 * 1000 + 10 * 2000             # -20,000
assert s["flow_net_amt"] == 40_000
assert s["foreign_hold_ratio"] == 46.55 and s["flow_asof"] == "20260915"
assert summarize_trend(rows[:5], days=20) is None                                   # 20거래일이 안 되면 보류
assert summarize_trend(rows[:-1] + [day("20260801", "", "0", "3,000")], days=20) is None   # 빈칸이 끼면 보류

# 3) 점수는 값이 있는 축만으로 평균낸다 - 수급이 없는 미국 종목이 깎이지 않는다
pct = pd.DataFrame({"pbr": [80.0, 80.0, None], "flow_net": [60.0, None, None]})
sc = weighted_score(pct, {"pbr": 1.0, "flow_net": 1.0, "roe": 2.0})   # 표에 없는 축(roe)은 무시
assert sc[0] == 70 and sc[1] == 80 and pd.isna(sc[2])

print("ok")
