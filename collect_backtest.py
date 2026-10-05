"""백테스트용 과거 일별 종가 수집 — Yahoo spark 5년.  실행: python collect_backtest.py

추세·RS 처럼 '가격만 쓰는' 신호를 과거로 검증하려는 데이터. 재무가 아니라 가격이라 과거를
받을 수 있다. 스크리너 기본 유니버스(주요 거래소·시총 $100M+)만 받는다.

⚠️ 생존편향: 지금 상장된 종목만 있어 그동안 상폐·부도난 종목이 빠져 있다. 이 데이터로 돌린
백테스트 성과는 실제보다 부풀려진 '상한선'으로 봐야 한다(완전히 못 고침).

로컬 연구용이라 backtest_prices.pkl 에 저장하고 커밋하지 않는다(.gitignore).
"""
import json
import time
import urllib.error
import urllib.request

import pandas as pd

import data
import screener

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
BATCH = 20
PAUSE = 0.3
RANGE = "5y"
MAJOR = ("Nasdaq", "NYSE", "KOSPI", "KOSDAQ")
OUT = "backtest_prices.pkl"


def spark_history(symbols):
    """{ticker: 일별 종가 Series(date index)} — 없는 티커는 빠진다."""
    url = ("https://query1.finance.yahoo.com/v7/finance/spark?symbols="
           + ",".join(symbols) + f"&range={RANGE}&interval=1d")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                results = json.load(r)["spark"]["result"]
            break
        except urllib.error.HTTPError as e:
            if e.code == 400:
                return {}
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    else:
        return {}

    out = {}
    for item in results:
        rsp = item["response"][0]
        ts = rsp.get("timestamp") or []
        cl = (rsp.get("indicators", {}).get("quote", [{}])[0].get("close")) or []
        n = min(len(ts), len(cl))
        if n < 2:
            continue
        s = pd.Series(cl[:n], index=pd.to_datetime(ts[:n], unit="s").normalize()).dropna()
        if not s.empty:
            out[rsp["meta"]["symbol"]] = s[~s.index.duplicated(keep="last")]
    return out


def universe_tickers():
    df = data.load_stocks()
    markets = [m for m in MAJOR if m in set(df.market)]
    u = screener.prepare_universe(df, markets, 1e8, True, False, False)   # $100M, ETF 제외
    return u.ticker.tolist()


def main():
    tickers = universe_tickers()
    print(f"유니버스 {len(tickers):,}종목 · {-(-len(tickers) // BATCH):,}회 호출 (range={RANGE})")
    series, started = {}, time.time()
    for i in range(0, len(tickers), BATCH):
        series.update(spark_history(tickers[i:i + BATCH]))
        if (i // BATCH) % 25 == 0 and i:
            rate = (i / BATCH) / (time.time() - started)
            print(f"  {i:>5,}/{len(tickers):,}  받음 {len(series):,}  "
                  f"남은 {((len(tickers) - i) / BATCH) / rate / 60:.0f}분", flush=True)
        time.sleep(PAUSE)

    prices = pd.DataFrame(series).sort_index()
    prices.to_pickle(OUT)
    print(f"\n{OUT}: {prices.shape[0]:,}일 × {prices.shape[1]:,}종목 "
          f"({prices.index.min().date()}~{prices.index.max().date()})")
    return prices


if __name__ == "__main__":
    main()
