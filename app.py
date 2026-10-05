"""저평가 우량주 스크리너.  실행: streamlit run app.py"""
import pandas as pd
import streamlit as st

import os

import data
import detail_view
import market_data
import picks as picks_mod
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
df_full = df                                      # 전체 종목 탭용 (사이드바 국가 필터 전 전 종목)
price_now = dict(zip(df.ticker, df.price))        # 성과 추적용: 필터 전 전 종목 현재가


@st.cache_data(ttl=1800, show_spinner=False)      # 벤치마크 현재가 (네트워크 1회/30분)
def bench_now():
    return picks_mod.price_snapshot()


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
    sectors = st.multiselect("업종", sorted(df.sector.unique()), default=[],
                             placeholder="전체 업종")

    # 거의 안 바꾸는 값들은 고정한다(사이드바 정리). 바꾸려면 여기 숫자를 고치면 된다.
    exchanges = sorted(df.market.unique())
    markets = [e for e in exchanges if e in ("Nasdaq", "NYSE", "KOSPI", "KOSDAQ")] or exchanges
    drop_funds = True                                 # ETF·펀드는 항상 제외(주식만)
    by_sector = True                                  # 항상 같은 나라·업종·규모 안에서 비교(추천 방식)

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
    only_graham = st.checkbox("🛡 그레이엄 적정가 아래만 (안전마진)", value=False,
                              help="그레이엄 수 √(22.5·EPS·BPS)보다 현재가가 싼 종목만. "
                                   "흑자·자본 양(+) 기업에만 적용, 금융업·적자는 제외됩니다. "
                                   "그레이엄의 방어적 투자자 어림값 — 성장주엔 지나치게 보수적일 수 있습니다.")
    _wl = watchlist.load()
    only_watch = st.checkbox(f"⭐ 관심종목만 보기 ({len(_wl)})", value=False,
                             help="종목 상세의 ⭐ 버튼으로 담은 종목만. 등수 조건은 건너뛰고 "
                                  "거래소·시총 필터만 적용합니다.")

    st.divider()
    cuts, roe_floor = {}, None
    with st.expander("⚙ 고급 설정 — 시총·조건 세부 조정", expanded=False):
        cap_label = st.select_slider("최소 시가총액", list(CAP_STEPS), value="$100M",
                                     help="너무 작으면 거래량이 없어 실제로 사고팔기 어렵습니다. "
                                          "한국 종목은 원/달러 환율로 환산해 비교합니다.")
        st.caption("각 조건은 **같은 나라·업종·규모 안에서의 등수**로 거릅니다. "
                   "종목이 적은 그룹은 같은 나라·규모 전체 등수와 섞어 튀지 않게 합니다.")
        for stage, col, direction, (label, lo, hi, dflt, step), pct_dflt in FILTERS:
            if col not in CORE_COLS:
                continue
            st.subheader(stage)
            cuts[col] = st.slider(f"{label.split(' ')[0]} 그룹 내 상위 %", 5, 100, pct_dflt, 5,
                                  key=f"{col}_pct")
            if col == "roe":
                roe_floor = st.slider("ROE 최소 (%)", -10.0, 30.0, 5.0, 0.5, key="roe_floor",
                                      help="등수와 별개로 적용합니다. ROE 가 전반적으로 낮은 그룹에서는 "
                                           "예금금리 수준만 벌어도 '상위 50%' 에 들기 때문입니다.")
            if col == "flow_net":
                st.caption("한국만 적용합니다. 미국은 일별 수급 데이터가 없어 이 단계를 건너뜁니다. "
                           "출처: 네이버 증권(비공식)")
            if col == "debt_ratio":
                st.caption("은행·보험은 부채 구조가 일반 기업과 달라 이 축을 점수와 필터에서 제외합니다.")

tab_screener, tab_all = st.tabs(["🏆 스크리너", "📋 전체 종목"])

# ---------------- 📋 전체 종목: 사이드바·등수와 무관하게 전 종목을 정렬·검색 ----------------
# 스크리너 탭보다 먼저 그린다 — 스크리너가 빈 결과로 st.stop 해도 이 탭은 이미 그려져 있도록.
with tab_all:
    st.caption("사이드바 필터·등수와 무관하게 **전 종목**을 봅니다. 열 머리글을 눌러 정렬하세요. "
               "종합점수는 비교그룹이 있어야 뜻이 있어 여기선 생략하고 원시 지표만 보여줍니다. "
               "상세는 스크리너 탭의 '종목 직접 검색'에서 엽니다.")
    cn, cq = st.columns([1, 2])
    nat = cn.segmented_control("국가", ["전체", "🇰🇷 한국", "🇺🇸 미국"], default="전체",
                               key="all_nat", label_visibility="collapsed") or "전체"
    q = cq.text_input("검색", key="all_q", placeholder="검색 — 티커·종목명 (예: AAPL, 삼성, 반도체)",
                      label_visibility="collapsed")
    allv = df_full
    if nat != "전체":
        allv = allv[allv.country == {"🇰🇷 한국": "KR", "🇺🇸 미국": "US"}[nat]]
    if q:
        ql = q.strip().lower()
        allv = allv[allv.ticker.str.lower().str.contains(ql, na=False)
                    | allv["name"].str.lower().str.contains(ql, na=False)]
    allv = allv.assign(size_bucket=allv.groupby("country").market_cap.transform(data.size_bucket))
    show_all = pd.DataFrame({
        "티커": allv.ticker.values, "종목": allv["name"].values,
        "국가": allv.country.map({"US": "🇺🇸", "KR": "🇰🇷"}).values,
        "거래소": allv.market.values, "업종": allv.sector.values, "규모": allv.size_bucket.values,
        "현재가": allv.price.values, "시총($M)": (allv.market_cap_usd / 1e6).values,
        "PBR": allv.pbr.values, "ROE": allv.roe.values, "영업익증가율": allv.op_growth.values,
        "부채비율": allv.debt_ratio.values, "수급": allv.flow_net.values,
        "3개월%": allv.ret_3m.values, "6개월%": allv.ret_6m.values,
        "추세": data.trend_label(allv).values,
    })
    st.caption(f"{len(show_all):,}종목 · 시총은 달러 환산($M) · 현재가 통화는 국가 기준")
    st.dataframe(show_all, width="stretch", hide_index=True, height=600, column_config={
        "현재가": st.column_config.NumberColumn(format="%.2f"),
        "시총($M)": st.column_config.NumberColumn(format="%.0f"),
        "PBR": st.column_config.NumberColumn(format="%.2f배"),
        "ROE": st.column_config.NumberColumn(format="%.1f%%"),
        "영업익증가율": st.column_config.NumberColumn(format="%.1f%%"),
        "부채비율": st.column_config.NumberColumn(format="%.0f%%"),
        "수급": st.column_config.NumberColumn(format="%+.1f%%"),
        "3개월%": st.column_config.NumberColumn(format="%+.1f%%"),
        "6개월%": st.column_config.NumberColumn(format="%+.1f%%"),
    })
    st.download_button("전체 CSV 내려받기", show_all.to_csv(index=False).encode("utf-8-sig"),
                       "all_stocks.csv", "text/csv", key="all_dl")

with tab_screener:
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
    if only_graham and not only_watch:                # 그레이엄 적정가 아래(안전마진 +)만 — 금융·적자는 자동 제외
        f = f[(data.graham(f).margin > 0) & ~f.sector.isin(data.FINANCIAL_SECTORS)]
        if f.empty:
            st.warning("조건을 통과한 종목 중 그레이엄 적정가 아래(안전마진 +)인 것이 없습니다. "
                       "안전마진 필터를 끄거나 종목 조건을 풀어보세요.")
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
                        "수급중앙": st.column_config.NumberColumn(format="%+.1f%%"),
                    })

    view = f.sort_values("score", ascending=False).head(100)
    view = view.assign(trend_label=data.trend_label(view), rs=rs_all.reindex(view.index))
    metric_cfg = {                                      # 두 표(랭킹·대시보드)가 함께 쓰는 지표 서식
        "PBR": st.column_config.NumberColumn(format="%.2f배"),
        "ROE": st.column_config.NumberColumn(format="%.1f%%"),
        "영업익증가율": st.column_config.NumberColumn(format="%.1f%%"),
        "부채비율": st.column_config.NumberColumn(format="%.0f%%"),
        "수급": st.column_config.NumberColumn(format="%+.1f%%"),
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
            "당일%": st.column_config.NumberColumn(format="%+.1f%%"),
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
    c_dl, c_snap = st.columns([1, 1])
    c_dl.download_button("CSV 내려받기", show.to_csv(index=False).encode("utf-8-sig"),
                         "screener.csv", "text/csv")
    if not only_watch:                                  # 전방 추적: 오늘 상위 N종목을 스냅샷으로 저장
        n_snap = min(20, len(view))
        if c_snap.button(f"📸 오늘 추천 상위 {n_snap}종목 저장 (전방 추적)",
                         help="지금 상위 종목을 오늘 날짜로 기록합니다. 시간이 지나면 아래 '성과 추적'에서 "
                              "벤치마크 대비 성과를 봅니다. 로컬에 저장되며, 보존하려면 커밋하세요."):
            saved = picks_mod.snapshot(view.head(n_snap), preset, bench_now())
            st.success(f"{saved}종목 저장 완료 ({pd.Timestamp.now():%Y-%m-%d}). "
                       "보존하려면 picks.csv·bench.csv를 커밋하세요.")

    detail_view.render(df, view, event, pct_all, by_sector, CORE)

    # ---------------- 성과 추적 (전방 테스트) ----------------
    if not picks_mod.load().empty:
        with st.expander("📈 성과 추적 — 저장한 추천의 실제 성과"):
            perf = picks_mod.performance(price_now, bench_now())
            if perf.empty:
                st.caption("아직 저장된 추천이 없습니다.")
            else:
                st.caption("저장일(코호트)별 · 전략 = 상위 종목 동일가중 수익률(왕복 비용 차감) · "
                           "벤치마크 = SPY·KODEX200 · 상폐·정지 종목은 −100%로 집계(생존편향 방지). "
                           "**표본이 적고 기간이 짧으면 운에 가깝습니다** — 수개월 쌓인 뒤 판단하세요.")
                st.dataframe(perf, hide_index=True, width="stretch", column_config={
                    "전략수익률": st.column_config.NumberColumn(format="%+.1f%%"),
                    "벤치수익률": st.column_config.NumberColumn(format="%+.1f%%"),
                    "초과": st.column_config.NumberColumn("초과수익", format="%+.1f%%"),
                })

    st.caption("SEC EDGAR·DART 공시 재무, Yahoo 시세, 네이버 증권 수급(한국)을 정해진 규칙으로 정렬해 보여주는 도구입니다. "
               "투자 자문이 아니며, 투자 판단과 그 결과의 책임은 본인에게 있습니다.")
