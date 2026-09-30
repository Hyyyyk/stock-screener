"""종목 상세 Streamlit 화면."""
import altair as alt
import pandas as pd
import streamlit as st

import data
import market_data


def render(df, view, event, pct_all, by_sector, core):
    opts = sorted(df.ticker + "  " + df["name"])
    searched = st.selectbox("🔎 종목 직접 검색 — 순위·필터와 무관하게 아무 종목이나 (티커·종목명)",
                            [""] + opts, index=0, placeholder="예: 005930.KS, 삼성전자, AAPL")
    if searched:
        idx = df.index[df.ticker == searched.split("  ")[0]][0]
    elif event.selection.rows:
        idx = view.index[event.selection.rows[0]]
    else:
        idx = None

    if idx is None:
        st.info("👆 위 표에서 종목을 클릭하거나, 검색창에서 종목을 고르면 여기에 상세가 펼쳐집니다.")
        return

    row = df.loc[idx]
    st.divider()
    st.subheader(f"{row['name']}  ·  {row.ticker}  ·  {row.market}")
    meta = [row.get("sector"), row.get("size_bucket"),
            f"재무 {int(row.fiscal_year)}년" if pd.notna(row.get("fiscal_year")) else None,
            f"데이터 {int(row.data_axes)}/{int(row.data_expected)}축"]
    st.caption(" · ".join(str(x) for x in meta if pd.notna(x)))
    if row.get("financial_stale", False):
        st.warning("이 종목의 재무 데이터가 기대 기준연도보다 오래됐습니다. 점수를 참고용으로만 보세요.")
    if idx in pct_all.index:
        st.info("선정 이유: " + data.score_reason(pct_all.loc[idx]))
    summary = data.load_business(row.ticker)
    if summary:
        st.markdown(f"🏢 {summary}")
    else:
        biz = row.get("business")
        if pd.notna(biz) and str(biz).strip() not in ("", "-"):
            st.markdown(f"🏢 **{biz}**")

    _render_price(row)
    _render_metrics(row, idx, pct_all, by_sector, core)
    _render_history(row)
    if row.country == "KR":
        _render_flow(row)
    with st.expander("보조 지표"):
        st.dataframe(pd.DataFrame(
            [{"지표": label, "값": "–" if pd.isna(row[col]) else f"{row[col]:,.1f}{unit}", "의미": desc}
             for label, col, unit, desc in data.EXTRA]), hide_index=True, width="stretch")


def _render_price(row):
    st.subheader("주가 흐름")
    period = st.segmented_control("조회 기간", list(market_data.PRICE_RANGES), default="1년",
                                  key="price_period", label_visibility="collapsed") or "1년"
    history, currency = market_data.load_price_history(row.ticker, market_data.PRICE_RANGES[period])
    if history.empty:
        st.info("주가 이력을 받지 못했습니다. 잠시 뒤 다시 열어보세요.")
        return

    first, last = history.iloc[0].종가, history.iloc[-1].종가
    change = (last / first - 1) * 100 if first else None
    unit = "원" if (currency or row.get("currency")) == "KRW" else (currency or row.get("currency") or "")
    c1, c2, c3 = st.columns(3)
    c1.metric("최근 종가", f"{last:,.2f} {unit}".strip(),
              None if change is None else f"기간 {change:+.1f}%")
    c2.metric("기간 최고", f"{history.종가.max():,.2f} {unit}".strip())
    c3.metric("기간 최저", f"{history.종가.min():,.2f} {unit}".strip())

    base = alt.Chart(history).encode(x=alt.X("날짜:T", title=None))
    area = base.mark_area(line={"color": "#3b82f6"}, color="#3b82f6", opacity=0.12).encode(
        y=alt.Y("종가:Q", title=f"종가 ({unit})" if unit else "종가", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("날짜:T", format="%Y-%m-%d"), alt.Tooltip("종가:Q", format=",.2f")])
    st.altair_chart(area.properties(height=320), width="stretch")
    st.caption("일별 종가 기준 · 장중 고가·저가가 아닌 기간 내 종가 범위 · 출처: Yahoo Finance")


def _render_metrics(row, idx, pct_all, by_sector, core):
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**각 축이 어디에 서 있나** — "
                    + ("같은 나라·업종·규모 안에서의 백분위" if by_sector else "시장 전체에서의 백분위")
                    + " (100 = 최상위)")
        if idx in pct_all.index:
            st.bar_chart(pd.DataFrame({"백분위": [pct_all.at[idx, col] for _, col, _, _, _ in core]},
                                      index=[label for label, _, _, _, _ in core]),
                         horizontal=True, height=240)
        else:
            st.caption("검색으로 연 종목이라 현재 필터 모집단 밖입니다 — 업종 백분위는 생략하고 "
                       "실제 값·실적·수급만 보여줍니다.")
    with c2:
        st.markdown("**실제 값**")
        st.dataframe(pd.DataFrame(
            [{"지표": label, "값": "–" if pd.isna(row[col]) else f"{row[col]:,.1f}{unit}", "의미": desc}
             for label, col, unit, _, desc in core]), hide_index=True, width="stretch")


def _render_history(row):
    st.subheader("실적이 어떻게 흘러왔나")
    kr = row.country == "KR"
    source, unit = ("DART", "억 원") if kr else ("SEC", "백만 달러")
    period = st.radio("기간", ["연간", "분기"], horizontal=True, key="hist_period",
                      label_visibility="collapsed")
    try:
        if period == "분기":
            history = (data.load_history_kr_quarter(row.corp_code) if kr else
                       pd.DataFrame() if pd.isna(row.get("cik")) else data.load_history_us_quarter(row.cik))
        else:
            history = (data.load_history_kr(row.corp_code) if kr else
                       pd.DataFrame() if pd.isna(row.get("cik")) else data.load_history(row.cik))
    except Exception:
        st.warning(f"{source} 응답을 받지 못했습니다. 잠시 뒤 다시 열어보세요.")
        return
    if history.empty:
        st.warning(f"이 회사는 {source}에 표준 계정이 없어 추이를 만들 수 없습니다.")
        return

    note = " · 분기는 당분기(3개월)" if period == "분기" else ""
    if period == "분기" and not kr:
        note += " · 미국은 분기 현금흐름 미제공(손익만)"
    st.caption(f"단위: {unit}{note}")
    history = (history.set_index("연도") if period == "분기" else
               history.assign(연도=history["연도"].astype(str).str[2:] + "년").set_index("연도"))
    c1, c2 = st.columns(2)
    pnl = [c for c in ["매출액", "영업이익", "순이익"] if c in history]
    cashflow = [c for c in ["영업CF", "투자CF", "재무CF"] if c in history]
    if pnl:
        long = history[pnl].reset_index().melt("연도", var_name="항목", value_name="값")
        ymax, ymin = long["값"].max(), long["값"].min()
        positive = alt.Chart(pd.DataFrame({"y": [0], "y2": [max(ymax, 0)]})).mark_rect(
            color="#3b82f6", opacity=0.06).encode(y="y:Q", y2="y2:Q")
        negative = alt.Chart(pd.DataFrame({"y": [min(ymin, 0)], "y2": [0]})).mark_rect(
            color="#e5484d", opacity=0.06).encode(y="y:Q", y2="y2:Q")
        line = alt.Chart(long).mark_line(point=True).encode(
            x=alt.X("연도:N", title=None, sort=list(history.index)), y=alt.Y("값:Q", title=None),
            color=alt.Color("항목:N", title=None,
                            scale=alt.Scale(domain=pnl, range=["#1f4e9e", "#e5484d", "#5b8def"][:len(pnl)])),
            tooltip=["연도", "항목", alt.Tooltip("값:Q", format=",.0f")])
        c1.altair_chart(positive + negative + line, width="stretch")
    if cashflow:
        c2.bar_chart(history[cashflow])
        c2.caption("영업에서 벌어(+) · 투자에 쓰고(−) · 재무로 조달·상환(−)한 실제 현금")
    st.dataframe(history.T.round(0), width="stretch")


def _render_flow(row):
    st.subheader("수급 — 외국인·기관")
    flow = data.load_flow_daily(row.ticker.split(".")[0])
    if flow.empty:
        st.info("수급 데이터를 받지 못했습니다. 잠시 뒤 다시 열어보세요.")
        return
    cols = st.columns(2)
    for col, who, amount in zip(cols, ["외국인", "기관"], ["외인_억", "기관_억"]):
        sum3, sum7 = flow[amount].tail(3).sum(), flow[amount].tail(7).sum()
        streak = data.flow_streak(flow[amount])
        label = (f"{abs(streak)}일 연속 순매수" if streak > 0 else
                 f"{abs(streak)}일 연속 순매도" if streak < 0 else "연속 없음")
        col.metric(f"{who} · 3일 합", f"{sum3:+,.0f}억", label, delta_color="off")
        col.caption(f"7일 합 {sum7:+,.0f}억")
    table = pd.DataFrame({
        "날짜": flow["날짜"], "외인 순매수(주)": flow["외인_주"].map("{:+,.0f}".format),
        "외인 금액(억)": flow["외인_억"].map("{:+,.1f}".format),
        "기관 순매수(주)": flow["기관_주"].map("{:+,.0f}".format),
        "기관 금액(억)": flow["기관_억"].map("{:+,.1f}".format),
    })[::-1]
    st.dataframe(table, hide_index=True, width="stretch")
    st.caption("순매수(주) = 사들인 주식 수, 금액 = 그 금액(억) · 양수 순매수 / 음수 순매도")
