"""저평가 우량주 스크리너.  실행: streamlit run app.py"""
import pandas as pd
import streamlit as st

import os

import data
import detail_view
import screener
import watchlist
from settings import CAP_STEPS, FILTERS, PRESETS

st.set_page_config(page_title="저평가주 스크리너", layout="wide")

# 클라우드에선 DART 키가 Secrets 로 온다. 한국 상세 탭이 collect_kr.key() 로 읽을 수 있게 환경변수로 옮긴다.
# 로컬엔 secrets 파일이 없어 st.secrets 접근만으로도 예외가 나므로 통째로 감싼다(.env 를 쓴다).
try:
    if not os.environ.get("DART_API_KEY") and "DART_API_KEY" in st.secrets:
        os.environ["DART_API_KEY"] = st.secrets["DART_API_KEY"]
except Exception:
    pass

df = data.load_stocks()
CORE = data.available(df, data.CORE)              # 값이 없는 축은 통째로 뺀다
CORE_COLS = [c for _, c, *_ in CORE]
missing = [m for m in data.CORE if m not in CORE]

if missing:
    st.info("아직 붙지 않은 축: " + " · ".join(
        f"**{label}** — {data.PENDING.get(col, '데이터 없음')}" for label, col, *_ in missing))

# ---------------- 사이드바: 좁혀나가는 조건 ----------------
with st.sidebar:
    fresh = data.data_freshness()                 # 소스별 기준일을 맨 위에 표시
    _px, _fl, _fy = fresh["price"], fresh["flow"], fresh["fiscal_year"]
    if _px or _fl or _fy:
        parts = []
        if _fy:
            parts.append(f"재무 {_fy}년")
        if _px:
            parts.append(f"시세 {str(_px)[:10]}")
        if _fl and len(str(_fl)) == 8:
            parts.append(f"수급 {str(_fl)[:4]}-{str(_fl)[4:6]}-{str(_fl)[6:8]}")
        st.caption("📅 " + " · ".join(parts))
    if _fy and _fy < data.expected_annual_year():
        st.warning(f"재무가 {_fy}년 기준으로 오래됐습니다. 재무 수집기를 다시 실행해 주세요.")

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
                          help="DB에 저장된 최근 3개 연도의 매출이 매년 늘어난 종목만.")
    only_turn = st.checkbox("흑자전환 (작년 적자→올해 흑자)", value=False,
                            help="직전 연도는 순손실, 최근 연도는 순이익인 종목만.")
    only_trend = st.checkbox("📈 추세 양호만 (상승 추세 구간)", value=False,
                             help="52주 고점 대비 -25% 이내 그리고 저점 대비 +30% 이상인 종목만. "
                                  "점수(가치·성장)는 그대로 두고 '시점'만 덧씌우는 필터입니다. "
                                  "미너비니 추세 템플릿의 가격 위치 조건 일부 — 제 제안 기준이라 백테스트 미검증.")
    only_rs = st.checkbox("📊 RS(상대강도) 상위 30%만", value=False,
                          help="같은 나라 종목 중 최근 3·6개월 수익률 순위 상위 30%만. "
                               "오닐·미너비니의 상대강도 개념 — 점수는 그대로 두는 '시점' 오버레이. "
                               "제 제안 기준(최근 3개월 2배 가중)이라 백테스트 미검증.")
    _wl = watchlist.load()
    only_watch = st.checkbox(f"⭐ 관심종목만 보기 ({len(_wl)})", value=False,
                             help="종목 상세의 ⭐ 버튼으로 담은 종목만. 등수 조건은 건너뛰고 "
                                  "거래소·시총 필터만 적용합니다.")

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
        if col == "debt_ratio":
            st.caption("은행·보험은 부채 구조가 일반 기업과 달라 이 축을 점수와 필터에서 제외합니다.")

# ---------------- 모집단과 비교 그룹 ----------------
universe = screener.prepare_universe(df, markets, CAP_STEPS[cap_label], drop_funds, only_up, only_turn)

# 등수는 업종 필터를 걸기 전(universe) 기준으로 한 번만 매긴다.
# 단계마다 다시 매기거나 업종으로 좁힌 뒤 매기면 "상위 30%" 의 모집단이 바뀌어 뜻이 달라진다.
pct_all, applicable = screener.percentiles(universe, CORE, by_sector)

# ---------------- 깔때기: 단계별로 몇 개가 걸러지는가 ----------------
base = universe[universe.sector.isin(sectors)] if sectors else universe
if only_watch:                                    # 관심종목은 등수 조건 없이 전부 보여준다
    f = base[base.ticker.isin(_wl)]
    if f.empty:
        st.info("관심종목이 없습니다 (또는 현재 거래소·시총 필터 밖입니다). "
                "'⭐ 관심종목만 보기'를 끄고, 종목을 클릭·검색해 상세에서 ⭐ 버튼으로 담으세요.")
        st.stop()
else:
    f = screener.apply_filters(base, FILTERS, cuts, pct_all, applicable, by_sector, roe_floor)[-1][1]
    if f.empty:
        st.error("조건에 맞는 종목이 없습니다. 사이드바에서 조건을 풀어보세요.")
        st.stop()

rs_all = data.relative_strength(universe)          # 같은 나라 안 수익률 순위(0~100), 점수와 별개
if only_trend and not only_watch:                 # 시점 오버레이: 점수·순위는 그대로, 상승 추세만 남긴다
    f = f[data.trend_label(f) == "상승 추세"]
    if f.empty:
        st.warning("가치·성장 조건은 통과했지만 '상승 추세 구간'에 든 종목이 없습니다. "
                   "추세 양호 필터를 끄거나 종목 조건을 풀어보세요.")
        st.stop()
if only_rs and not only_watch:                    # RS 상위 30%(백분위 70↑)만
    f = f[rs_all.reindex(f.index) >= 70]
    if f.empty:
        st.warning("가치·성장 조건은 통과했지만 RS(상대강도) 상위 30%에 든 종목이 없습니다. "
                   "RS 필터를 끄거나 종목 조건을 풀어보세요.")
        st.stop()

sc_all = data.weighted_score(pct_all, PRESETS[preset], min_axes=2)  # 한 축만으로 높은 종합점수가 되지 않게 한다
pct, f = pct_all.loc[f.index], f.assign(score=sc_all.loc[f.index])

st.subheader(f"⭐ 관심종목 {len(f):,}개" if only_watch else f"🏆 후보 {len(f):,}종목")
st.caption(f"**{preset}** 기준 · {len(CORE)}개 축을 **시장 전체 {len(universe):,}개 종목 기준** "
           "백분위로 환산해 가중평균한 점수입니다. 100에 가까울수록 조건에 잘 맞습니다."
           if not by_sector else
           f"**{preset}** 기준 · **같은 나라·업종·규모 안에서** 백분위를 매겼습니다. "
           "한국 소형 반도체는 한국 소형 반도체끼리 겨루고, 그런 종목이 적으면 한국 소형주 전체와 섞습니다. "
           "종합점수는 계산 가능한 축이 2개 이상일 때만 표시합니다.")

if not only_watch:                                  # 숲 보기: 지금 어느 업종이 전반적으로 싼가·좋은가
    with st.expander("🗺 지금 시장 어디가 싼가 — 업종별 요약", expanded=False):
        grp = universe.assign(score=sc_all).dropna(subset=["score"])
        summary = (grp.groupby(["country", "sector"])
                   .agg(종목수=("ticker", "size"), 평균점수=("score", "mean"),
                        PBR중앙=("pbr", "median"), ROE중앙=("roe", "median"),
                        수급중앙=("flow_net", "median"))
                   .reset_index())
        summary = summary[summary.종목수 >= 3]       # 표본 3개 미만 그룹은 노이즈라 뺀다
        if summary.empty:
            st.caption("요약할 만큼 종목이 모이는 업종이 없습니다. 거래소·시총 조건을 넓혀보세요.")
        else:
            summary["국가"] = summary.country.map({"US": "🇺🇸", "KR": "🇰🇷"})
            summary = summary.sort_values("평균점수", ascending=False)
            st.caption("거래소·시총 필터 안에서 **종목 3개 이상인 업종만**, 평균점수 높은 순. "
                       "= 지금 조건에 전반적으로 잘 맞는 업종. (업종 안 개별 종목은 아래 표에서)")
            st.dataframe(
                summary[["국가", "sector", "종목수", "평균점수", "PBR중앙", "ROE중앙", "수급중앙"]]
                .rename(columns={"sector": "업종"}),
                hide_index=True, width="stretch", column_config={
                    "평균점수": st.column_config.ProgressColumn(format="%.0f", min_value=0, max_value=100),
                    "PBR중앙": st.column_config.NumberColumn(format="%.2f배"),
                    "ROE중앙": st.column_config.NumberColumn(format="%.1f%%"),
                    "수급중앙": st.column_config.NumberColumn(format="%+.2f%%"),
                })

view = f.sort_values("score", ascending=False).head(100)
metric_cfg = {                                      # 두 표(랭킹·대시보드)가 함께 쓰는 지표 서식
    "PBR": st.column_config.NumberColumn(format="%.2f배"),
    "ROE": st.column_config.NumberColumn(format="%.1f%%"),
    "영업익증가율": st.column_config.NumberColumn(format="%.1f%%"),
    "부채비율": st.column_config.NumberColumn(format="%.0f%%"),
    "수급": st.column_config.NumberColumn(format="%+.2f%%"),
}
if only_watch:                                      # 관심종목은 주가 중심 대시보드로 본다
    drawdown = (view.price / view.high52 - 1) * 100  # 52주 고점에서 얼마나 내려와 있나(음수)
    show = pd.DataFrame({
        "티커": view.ticker.values,
        "종목": view["name"].values,
        "국가": view.country.map({"US": "🇺🇸", "KR": "🇰🇷"}).values,
        "현재가": view.price.values,
        "당일%": view.change_pct.values,
        "52주高대비": drawdown.values,
        "점수": view.score.values,
        **{label: view[col].values for label, col, _, _, _ in CORE},
    })
    col_cfg = {
        "점수": st.column_config.ProgressColumn(format="%.0f", min_value=0, max_value=100),
        "현재가": st.column_config.NumberColumn(format="%.2f", help="통화는 국가 기준(🇰🇷 원 · 🇺🇸 달러)"),
        "당일%": st.column_config.NumberColumn(format="%+.2f%%"),
        "52주高대비": st.column_config.NumberColumn(format="%+.1f%%",
                                                    help="52주 최고가 대비 현재가 위치 · 0에 가까울수록 고점 부근, 음수가 클수록 많이 내려옴"),
        **metric_cfg,
    }
    st.caption("담아둔 종목의 **주가·점수·지표**를 한눈에. 행을 **클릭**하면 아래에 상세가 펼쳐집니다.")
else:
    show = pd.DataFrame({
        "순위": range(1, len(view) + 1),
        "티커": view.ticker.values,
        "종목": view["name"].values,
        "거래소": view.market.values,
        "국가": view.country.map({"US": "🇺🇸", "KR": "🇰🇷"}).values,
        "업종": view.sector.values,
        "규모": view.size_bucket.values,
        "점수": view.score.values,
        "추세": data.trend_label(view).values,
        "RS": rs_all.reindex(view.index).values,
        "데이터": view.data_completeness.values,
        **{label: view[col].values for label, col, _, _, _ in CORE},
    })
    col_cfg = {
        "점수": st.column_config.ProgressColumn(format="%.0f", min_value=0, max_value=100),
        "추세": st.column_config.TextColumn(help="52주 고·저 대비 위치 · 상승 추세/조정 중/약세 "
                                                 "(미너비니 가격조건 일부, 제 제안 기준)"),
        "RS": st.column_config.NumberColumn(format="%.0f", help="상대강도 — 같은 나라 안 최근 3·6개월 "
                                                               "수익률 순위(0~100, 높을수록 강함). 오닐·미너비니."),
        "데이터": st.column_config.ProgressColumn("데이터 완성도", format="%.0f%%", min_value=0, max_value=100,
                                                   help="해당 국가에서 제공되는 핵심 지표 중 값이 있는 비율"),
        **metric_cfg,
    }
    st.caption("행을 **클릭**하면 바로 아래에 그 종목 상세가 펼쳐집니다.")
event = st.dataframe(
    show, width="stretch", hide_index=True, height=520,
    on_select="rerun", selection_mode="single-row", key="rank_sel",
    column_config=col_cfg,
)
st.download_button("CSV 내려받기", show.to_csv(index=False).encode("utf-8-sig"),
                   "screener.csv", "text/csv")

detail_view.render(df, view, event, pct_all, by_sector, CORE)

st.caption("SEC EDGAR·DART 공시 재무, Yahoo 시세, 네이버 증권 수급(한국)을 정해진 규칙으로 정렬해 보여주는 도구입니다. "
           "투자 자문이 아니며, 투자 판단과 그 결과의 책임은 본인에게 있습니다.")
