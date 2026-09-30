"""한국 수급 수집 - 네이버 모바일 증권 API (비공식).  실행: python collect_flow.py

KRX 공식 투자자별 매매는 로그인이 필요해졌고(data.krx.co.kr → LOGOUT), DART·SEC 에는 없다.
그래서 비공식인 네이버 모바일 API 를 쓴다. 예고 없이 막히거나 형식이 바뀔 수 있다.

종목당 1호출이라 하나씩 천천히 받고, 200종목마다 저장한다.
같은 날 다시 돌리면 오늘 이미 받은 종목은 건너뛴다.
"""
import json
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import date

import pandas as pd
from settings import DB

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
DAYS = 20                 # 최근 20거래일 누적
PAUSE = 0.3               # 요청 사이 쉬는 시간
SAVE_EVERY = 200
MAX_CONSECUTIVE_FAIL = 20  # 연속으로 이만큼 실패하면 차단으로 보고 멈춘다 (재시도만 하며 몇 시간 도는 걸 막는다)


def to_int(s):
    """'+1,379,866' → 1379866, 빈칸은 None."""
    s = str(s or "").replace(",", "").replace("+", "").strip()
    try:
        return int(float(s))
    except ValueError:
        return None


def summarize_trend(rows, days=DAYS):
    """네이버 일별 행(최신이 앞) → 최근 days 거래일 외국인·기관 순매수 금액(원).

    주식 수 그대로는 삼성전자와 소형주를 비교할 수 없어 그날 종가를 곱해 금액으로 만든다.
    거래일이 모자라거나 빈칸이 끼면 판단을 보류(None)한다.
    """
    rows = rows[:days]
    if len(rows) < days:
        return None
    foreign = inst = 0
    for r in rows:
        f, o, c = (to_int(r.get(k)) for k in ("foreignerPureBuyQuant", "organPureBuyQuant", "closePrice"))
        if f is None or o is None or c is None:
            return None
        foreign += f * c
        inst += o * c
    hold = str(rows[0].get("foreignerHoldRatio") or "").rstrip("%")
    return {"flow_foreign_amt": foreign, "flow_inst_amt": inst, "flow_net_amt": foreign + inst,
            "foreign_hold_ratio": float(hold) if hold.replace(".", "", 1).isdigit() else None,
            "flow_asof": rows[0].get("bizdate"), "flow_days": days}


def fetch(code):
    """('ok', 요약) / ('nodata', None) / ('fail', None). 실패를 '데이터 없음'으로 숨기지 않는다."""
    url = f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize={DAYS}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                rows = json.load(r)
            time.sleep(PAUSE)
            rec = summarize_trend(rows if isinstance(rows, list) else [])
            return ("ok", rec) if rec else ("nodata", None)
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:      # 없는 종목 등 - 재시도해도 소용없다
                return "nodata", None
            time.sleep(30 if e.code == 429 else 2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    return "fail", None


def main():
    today = date.today().isoformat()
    with sqlite3.connect(DB) as con:
        con.execute("""create table if not exists flows (
            ticker text primary key, flow_foreign_amt real, flow_inst_amt real, flow_net_amt real,
            foreign_hold_ratio real, flow_asof text, flow_days integer, fetched_on text)""")
        kr = pd.read_sql("select ticker, stock_code from kr_fundamentals where ticker is not null", con)
        done = set(pd.read_sql("select ticker from flows where fetched_on = ?", con, params=(today,)).ticker)
    todo = kr[~kr.ticker.isin(done)]
    print(f"한국 {len(kr):,}종목 · 오늘 받은 것 {len(done):,} · 받을 것 {len(todo):,}")

    buf, ok, nodata, failed, streak = [], 0, 0, 0, 0
    started = time.time()

    def flush():
        if buf:
            with sqlite3.connect(DB) as con:
                con.executemany("insert or replace into flows values (?,?,?,?,?,?,?,?)", buf)
            buf.clear()

    for i, (ticker, code) in enumerate(zip(todo.ticker, todo.stock_code), 1):
        status, rec = fetch(code)
        if status == "ok":
            ok, streak = ok + 1, 0
            buf.append((ticker, rec["flow_foreign_amt"], rec["flow_inst_amt"], rec["flow_net_amt"],
                        rec["foreign_hold_ratio"], rec["flow_asof"], rec["flow_days"], today))
        elif status == "nodata":
            nodata, streak = nodata + 1, 0
        else:
            failed, streak = failed + 1, streak + 1
            if streak >= MAX_CONSECUTIVE_FAIL:
                flush()
                print(f"\n연속 {streak}번 실패 - 차단된 것으로 보고 멈춥니다. 잠시 뒤 다시 실행하면 이어서 받습니다.")
                break
        if i % SAVE_EVERY == 0:
            flush()
            rate = i / (time.time() - started)
            print(f"  {i:>5,}/{len(todo):,}  저장 {ok:,} · 데이터없음 {nodata:,} · 실패 {failed:,}  "
                  f"{rate:.1f}건/s  남은 {(len(todo) - i) / rate / 60:.0f}분")
    flush()
    print(f"\n{DB} · flows · 이번 저장 {ok:,}종목 (데이터없음 {nodata:,}, 실패 {failed:,})")
    if failed:
        print("실패분은 다시 실행하면 이어서 받습니다.")


if __name__ == "__main__":
    main()
