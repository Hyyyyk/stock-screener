"""업종 수집 - SEC submissions API.  실행: python collect_sic.py

SIC 코드는 회사당 1호출이어야 한다(frames 같은 일괄 경로가 없다).
대신 거의 바뀌지 않으니 한 번 받아두면 끝. 이미 받아둔 회사는 건너뛰므로
중간에 끊겨도 다시 돌리면 남은 것만 채운다.

SEC 권고는 10 req/s 이고, 넘기면 429 로 막는다. 실측상 5 워커를 쉬지 않고
돌리면 45 req/s 가 되어 차단당한다. 그래서 요청마다 쉬어 8 req/s 아래로 맞춘다.
"""
import json
import sqlite3
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

UA = {"User-Agent": "stock-screener gusrkds96@gmail.com"}
DB = "stocks.db"
WORKERS = 4
PER_REQUEST_PAUSE = 0.5        # 워커 4개 × 0.5초 → 약 8 req/s

# SIC 앞 2자리 → 화면에 쓸 업종 대분류. (시작, 끝, 이름) 앞에서부터 맞는 것.
# 은행·보험·리츠를 갈라놓는 게 핵심 목적이다. 부채비율 잣대가 제조업과 전혀 다르다.
SIC_GROUPS = [
    (1, 9, "농림어업"), (10, 14, "광업·에너지"), (15, 17, "건설"),
    (20, 21, "식음료·담배"), (22, 23, "섬유·의류"), (24, 27, "목재·종이·인쇄"),
    (28, 28, "화학·제약"), (29, 29, "정유"), (30, 34, "소재·금속"),
    (35, 35, "기계·컴퓨터"), (36, 36, "전자·반도체"), (37, 37, "운송장비"),
    (38, 38, "정밀기기·의료기기"), (39, 39, "기타제조"),
    (40, 47, "운송"), (48, 48, "통신"), (49, 49, "유틸리티"),
    (50, 51, "도매"), (52, 59, "소매"),
    (60, 62, "은행·증권"), (63, 64, "보험"), (65, 66, "부동산·리츠"), (67, 67, "지주·투자"),
    (70, 72, "숙박·개인서비스"), (73, 73, "소프트웨어·IT서비스"), (78, 79, "미디어·레저"),
    (80, 80, "헬스케어서비스"), (82, 86, "교육·비영리"), (87, 89, "전문서비스"),
]

# 67xx(지주·투자) 안에 성격이 전혀 다른 것들이 섞여 있어 4자리로 따로 뺀다
SIC_EXACT = {"6798": "부동산·리츠", "6770": "SPAC·페이퍼컴퍼니"}


def group_of(sic):
    """SIC 4자리 → 업종 대분류 이름."""
    if not sic or not str(sic).strip().isdigit():
        return "미분류"
    sic = str(sic).strip()
    if sic in SIC_EXACT:
        return SIC_EXACT[sic]
    major = int(sic[:-2] or 0)                       # 3571 → 35
    for lo, hi, name in SIC_GROUPS:
        if lo <= major <= hi:
            return name
    return "기타"


def one(cik):
    """성공하면 dict, 끝내 실패하면 None. 실패를 '미분류'로 숨기지 않는다."""
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    for attempt in range(25):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                d = json.load(r)
            time.sleep(PER_REQUEST_PAUSE)
            return {"cik": int(cik), "sic": d.get("sic"), "sic_desc": d.get("sicDescription"),
                    "sector": group_of(d.get("sic"))}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            # 429 차단은 10~20분씩 간다. 짧게 재시도하면 차단만 길어지니 푹 쉰다.
            # 재시도 횟수를 넉넉히 둬야 차단이 풀릴 때까지 버티고 이어서 받는다.
            time.sleep(60 if e.code == 429 else min(2 ** attempt, 60))
        except Exception:
            time.sleep(2 ** attempt)
    return None


def existing():
    """이미 제대로 받아둔 것 - 재실행 시 건너뛴다."""
    try:
        with sqlite3.connect(DB) as con:
            df = pd.read_sql("select * from sectors", con)
        return df[df.sic.notna() & (df.sic != "")]
    except (pd.errors.DatabaseError, KeyError):
        return pd.DataFrame(columns=["cik", "sic", "sic_desc", "sector"])


def main():
    with sqlite3.connect(DB) as con:
        ciks = pd.read_sql("select distinct cik from us_fundamentals", con).cik.astype(int).tolist()

    done = existing()
    todo = [c for c in ciks if c not in set(done.cik.astype(int))]
    print(f"전체 {len(ciks):,}개사 · 기존 {len(done):,}개 · 받을 것 {len(todo):,}개")
    if not todo:
        print("이미 다 받았습니다.")
        return done

    rows, failed = [], 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, row in enumerate(pool.map(one, todo), 1):
            if row:
                rows.append(row)
            else:
                failed += 1
            if i % 200 == 0:
                rate = i / (time.time() - started)
                print(f"  {i:>5,}/{len(todo):,}  성공 {len(rows):,} 실패 {failed:,}  "
                      f"{rate:.1f}건/s  남은 {(len(todo) - i) / rate / 60:.0f}분")

    df = pd.concat([done, pd.DataFrame(rows)], ignore_index=True).drop_duplicates("cik")
    with sqlite3.connect(DB) as con:
        df.to_sql("sectors", con, if_exists="replace", index=False)
    print(f"\n{DB} · sectors · {len(df):,}개사 저장 (이번 실패 {failed:,}개)")
    if failed:
        print("실패분은 다시 실행하면 이어서 받습니다.")
    print(df.sector.value_counts().head(15).to_string())
    return df


if __name__ == "__main__":
    main()
