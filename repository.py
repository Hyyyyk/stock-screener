"""SQLite 읽기 전담 계층. 화면/점수 코드는 SQL을 직접 알 필요가 없다."""
import sqlite3

import pandas as pd

from settings import DB


def read_table(con, table):
    try:
        return pd.read_sql(f"select * from {table}", con)
    except pd.errors.DatabaseError:
        return pd.DataFrame()


def load_snapshot_tables():
    with sqlite3.connect(DB) as con:
        return {name: read_table(con, name)
                for name in ("us_fundamentals", "kr_fundamentals", "prices", "sectors", "flows")}


def scalar(sql):
    with sqlite3.connect(DB) as con:
        try:
            return pd.read_sql(sql, con).iloc[0, 0]
        except Exception:
            return None
