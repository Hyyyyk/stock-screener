"""현재 stocks.db 전체 품질 점검. 실행: python check_data.py"""
import sqlite3

import pandas as pd

import data
from quality import has_errors, print_report, validate_stocks


def main():
    stocks = data.load_stocks()
    with sqlite3.connect(data.DB) as con:
        prices = pd.read_sql("select * from prices", con)
    findings = validate_stocks(stocks, prices, data.expected_annual_year())
    print_report("통합 종목", findings, len(stocks))
    print("\n국가별 데이터 완성도")
    print(stocks.groupby("country").data_completeness.agg(["count", "mean", "min"]).round(1).to_string())
    return 1 if has_errors(findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
