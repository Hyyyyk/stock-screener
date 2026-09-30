"""상세 화면용 시세 API와 응답 파싱."""
import json
import urllib.parse
import urllib.request

import pandas as pd
import streamlit as st

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
PRICE_RANGES = {"6개월": "6mo", "1년": "1y", "3년": "3y"}


def parse_chart(payload):
    """Yahoo chart JSON을 날짜·종가·거래량 표로 변환한다."""
    result = payload.get("chart", {}).get("result") or []
    if not result:
        return pd.DataFrame(), None
    result = result[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes, volumes = quote.get("close") or [], quote.get("volume") or []
    size = min(len(timestamps), len(closes))
    frame = pd.DataFrame({
        "날짜": pd.to_datetime(timestamps[:size], unit="s", utc=True).tz_convert(None).normalize(),
        "종가": pd.to_numeric(closes[:size], errors="coerce"),
        "거래량": pd.to_numeric((volumes + [None] * size)[:size], errors="coerce"),
    }).dropna(subset=["종가"]).drop_duplicates("날짜").sort_values("날짜")
    return frame.reset_index(drop=True), (result.get("meta") or {}).get("currency")


@st.cache_data(ttl=1800, show_spinner="주가 이력을 받는 중…")
def load_price_history(ticker, range_code="1y"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(ticker)}?range={range_code}&interval=1d&events=div%2Csplits")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as response:
            return parse_chart(json.load(response))
    except Exception:
        return pd.DataFrame(), None
