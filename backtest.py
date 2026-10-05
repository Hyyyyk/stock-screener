"""추세·RS 신호 과거 백테스트 (가격 전용).  실행: python backtest.py

collect_backtest.py 가 만든 backtest_prices.pkl(일별 종가 행렬)을 월말마다 리밸런싱하며,
그 시점까지의 가격만으로 신호를 계산해(미래정보 차단) 상위 N종목을 1개월 보유한다.
벤치마크는 같은 유니버스 동일가중 — "신호가 시장(동일가중)을 이겼나"를 직접 본다.

⚠️ 생존편향: 데이터가 현재 상장 종목뿐이라 상폐분이 빠져 성과가 부풀려진다. '상한선'으로 볼 것.
임계값(−25%/+30%, RS 블렌딩)은 제 제안값 그대로 — 여기서 맞추면 과최적화라 손대지 않는다.
"""
import pandas as pd

TOP_N = 20
WARMUP = 252                         # 추세의 52주 고·저 계산에 필요한 거래일
COST = {"KR": 0.3, "US": 0.1}        # 왕복 거래비용(%) — 회전분에만 차감


def country(ticker):
    return "KR" if str(ticker).endswith((".KS", ".KQ")) else "US"


def rebalance_dates(prices):
    """월말 거래일 목록."""
    s = pd.Series(prices.index, index=prices.index)
    return list(s.groupby(prices.index.to_period("M")).last())


def run(prices, top_n=TOP_N, warmup=WARMUP):
    """월별 전략·벤치 순수익률(%) long DataFrame[date, strategy, net, n]."""
    dates = [d for d in rebalance_dates(prices) if prices.index.get_loc(d) >= warmup]
    rows, prev = [], {"추세": set(), "RS": set()}
    for t, t1 in zip(dates[:-1], dates[1:]):
        i = prices.index.get_loc(t)
        price = prices.loc[t]
        win = prices.iloc[i - warmup:i + 1]                    # t 까지만 (미래정보 없음)
        hi, lo = win.max(), win.min()
        p63, p126 = prices.iloc[i - 63], prices.iloc[i - 126]
        fwd = prices.loc[t1] / price - 1                       # t → t1 수익률

        valid = price.notna() & hi.notna() & lo.notna() & (lo > 0)
        trend_ok = valid & (price >= 0.75 * hi) & (price >= 1.30 * lo)
        trend_pick = (price / hi).where(trend_ok).dropna().nlargest(top_n).index
        rs = 2 * (price / p63 - 1).where(p63 > 0) + (price / p126 - 1).where(p126 > 0)
        rs_pick = rs.where(valid).dropna().nlargest(top_n).index

        for name, pick in [("추세", trend_pick), ("RS", rs_pick)]:
            r = fwd.reindex(pick).dropna()
            if len(r) == 0:
                continue
            turnover = len(set(pick) - prev[name]) / len(pick)
            cost = turnover * sum(COST[country(t_)] for t_ in pick) / len(pick)
            rows.append({"date": t1, "strategy": name, "net": r.mean() * 100 - cost, "n": len(r)})
            prev[name] = set(pick)
        bench = fwd[valid].dropna()
        rows.append({"date": t1, "strategy": "벤치(동일가중)", "net": bench.mean() * 100, "n": len(bench)})
    return pd.DataFrame(rows)


def summary(monthly):
    """전략별 요약: 월수·누적%·연환산%·월승률%·최대낙폭%·벤치대비 초과(연%)."""
    out = {}
    for name, g in monthly.groupby("strategy"):
        g = g.sort_values("date")
        growth = (1 + g.net / 100)
        curve = growth.cumprod()
        months = len(g)
        cum = curve.iloc[-1] - 1
        cagr = curve.iloc[-1] ** (12 / months) - 1 if months else 0
        mdd = (curve / curve.cummax() - 1).min()
        out[name] = {"월수": months, "누적%": cum * 100, "연환산%": cagr * 100,
                     "월승률%": (g.net > 0).mean() * 100, "최대낙폭%": mdd * 100}
    df = pd.DataFrame(out).T
    if "벤치(동일가중)" in df.index:                       # 초과수익(연환산, %p)
        df["초과(연%p)"] = df["연환산%"] - df.loc["벤치(동일가중)", "연환산%"]
    return df.round(1)


def main():
    prices = pd.read_pickle("backtest_prices.pkl")
    print(f"가격: {prices.shape[0]:,}일 × {prices.shape[1]:,}종목 "
          f"({prices.index.min().date()}~{prices.index.max().date()})")
    monthly = run(prices)
    print(f"\n리밸런싱 {monthly.date.nunique()}개월\n")
    print(summary(monthly).to_string())
    print("\n[주의] 생존편향으로 실제보다 부풀려진 상한선. 임계값은 미튜닝(과최적화 방지).")


if __name__ == "__main__":
    main()
