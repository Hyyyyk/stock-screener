"""프로젝트 전역 경로와 화면 설정."""
from pathlib import Path

DB = "stocks.db"
CACHE = Path("cache")
WATCHLIST = Path("watchlist.json")     # 관심종목 (로컬 전용)

PRESETS = {
    "균형": {"pbr": 1.0, "roe": 1.0, "op_growth": 1.0, "debt_ratio": 0.7, "flow_net": 0.7},
    "저평가 중시": {"pbr": 2.0, "roe": 1.0, "op_growth": 0.5, "debt_ratio": 1.0, "flow_net": 0.5},
    "성장 중시": {"pbr": 0.7, "roe": 1.2, "op_growth": 2.0, "debt_ratio": 0.5, "flow_net": 1.0},
}

CAP_STEPS = {"제한 없음": 0, "$50M": 5e7, "$100M": 1e8, "$300M": 3e8,
             "$1B": 1e9, "$5B": 5e9, "$50B": 5e10}

FILTERS = [
    ("① 싼가", "pbr", "max", ("PBR 상한 (배)", 0.2, 12.0, 1.5, 0.1), 30),
    ("② 잘 버는가", "roe", "min", ("ROE 하한 (%)", -30.0, 60.0, 8.0, 0.5), 50),
    ("③ 크고 있는가", "op_growth", "min", ("영업이익 증가율 하한 (%)", -100.0, 300.0, 0.0, 5.0), 50),
    ("④ 안전한가", "debt_ratio", "max", ("부채비율 상한 (%)", 10.0, 500.0, 150.0, 10.0), 50),
    ("⑤ 남들도 사는가", "flow_net", "min", ("수급 하한 (시총 대비 %)", -5.0, 5.0, 0.0, 0.1), 50),
]
