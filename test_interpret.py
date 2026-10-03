"""data.interpret 한 줄 해석 규칙 자가검증.  실행: python test_interpret.py"""
import pandas as pd

from data import interpret


def row(**kw):
    base = {"pbr": None, "roe": None, "op_growth": None, "debt_ratio": None, "flow_net": None}
    return pd.Series({**base, **kw})


def test_interpret():
    # 싸고(PBR<1) 잘 버는데(ROE 높음) 성장이 꺾임 → 강점 둘 + 역성장 주의
    t = interpret(row(pbr=0.8, roe=18, op_growth=-12))
    assert "싼 가격(PBR 0.80)" in t and "ROE 18%" in t
    assert "주의" in t and "줄고 있다(-12%)" in t

    # 약점만 (비싸고 부채 많음) → 강점 없음 문구 + 주의
    t = interpret(row(pbr=8, debt_ratio=300))
    assert t.startswith("두드러지는 강점은 적음") and "부채가 많다(300%)" in t

    # 값이 하나도 없으면 강점 없음, 주의 없음
    assert interpret(row()) == "두드러지는 강점은 적음"

    # 강점은 최대 2개까지만 (셋 충족시 잘림)
    t = interpret(row(pbr=0.5, roe=20, debt_ratio=30))
    assert t.count(",") == 1 and "주의" not in t

    # 수급 데드밴드: 소폭(+0.05)은 언급 안 함
    assert "사는 중" not in interpret(row(flow_net=0.05))
    assert "사는 중" in interpret(row(flow_net=0.5))
    print("ok")


if __name__ == "__main__":
    test_interpret()
