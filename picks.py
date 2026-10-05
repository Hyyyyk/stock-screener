"""전방 추적(paper-trade) — 오늘 추천 종목을 스냅샷 저장하고 나중에 성과를 계산한다.

과거 시점 재무가 없어 제대로 된 과거 백테스트가 불가능하므로, 오늘부터 실제 추천을
기록해 out-of-sample 로 검증한다(lookahead·과최적화 없음). 상폐·거래정지로 현재가가
없는 종목은 조용히 빼지 않고 '손실'로 집계해 생존편향을 막는다.

picks.csv 는 커밋해서 재배포·다른 PC에도 남긴다(클라우드는 읽기 전용이라 저장은 로컬에서).
"""
import pandas as pd

from settings import PICKS, BENCH

# 왕복 거래비용 어림(제 제안): 수수료+세금+슬리피지. 한국은 매도 증권거래세가 커서 높다.
COST = {"KR": 0.3, "US": 0.1}       # %
BENCH_TICKER = {"US": "SPY", "KR": "069500.KS"}   # S&P500 · KODEX 200


def _append(path, rows):
    df = pd.DataFrame(rows)
    header = not path.exists()
    df.to_csv(path, mode="a", header=header, index=False, encoding="utf-8-sig")


def snapshot(view, preset, bench_prices):
    """상위 종목(view)과 벤치마크 가격을 오늘 날짜로 기록한다. 저장한 종목 수를 돌려준다."""
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    rows = [{
        "date": today, "ticker": r.ticker, "name": r["name"], "country": r.country,
        "entry_price": r.price, "currency": r.get("currency"), "score": round(float(r.score), 1),
        "trend": r.get("trend_label"), "rs": None if pd.isna(r.get("rs")) else round(float(r.rs)),
        "preset": preset,
    } for _, r in view.iterrows()]
    _append(PICKS, rows)
    _append(BENCH, [{"date": today, "country": c, "ticker": t, "entry_price": bench_prices.get(t)}
                    for c, t in BENCH_TICKER.items() if bench_prices.get(t)])
    return len(rows)


def price_snapshot():
    """벤치마크(SPY·KODEX200) 현재가를 {ticker: price} 로. 네트워크 호출이라 호출부에서 캐시한다."""
    import collect_price
    return {d["ticker"]: d["price"] for d in collect_price.spark(list(BENCH_TICKER.values()))}


def load():
    try:
        return pd.read_csv(PICKS, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


def performance(now_price, bench_now):
    """코호트(저장일)별 성과. now_price: {ticker: 현재가}, bench_now: {ticker: 현재가}.

    돌려주는 컬럼: date, 종목수, 보유일, 전략수익률(%), 벤치수익률(%), 초과(%).
    현재가가 없는 종목(상폐 등)은 -100%로 보고 평균에 포함한다(생존편향 방지).
    """
    picks = load()
    if picks.empty:
        return pd.DataFrame()
    bench = pd.read_csv(BENCH, encoding="utf-8-sig") if BENCH.exists() else pd.DataFrame()
    today = pd.Timestamp.now().normalize()
    out = []
    for date, g in picks.groupby("date"):
        cur = g.ticker.map(now_price)
        gross = (cur / g.entry_price - 1) * 100
        gross = gross.where(cur.notna(), -100.0)          # 현재가 없음 = 상폐/정지 → 전액 손실
        net = gross - g.country.map(COST).fillna(0.2)     # 왕복 비용 차감
        row = {"date": date, "종목수": len(g), "보유일": (today - pd.Timestamp(date)).days,
               "전략수익률": net.mean()}
        if not bench.empty:
            b = bench[bench.date == date]
            brs = [(bench_now.get(t) / p - 1) * 100 for t, p in zip(b.ticker, b.entry_price)
                   if bench_now.get(t) and p]
            row["벤치수익률"] = sum(brs) / len(brs) if brs else None
            row["초과"] = row["전략수익률"] - row["벤치수익률"] if brs else None
        out.append(row)
    return pd.DataFrame(out).sort_values("date", ascending=False)
