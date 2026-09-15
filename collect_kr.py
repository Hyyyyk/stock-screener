"""한국 재무 수집 - DART OpenAPI.  실행: python collect_kr.py

fnlttMultiAcnt 는 corp_code 를 20개까지 한 번에 받고, 응답에 전기(frmtrm_amount)가
같이 오므로 연도별로 두 번 부를 필요가 없다. 2,800종목이면 호출 140여 회.

키는 .env 의 DART_API_KEY 에서 읽는다 (코드에 박지 않는다).
"""
import io
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

DB = "stocks.db"
CACHE = Path("cache")
UA = {"User-Agent": "stock-screener"}
BATCH = 20               # fnlttMultiAcnt 상한
SHARE_WORKERS = 2        # 주식수는 종목당 1호출 - 너무 빠르면 DART 가 연결을 끊는다
SHARE_PAUSE = 0.3        # 워커 2개 × 0.3초 → 약 6 req/s
YEAR = "2025"            # 사업보고서 기준연도 (응답에 전기=2024 가 함께 온다)
ANNUAL_REPORT = "11011"  # 사업보고서
KRX_LIST = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"

# DART 계정명 → 우리 컬럼. 업종마다 쓰는 이름이 달라 앞에서부터 찾는다.
ACCOUNTS = {
    "assets":      ["자산총계"],
    "liabilities": ["부채총계"],
    "equity":      ["자본총계"],
    "revenue":     ["매출액", "영업수익", "순이자손익", "이자수익"],   # 금융사는 매출액이 없다
    "op_income":   ["영업이익", "영업이익(손실)"],
    "net_income":  ["당기순이익", "당기순이익(손실)"],
}


def key():
    """DART 인증키. 로컬은 .env, 클라우드(Streamlit)는 환경변수/Secrets 로 넣는다."""
    env = {}
    try:
        env = dict(l.strip().split("=", 1) for l in open(".env", encoding="utf-8") if "=" in l)
    except FileNotFoundError:
        pass                                      # 클라우드엔 .env 가 없다 - 환경변수를 본다
    k = env.get("DART_API_KEY") or os.environ.get("DART_API_KEY")
    if not k:
        raise SystemExit("DART_API_KEY 가 없습니다 (.env 또는 Secrets 에 넣어주세요)")
    return k


def api(path, **params):
    url = f"https://opendart.fss.or.kr/api/{path}?" + urllib.parse.urlencode(
        {"crtfc_key": key(), **params})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def corp_codes():
    """종목코드 → (DART 고유번호, 회사명). 잘 안 바뀌므로 캐시한다."""
    path = CACHE / "dart_corpcode.xml"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        z = zipfile.ZipFile(io.BytesIO(api("corpCode.xml")))
        path.write_bytes(z.read(z.namelist()[0]))
    root = ET.fromstring(path.read_bytes().decode("utf-8"))
    out = {}
    for c in root.iter("list"):
        stock = (c.findtext("stock_code") or "").strip()
        if stock:
            out[stock] = (c.findtext("corp_code"), c.findtext("corp_name"))
    return out


def krx_listed():
    """현재 상장 종목만. DART 목록에는 상장폐지 기업도 남아 있어 이걸로 거른다."""
    path = CACHE / "krx_corplist.html"
    if not path.exists():
        with urllib.request.urlopen(urllib.request.Request(KRX_LIST, headers=UA), timeout=60) as r:
            path.write_bytes(r.read())
    html = path.read_bytes().decode("cp949")
    out = {}
    for row in html.split("<tr>")[2:]:
        td = [re.sub(r"\s+", " ", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)[:3]]
        if len(td) == 3 and re.fullmatch(r"\d{6}", td[2]):
            out[td[2]] = (td[0], "KOSDAQ" if "코스닥" in td[1] else "KOSPI")
    return out


# KRX 업종(한국표준산업분류 원문 158종) → 미국 SIC 와 같은 대분류 이름.
# 위에서부터 처음 맞는 규칙이 이긴다. 순서가 의미를 가진다:
#  - 유통(소매/도매)을 먼저 봐야 "섬유…소매업" 이 섬유로, "기계장비…도매업" 이 기계로 새지 않는다
#  - 금융·부동산·지주를 제조업 키워드보다 먼저 본다
#  - "통신 및 방송 장비 제조업"(삼성전자)은 통신이 아니라 전자로 가야 해서 통신보다 앞에 둔다
KSIC_RULES = [
    (["소매업", "판매업"], "소매"),
    (["도매업", "상품 중개"], "도매"),
    (["회사 본부"], "지주·투자"),
    (["보험"], "보험"),
    (["은행", "금융", "신탁업"], "은행·증권"),
    (["부동산"], "부동산·리츠"),
    (["임대업", "연구개발", "과학 및 기술", "과학기술", "엔지니어링", "시장조사",
      "전문디자인", "전문 서비스", "사업지원", "사업시설", "경비"], "전문서비스"),
    (["공사업", "건설업"], "건설"),
    (["교육", "학원"], "교육·비영리"),
    (["숙박", "수리업", "개인 서비스"], "숙박·개인서비스"),
    (["작물", "어업"], "농림어업"),
    (["전기업", "가스 제조", "증기", "폐기물", "원료 재생"], "유틸리티"),
    (["운송장비", "자동차", "선박", "항공기", "트레일러", "총포탄"], "운송장비"),
    (["운송", "여행사"], "운송"),
    (["반도체", "전자부품", "통신 및 방송 장비", "영상 및 음향기기", "매체 제조",
      "조명장치", "절연선", "전지", "전동기", "전기장비", "가정용 기기"], "전자·반도체"),
    (["컴퓨터 및 주변장치", "기계 제조", "기계 및 장비"], "기계·컴퓨터"),
    (["의료용 기기", "정밀기기", "광학기기"], "정밀기기·의료기기"),
    (["의약", "의료용품", "화학", "비료", "플라스틱 물질"], "화학·제약"),
    (["석유 정제"], "정유"),
    (["철강", "비철금속", "금속", "시멘트", "유리", "요업", "비금속 광물",
      "플라스틱제품", "고무제품"], "소재·금속"),
    (["식품", "음료", "담배", "도축", "수산물", "과실", "곡물", "유지 및 낙농",
      "사료", "빵", "도시락"], "식음료·담배"),
    (["섬유", "직물", "방적", "의복", "가죽", "신발"], "섬유·의류"),
    (["종이", "펄프", "가구", "목재", "나무제품", "인쇄"], "목재·종이·인쇄"),
    (["소프트웨어", "컴퓨터 프로그래밍", "자료처리", "정보 서비스"], "소프트웨어·IT서비스"),
    (["전기 통신", "방송업"], "통신"),
    (["영화", "오디오물", "예술", "유원지", "스포츠", "광고", "기록매체"], "미디어·레저"),
    (["귀금속", "악기", "경기용구", "기타 제품 제조"], "기타제조"),
]


def sector_of(name, ksic):
    """회사명·KRX 업종 → 대분류. 스팩은 업종이 '기타 금융업'이라 이름으로 먼저 거른다."""
    if "스팩" in name:
        return "SPAC·페이퍼컴퍼니"
    # KRX 는 지주회사를 전부 '기타 금융업'에 넣는다. KB금융(은행지주)과 SK·LG(사업지주)가
    # 한 칸에 섞이므로 이름으로 가른다. 미국 SIC 67(지주·투자)과 기준을 맞춘다.
    if ksic == "기타 금융업":
        is_fin = any(k in name for k in ("금융", "신한지주", "카드", "캐피탈"))
        return "은행·증권" if is_fin else "지주·투자"
    for keywords, group in KSIC_RULES:
        if any(k in ksic for k in keywords):
            return group
    return "기타"


def krx_sectors():
    """종목코드 → (대분류, KRX 업종 원문). krx_listed 와 같은 캐시 파일을 읽는다."""
    krx_listed()                                   # 캐시가 없으면 받아둔다
    html = (CACHE / "krx_corplist.html").read_bytes().decode("cp949")
    out = {}
    for row in html.split("<tr>")[2:]:
        td = [re.sub(r"\s+", " ", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)[:4]]
        if len(td) == 4 and re.fullmatch(r"\d{6}", td[2]):
            out[td[2]] = (sector_of(td[0], td[3]), td[3])
    return out


def num(s):
    """'1,234' → 1234.0, '-' 나 빈칸은 None."""
    s = (s or "").replace(",", "").strip()
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


def parse(rows):
    """DART 응답 행들 → {corp_code: {컬럼: 값}}. 연결(CFS) 우선, 없으면 별도(OFS)."""
    picked = {}
    for r in rows:
        cc = r["corp_code"]
        # 같은 계정이 여러 번 나오면(지배/비지배 지분 등) 먼저 나온 것을 쓴다
        picked.setdefault((cc, r["fs_div"], r["account_nm"]), r)

    out = {}
    for (cc, fs, name), r in picked.items():
        rec = out.setdefault(cc, {})
        for col, names in ACCOUNTS.items():
            if name not in names:
                continue
            rank = names.index(name)                       # 앞쪽 이름일수록 우선
            prefer = (0 if fs == "CFS" else 1, rank)       # 연결 우선, 그다음 계정명 우선순위
            if prefer < rec.get(f"_{col}_pref", (9, 9)):
                rec[f"_{col}_pref"] = prefer
                rec[col] = num(r["thstrm_amount"])
                rec[f"{col}_prev"] = num(r["frmtrm_amount"])
    for rec in out.values():
        for k in [k for k in rec if k.startswith("_")]:
            del rec[k]
    return out


def shares_of(corp_code):
    """보통주 유통주식수. (값, 실패여부) 를 돌려준다 - 실패를 '없음'으로 숨기지 않는다.

    발행총수(isu_stock_totqy)는 정관상 한도라 쓸 수 없다.
    """
    for attempt in range(5):
        try:
            d = json.loads(api("stockTotqySttus.json", corp_code=corp_code,
                               bsns_year=YEAR, reprt_code=ANNUAL_REPORT))
            time.sleep(SHARE_PAUSE)
            if d.get("status") == "013":       # 해당 보고서 없음 - 재시도해도 소용없다
                return None, False
            if d.get("status") != "000":
                return None, True
            rows = {x.get("se", "").strip(): num(x.get("distb_stock_co"))
                    for x in d.get("list", [])}
            return rows.get("보통주") or rows.get("합계"), False
        except Exception:
            time.sleep(2 ** attempt)           # 연결 끊김 = 스로틀링. 물러섰다 재시도
    return None, True


def collect_shares(corp_list):
    """종목당 1호출. DART 는 일 20,000회 한도지만 순간 속도를 내면 연결을 끊는다."""
    with ThreadPoolExecutor(max_workers=SHARE_WORKERS) as pool:
        results = list(pool.map(shares_of, corp_list))
    vals = [v for v, _ in results]
    failed = sum(1 for _, f in results if f)
    return vals, failed


def derive(df):
    eq = df.equity.where(df.equity > 0)                    # 자본잠식이면 비율 지표가 무의미
    df["roe"] = df.net_income / eq * 100
    df["roa"] = df.net_income / df.assets.where(df.assets > 0) * 100
    df["debt_ratio"] = df.liabilities / eq * 100
    df["opm"] = df.op_income / df.revenue.where(df.revenue > 0) * 100

    prev_op = df.op_income_prev.where(df.op_income_prev > 0)   # 적자→흑자는 증가율이 무의미
    df["op_growth"] = (df.op_income / prev_op - 1) * 100
    prev_rev = df.revenue_prev.where(df.revenue_prev > 0)
    df["rev_growth"] = (df.revenue / prev_rev - 1) * 100

    # 전년 이익이 0에 가까우면 증가율이 수천 %로 튄다. 순위는 그대로, 표시만 자른다.
    df["op_growth"] = df.op_growth.clip(-100, 300)
    df["rev_growth"] = df.rev_growth.clip(-100, 300)
    df["opm"] = df.opm.clip(-100, 100)
    return df


def previous_shares():
    """이전 실행에서 받아둔 {corp_code: 주식수}."""
    try:
        with sqlite3.connect(DB) as con:
            d = pd.read_sql("select corp_code, shares from kr_fundamentals "
                            "where shares is not null", con)
        return dict(zip(d.corp_code, d.shares))
    except (pd.errors.DatabaseError, KeyError):
        return {}


def main():
    listed, codes = krx_listed(), corp_codes()
    targets = [(s, codes[s][0], listed[s][0], listed[s][1]) for s in listed if s in codes]
    print(f"KRX 상장 {len(listed):,} · DART 매칭 {len(targets):,}종목 "
          f"· 호출 {-(-len(targets) // BATCH):,}회")

    # 재무는 한 번 받으면 분기까지 안 바뀐다. 캐시해두고 재실행 때 재사용해야
    # 주식수만 다시 받을 때 DART 를 또 135번 두드리지 않는다.
    fin_cache = CACHE / f"dart_fin_{YEAR}.json"
    if fin_cache.exists():
        got = json.loads(fin_cache.read_text(encoding="utf-8"))
        print(f"  재무 캐시 재사용 {len(got):,}종목")
        return finish(targets, got, 0)

    got, missing = {}, 0
    for i in range(0, len(targets), BATCH):
        chunk = targets[i:i + BATCH]
        try:
            d = json.loads(api("fnlttMultiAcnt.json",
                               corp_code=",".join(c[1] for c in chunk),
                               bsns_year=YEAR, reprt_code=ANNUAL_REPORT))
            if d.get("status") == "000":
                got.update(parse(d["list"]))
            else:
                missing += len(chunk)              # 013 = 해당 기간 보고서 없음
        except Exception as e:
            missing += len(chunk)
            print(f"  배치 {i // BATCH} 실패: {type(e).__name__}")
        if (i // BATCH) % 25 == 0:
            print(f"  {i + len(chunk):>5,}/{len(targets):,}  받음 {len(got):,}")
        time.sleep(0.1)

    fin_cache.write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")
    return finish(targets, got, missing)


def finish(targets, got, missing):
    rows = [{"stock_code": s, "corp_code": cc, "name": nm, "market": mk, **got[cc]}
            for s, cc, nm, mk in targets if cc in got]
    if not rows:
        raise SystemExit("DART 에서 받은 재무가 없습니다. 차단이 풀린 뒤 다시 실행하세요.")
    df = derive(pd.DataFrame(rows))

    df["ticker"] = df.stock_code + df.market.map({"KOSPI": ".KS", "KOSDAQ": ".KQ"})
    sectors = krx_sectors()
    df["sector"] = df.stock_code.map(lambda c: sectors.get(c, ("미분류", None))[0])
    df["sic_desc"] = df.stock_code.map(lambda c: sectors.get(c, (None, None))[1])

    # 이미 받아둔 주식수는 그대로 두고 빈 것만 채운다 - 끊겨도 다시 돌리면 이어진다
    prev = previous_shares()
    df["shares"] = df.corp_code.map(prev)
    todo = df.index[df.shares.isna()]
    print(f"주식수 조회 {len(todo):,}종목 (기존 {len(prev):,}개 재사용)")
    if len(todo):
        vals, share_fail = collect_shares(df.loc[todo, "corp_code"].tolist())
        df.loc[todo, "shares"] = vals
        if share_fail:
            print(f"  주식수 실패 {share_fail:,}개 - 다시 실행하면 이어서 받습니다")
    with sqlite3.connect(DB) as con:
        df.to_sql("kr_fundamentals", con, if_exists="replace", index=False)

    print(f"\n{DB} · kr_fundamentals · {len(df):,}종목 저장 (보고서 없음 {missing:,})")
    have = {c: int(df[c].notna().sum()) for c in ["roe", "debt_ratio", "op_growth", "opm", "shares"]}
    print("지표별 값이 있는 종목 수:", have)
    return df


if __name__ == "__main__":
    main()
