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


STAGE_MA = 150          # 30주 ≈ 150 거래일 (와인스타인 30주 이평)
SLOPE_LOOKBACK = 20     # 약 1개월 전 이평과 비교해 기울기를 본다


def moving_averages(history, windows=(50, STAGE_MA)):
    """종가 이동평균 열(예: '50일', '150일')을 붙여 돌려준다 — 차트 오버레이용."""
    out = history.copy()
    for w in windows:
        out[f"{w}일"] = out["종가"].rolling(w).mean()
    return out


def stage_analysis(history):
    """와인스타인 단계분석을 단순화한 휴리스틱(제 제안, 백테스트 미검증).

    30주(150일) 이평의 기울기(상승/평탄/하락)와 현재가 위치(이평 위/아래)로 1~4단계를 가른다.
    볼륨 확인·차트 패턴은 빼고 이평만 쓰므로 와인스타인 원법 그대로가 아니다.
    이평과 기울기를 만들 데이터가 모자라면 None(판단 유보).
    """
    close = history["종가"].reset_index(drop=True)
    if len(close) < STAGE_MA + SLOPE_LOOKBACK:
        return None
    ma = close.rolling(STAGE_MA).mean()
    now, prev, price = ma.iloc[-1], ma.iloc[-1 - SLOPE_LOOKBACK], close.iloc[-1]
    slope = (now / prev - 1) * 100 if prev else 0.0        # 최근 1개월 이평 변화율(%)
    above = price >= now
    if slope > 1.0:                                        # 이평 상승 (제 제안: 월 +1% 초과)
        label = "2단계 · 상승" if above else "전환 주의 · 상승 둔화"
    elif slope < -1.0:                                     # 이평 하락
        label = "4단계 · 하락" if not above else "전환 주의 · 바닥 시도"
    else:                                                  # 이평 평탄
        label = "3단계 · 천장/횡보 상단" if above else "1단계 · 바닥/횡보 하단"
    return label, slope


@st.cache_data(ttl=1800, show_spinner="주가 이력을 받는 중…")
def load_price_history(ticker, range_code="1y"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(ticker)}?range={range_code}&interval=1d&events=div%2Csplits")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as response:
            return parse_chart(json.load(response))
    except Exception:
        return pd.DataFrame(), None
