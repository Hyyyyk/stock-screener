"""시세 수집 - Yahoo spark API.  실행: python collect_price.py

재무(collect_us.py)는 분기마다, 시세는 매일 갱신하는 성격이라 테이블을 나눠 둔다.
spark 는 한 번에 20종목까지만 받는다(21개부터 400). 5,000종목이면 250여 회.
"""
import json
import sqlite3
import time
import urllib.error
import urllib.request

import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
DB = "stocks.db"
BATCH = 20            # spark 상한
PAUSE = 0.3           # 야후 배려


def spark(symbols):
    """[{symbol, price, ...}] - 없는 티커는 응답에서 그냥 빠진다."""
    url = ("https://query1.finance.yahoo.com/v7/finance/spark?symbols="
           + ",".join(symbols) + "&range=1d&interval=1d")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                results = json.load(r)["spark"]["result"]
            break
        except urllib.error.HTTPError as e:
            if e.code == 400:                       # 배치에 이상한 티커가 섞인 경우
                return []
            time.sleep(2 ** attempt)                # 429/5xx 는 물러섰다 재시도
        except Exception:
            time.sleep(2 ** attempt)
    else:
        return []

    out = []
    for item in results:
        m = item["response"][0]["meta"]
        prev = m.get("chartPreviousClose")
        price = m.get("regularMarketPrice")
        if price is None:
            continue
        out.append({
            "ticker": m["symbol"], "price": price, "currency": m.get("currency"),
            "prev_close": prev,
            "change_pct": (price / prev - 1) * 100 if prev else None,
            "high52": m.get("fiftyTwoWeekHigh"), "low52": m.get("fiftyTwoWeekLow"),
            "volume": m.get("regularMarketVolume"),
            "kind": m.get("instrumentType"),      # EQUITY / ETF / … - ETF 를 걸러내려고 받는다
        })
    return out


def main():
    with sqlite3.connect(DB) as con:
        tickers = pd.read_sql(
            "select distinct ticker from us_fundamentals where ticker is not null", con
        ).ticker.tolist()
        try:                                    # 한국 종목은 005930.KS 형태로 야후에 있다
            tickers += pd.read_sql(
                "select distinct ticker from kr_fundamentals where ticker is not null", con
            ).ticker.tolist()
        except pd.errors.DatabaseError:
            pass                                # collect_kr.py 를 아직 안 돌린 경우
    tickers.append("KRW=X")                     # 원/달러 환율 - 한·미 시가총액을 같은 잣대로 비교하려고

    print(f"{len(tickers):,}종목 · {-(-len(tickers) // BATCH):,}회 호출")
    rows, missed = [], 0
    for i in range(0, len(tickers), BATCH):
        chunk = tickers[i:i + BATCH]
        got = spark(chunk)
        rows += got
        missed += len(chunk) - len(got)
        if (i // BATCH) % 25 == 0:
            print(f"  {i + len(chunk):>5,}/{len(tickers):,}  받음 {len(rows):,}")
        time.sleep(PAUSE)

    df = pd.DataFrame(rows).drop_duplicates("ticker")
    df["fetched_at"] = pd.Timestamp.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB) as con:
        df.to_sql("prices", con, if_exists="replace", index=False)
    print(f"\n{DB} · prices · {len(df):,}종목 저장 (시세 없음 {missed:,}종목)")
    return df


if __name__ == "__main__":
    main()
