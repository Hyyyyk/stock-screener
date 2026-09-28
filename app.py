"""저평가 우량주 스크리너.  실행: streamlit run app.py"""
import altair as alt
import pandas as pd
import streamlit as st

import os

import data

st.set_page_config(page_title="저평가주 스크리너", layout="wide")

# 클라우드에선 DART 키가 Secrets 로 온다. 한국 상세 탭이 collect_kr.key() 로 읽을 수 있게 환경변수로 옮긴다.
# 로컬엔 secrets 파일이 없어 st.secrets 접근만으로도 예외가 나므로 통째로 감싼다(.env 를 쓴다).
try:
    if not os.environ.get("DART_API_KEY") and "DART_API_KEY" in st.secrets:
        os.environ["DART_API_KEY"] = st.secrets["DART_API_KEY"]
except Exception:
    pass

# 프리셋별 5축 가중치 (합이 1일 필요는 없음, 상대비율만 의미 있음)
PRESETS = {
    "균형":       {"pbr": 1.0, "roe": 1.0, "op_growth": 1.0, "debt_ratio": 0.7, "flow_net": 0.7},
    "저평가 중시": {"pbr": 2.0, "roe": 1.0, "op_growth": 0.5, "debt_ratio": 1.0, "flow_net": 0.5},
    "성장 중시":   {"pbr": 0.7, "roe": 1.2, "op_growth": 2.0, "debt_ratio": 0.5, "flow_net": 1.0},
}

CAP_STEPS = {"제한 없음": 0, "$50M": 5e7, "$100M": 1e8, "$300M": 3e8,
             "$1B": 1e9, "$5B": 5e9, "$50B": 5e10}

# 업종마다 정상 범위가 달라(은행 부채비율 중앙값 760%, 화학 40%) 절대값 하나로는
# 업종이 통째로 걸러진다. 그래서 기본은 "비교 그룹 안에서 상위 몇 %" 로 거른다.
# (단계명, 컬럼, 방향, 절대값 슬라이더(라벨,최소,최대,기본,간격), 그룹내 상위 % 기본값)
FILTERS = [
    ("① 싼가",       "pbr",        "max", ("PBR 상한 (배)",           0.2,  12.0,   1.5,  0.1), 30),
    ("② 잘 버는가",   "roe",        "min", ("ROE 하한 (%)",          -30.0,  60.0,   8.0,  0.5), 50),
    ("③ 크고 있는가", "op_growth",  "min", ("영업이익 증가율 하한 (%)", -100.0, 300.0,   0.0,  5.0), 50),
    ("④ 안전한가",   "debt_ratio", "max", ("부채비율 상한 (%)",        10.0, 500.0, 150.0, 10.0), 50),
    ("⑤ 남들도 사는가", "flow_net",  "min", ("수급 하한 (시총 대비 %)",   -5.0,   5.0,   0.0,  0.1), 50),
]


df = data.load_stocks()
CORE = data.available(df, data.CORE)              # 값이 없는 축은 통째로 뺀다
CORE_COLS = [c for _, c, *_ in CORE]
missing = [m for m in data.CORE if m not in CORE]

if missing:
    st.info("아직 붙지 않은 축: " + " · ".join(
        f"**{label}** — {data.PENDING.get(col, '데이터 없음')}" for label, col, *_ in missing))

# ---------------- 사이드바: 좁혀나가는 조건 ----------------
with st.sidebar:
    _px, _fl = data.data_asof()                  # 데이터 기준일을 맨 위에 표시
    if _px or _fl:
        parts = []
        if _px:
            parts.append(f"시세 {str(_px)[:10]}")
        if _fl and len(str(_fl)) == 8:
            parts.append(f"수급 {str(_fl)[:4]}-{str(_fl)[4:6]}-{str(_fl)[6:8]}")
        st.caption("📅 " + " · ".join(parts))

    st.header("어떻게 좁힐까")
    preset = st.radio("무엇을 더 볼까요", list(PRESETS))
    st.caption({"균형": "다섯 축을 고르게 봅니다",
                "저평가 중시": "싼 것을 우선합니다",
                "성장 중시": "이익이 크는 쪽을 우선합니다"}[preset])

    st.divider()
    countries = st.multiselect("시장 국가", ["한국", "미국"], default=["한국", "미국"])
    df = df[df.country.isin([{"한국": "KR", "미국": "US"}[c] for c in countries])] if countries else df
    exchanges = sorted(df.market.unique())
    default = [e for e in exchanges if e in ("Nasdaq", "NYSE", "KOSPI", "KOSDAQ")] or exchanges
    markets = st.multiselect("거래소", exchanges, default=default,
                             help="OTC는 장외라 유동성이 낮습니다. 기본은 제외합니다.")
    cap_label = st.select_slider("최소 시가총액", list(CAP_STEPS), value="$100M",
                                 help="너무 작으면 거래량이 없어 실제로 사고팔기 어렵습니다. "
                                      "한국 종목은 원/달러 환율로 환산해 비교합니다.")
    drop_funds = st.checkbox("ETF·펀드 제외", value=True,
                             help="주식이 아닌 상품이 SEC에 재무를 제출해 섞여 들어옵니다.")
    sectors = st.multiselect("업종", sorted(df.sector.unique()), default=[],
                             placeholder="전체 업종")
    by_sector = st.checkbox("업종·규모 안에서 비교", value=True,
                            help="켜면 같은 나라·업종·시총규모끼리만 겨룹니다. "
                                 "끄면 시장 전체에 같은 절대값 기준을 적용합니다 — "
                                 "이때 은행처럼 부채비율이 원래 높은 업종은 통째로 빠지고, "
                                 "소형주가 '싼가'를 독식합니다.")

    st.divider()
    st.caption("이런 종목만 보기")
    only_up = st.checkbox("매출 3년 연속 증가", value=False,
                          help="최근 3년(2023<2024<2025) 매출이 매년 늘어난 종목만.")
    only_turn = st.checkbox("흑자전환 (작년 적자→올해 흑자)", value=False,
                            help="직전 연도는 순손실, 최근 연도는 순이익인 종목만.")

    st.divider()
    if by_sector:
        st.caption("각 조건은 **같은 나라·업종·규모 안에서의 등수**로 거릅니다. "
                   "종목이 적은 그룹은 같은 나라·규모 전체 등수와 섞어 튀지 않게 합니다.")
    cuts, roe_floor = {}, None
    for stage, col, direction, (label, lo, hi, dflt, step), pct_dflt in FILTERS:
        if col not in CORE_COLS:
            continue
        st.subheader(stage)
        cuts[col] = (st.slider(f"{label.split(' ')[0]} 그룹 내 상위 %", 5, 100, pct_dflt, 5,
                               key=f"{col}_pct")
                     if by_sector else st.slider(label, lo, hi, dflt, step, key=col))
        if col == "roe" and by_sector:
            roe_floor = st.slider("ROE 최소 (%)", -10.0, 30.0, 5.0, 0.5, key="roe_floor",
                                  help="등수와 별개로 적용합니다. ROE 가 전반적으로 낮은 그룹에서는 "
                                       "예금금리 수준만 벌어도 '상위 50%' 에 들기 때문입니다.")
        if col == "flow_net":
            st.caption("한국만 적용합니다. 미국은 일별 수급 데이터가 없어 이 단계를 건너뜁니다. "
                       "출처: 네이버 증권(비공식)")

# ---------------- 모집단과 비교 그룹 ----------------
universe = df[df.market.isin(markets)]
if drop_funds:
    universe = universe[universe.kind.fillna("EQUITY") == "EQUITY"]
if CAP_STEPS[cap_label]:
    universe = universe[universe.market_cap_usd >= CAP_STEPS[cap_label]]   # 원화는 환율로 달러 환산해 비교
if only_up:
    universe = universe[universe.rev_up_3y]
if only_turn:
    universe = universe[universe.turnaround]
universe = universe.assign(size_bucket=universe.groupby("country").market_cap.transform(data.size_bucket))

# 등수는 업종 필터를 걸기 전(universe) 기준으로 한 번만 매긴다.
# 단계마다 다시 매기거나 업종으로 좁힌 뒤 매기면 "상위 30%" 의 모집단이 바뀌어 뜻이 달라진다.
pct_all = pd.DataFrame({col: data.peer_pct(universe, col, big, by_sector) for _, col, _, big, _ in CORE})
# 축 데이터가 나라 전체에 아예 없으면(수급 → 미국) 그 단계에서 걸러내지 않는다
has_axis = {col: universe.groupby("country")[col].transform("count") > 0 for col in CORE_COLS}

# ---------------- 깔때기: 단계별로 몇 개가 걸러지는가 ----------------
base = universe[universe.sector.isin(sectors)] if sectors else universe
steps, cur = [("전체", base)], base
for stage, col, direction, *_ in FILTERS:
    if col not in cuts:
        continue
    v = cuts[col]
    if by_sector:
        keep = pct_all[col].loc[cur.index] >= 100 - v
        if col == "roe" and roe_floor is not None:
            keep &= cur.roe >= roe_floor
    else:
        keep = cur[col] <= v if direction == "max" else cur[col] >= v
    # 값이 없는 종목은 판단 불가라 제외하되, 그 나라에 이 축 데이터가 아예 없으면 통과시킨다
    cur = cur[keep.fillna(False) | ~has_axis[col].loc[cur.index]]
    steps.append((stage, cur))

f = steps[-1][1]
if f.empty:
    st.error("조건에 맞는 종목이 없습니다. 사이드바에서 조건을 풀어보세요.")
    st.stop()

sc_all = data.weighted_score(pct_all, PRESETS[preset])      # 값이 없는 축(미국 수급)은 분모에서 뺀다
pct, f = pct_all.loc[f.index], f.assign(score=sc_all.loc[f.index])

st.subheader(f"🏆 후보 {len(f):,}종목")
st.caption(f"**{preset}** 기준 · {len(CORE)}개 축을 **시장 전체 {len(universe):,}개 종목 기준** "
           "백분위로 환산해 가중평균한 점수입니다. 100에 가까울수록 조건에 잘 맞습니다."
           if not by_sector else
           f"**{preset}** 기준 · **같은 나라·업종·규모 안에서** 백분위를 매겼습니다. "
           "한국 소형 반도체는 한국 소형 반도체끼리 겨루고, 그런 종목이 적으면 한국 소형주 전체와 섞습니다.")
view = f.sort_values("score", ascending=False).head(100)
show = pd.DataFrame({
    "순위": range(1, len(view) + 1),
    "티커": view.ticker.values,
    "종목": view["name"].values,
    "거래소": view.market.values,
    "국가": view.country.map({"US": "🇺🇸", "KR": "🇰🇷"}).values,
    "업종": view.sector.values,
    "규모": view.size_bucket.values,
    "점수": view.score.values,
    **{label: view[col].values for label, col, _, _, _ in CORE},
})
st.caption("행을 **클릭**하면 바로 아래에 그 종목 상세가 펼쳐집니다.")
event = st.dataframe(
    show, use_container_width=True, hide_index=True, height=520,
    on_select="rerun", selection_mode="single-row", key="rank_sel",
    column_config={
        "점수": st.column_config.ProgressColumn(format="%.0f", min_value=0, max_value=100),
        "PBR": st.column_config.NumberColumn(format="%.2f배"),
        "ROE": st.column_config.NumberColumn(format="%.1f%%"),
        "영업익증가율": st.column_config.NumberColumn(format="%.1f%%"),
        "부채비율": st.column_config.NumberColumn(format="%.0f%%"),
        "수급": st.column_config.NumberColumn(format="%+.2f%%"),
    },
)
st.download_button("CSV 내려받기", show.to_csv(index=False).encode("utf-8-sig"),
                   "screener.csv", "text/csv")

# ---------------- 클릭한 종목 상세 (표 바로 아래에 펼침) ----------------
if not event.selection.rows:
    st.info("👆 위 표에서 종목을 클릭하면 여기에 상세가 펼쳐집니다.")
else:
    idx = view.index[event.selection.rows[0]]      # 클릭한 행의 원본 인덱스
    row = f.loc[idx]
    st.divider()
    st.subheader(f"{row['name']}  ·  {row.ticker}  ·  {row.market}")
    st.caption(" · ".join(str(x) for x in [row.sector, row.size_bucket] if pd.notna(x)))
    summary = data.load_business(row.ticker)     # Yahoo 회사 소개(영어). 열 때만 실시간 조회
    if summary:
        st.markdown(f"🏢 {summary}")
    else:                                        # 실패 시 KRX 주요제품 / SEC 업종 한 줄로 폴백
        biz = row.get("business")
        if pd.notna(biz) and str(biz).strip() not in ("", "-"):
            st.markdown(f"🏢 **{biz}**")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**각 축이 어디에 서 있나** — "
                    + ("같은 나라·업종·규모 안에서의 백분위" if by_sector else "시장 전체에서의 백분위")
                    + " (100 = 최상위)")
        st.bar_chart(pd.DataFrame({"백분위": [pct.at[idx, col] for _, col, _, _, _ in CORE]},
                                  index=[l for l, _, _, _, _ in CORE]),
                     horizontal=True, height=240)
    with c2:
        st.markdown("**실제 값**")
        st.dataframe(pd.DataFrame(
            [{"지표": l, "값": "–" if pd.isna(row[col]) else f"{row[col]:,.1f}{u}", "의미": desc}
             for l, col, u, _, desc in CORE]), hide_index=True, use_container_width=True)

    st.subheader("실적이 어떻게 흘러왔나")
    kr = row.country == "KR"
    source, unit = ("DART", "억 원") if kr else ("SEC", "백만 달러")
    period = st.radio("기간", ["연간", "분기"], horizontal=True, key="hist_period",
                      label_visibility="collapsed")
    try:
        if period == "분기":
            h = (data.load_history_kr_quarter(row.corp_code) if kr
                 else pd.DataFrame() if pd.isna(row.get("cik")) else data.load_history_us_quarter(row.cik))
        else:
            h = (data.load_history_kr(row.corp_code) if kr
                 else pd.DataFrame() if pd.isna(row.get("cik")) else data.load_history(row.cik))
    except Exception:                              # 네트워크 오류·차단. 캐시되지 않아 다시 열면 재시도한다
        h = None
        st.warning(f"{source} 응답을 받지 못했습니다. 잠시 뒤 다시 열어보세요.")
    if h is None:
        pass
    elif h.empty:
        st.warning(f"이 회사는 {source}에 표준 계정이 없어 추이를 만들 수 없습니다.")
    else:
        note = " · 분기는 당분기(3개월)" if period == "분기" else ""
        if period == "분기" and not kr:
            note += " · 미국은 분기 현금흐름 미제공(손익만)"
        st.caption(f"단위: {unit}{note}")
        # 분기 라벨("25 2Q")은 그대로, 연간은 "23년"으로 → 축이 숫자·세로가 아니라 카테고리로 깔끔
        hy = (h.set_index("연도") if period == "분기"
              else h.assign(연도=h["연도"].astype(str).str[2:] + "년").set_index("연도"))
        cc1, cc2 = st.columns(2)
        pnl = [c for c in ["매출액", "영업이익", "순이익"] if c in hy]
        cfl = [c for c in ["영업CF", "투자CF", "재무CF"] if c in hy]
        if pnl:
            long = hy[pnl].reset_index().melt("연도", var_name="항목", value_name="값")
            ymax, ymin = long["값"].max(), long["값"].min()
            # 0선 위(양수)는 옅은 파랑, 아래(음수)는 옅은 빨강 배경으로 흑자·적자를 한눈에
            pos = alt.Chart(pd.DataFrame({"y": [0], "y2": [max(ymax, 0)]})).mark_rect(
                color="#3b82f6", opacity=0.06).encode(y="y:Q", y2="y2:Q")
            neg = alt.Chart(pd.DataFrame({"y": [min(ymin, 0)], "y2": [0]})).mark_rect(
                color="#e5484d", opacity=0.06).encode(y="y:Q", y2="y2:Q")
            line = alt.Chart(long).mark_line(point=True).encode(
                x=alt.X("연도:N", title=None, sort=list(hy.index)),
                y=alt.Y("값:Q", title=None),
                color=alt.Color("항목:N", title=None,
                                scale=alt.Scale(domain=pnl,
                                                range=["#1f4e9e", "#e5484d", "#5b8def"][:len(pnl)])),
                tooltip=["연도", "항목", alt.Tooltip("값:Q", format=",.0f")])
            cc1.altair_chart(pos + neg + line, use_container_width=True)
        if cfl:
            cc2.bar_chart(hy[cfl])
            cc2.caption("영업에서 벌어(+) · 투자에 쓰고(−) · 재무로 조달·상환(−)한 실제 현금")
        st.dataframe(hy.T.round(0), use_container_width=True)

    with st.expander("보조 지표"):
        st.dataframe(pd.DataFrame(
            [{"지표": l, "값": "–" if pd.isna(row[col]) else f"{row[col]:,.1f}{u}", "의미": desc}
             for l, col, u, desc in data.EXTRA]), hide_index=True, use_container_width=True)

st.caption("SEC EDGAR·DART 공시 재무, Yahoo 시세, 네이버 증권 수급(한국)을 정해진 규칙으로 정렬해 보여주는 도구입니다. "
           "투자 자문이 아니며, 투자 판단과 그 결과의 책임은 본인에게 있습니다.")
