"""files/steel.db 읽기 전용 접근."""
import sqlite3
from contextlib import contextmanager

import pandas as pd

from config import DB_PATH
from tools.guard import ensure_allowed

LINES = ("CAL", "CGL_GA")


@contextmanager
def connect(db_path=DB_PATH):
    """sqlite URI mode=ro로 연결해 쓰기를 원천 차단한다."""
    path = ensure_allowed(db_path)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        yield conn
    finally:
        conn.close()


def read_sql(sql: str, params: tuple = ()) -> pd.DataFrame:
    """파라미터 바인딩으로만 조회한다."""
    with connect() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def load_grade_master() -> pd.DataFrame:
    return read_sql("SELECT * FROM grade_master")


def grade_codes() -> list[str]:
    return load_grade_master()["grade"].tolist()


def get_grade(grade: str) -> dict | None:
    df = read_sql("SELECT * FROM grade_master WHERE grade = ?", (grade,))
    return None if df.empty else df.iloc[0].to_dict()


def fetch_coils(grade=None, line=None, start_date=None, end_date=None,
                thk_min=None, thk_max=None, coil_pos=None) -> pd.DataFrame:
    """조건에 맞는 coil 행을 반환한다. 모든 값은 바인딩 파라미터로 전달한다."""
    clauses, params = [], []
    if grade:
        clauses.append("grade = ?"); params.append(grade)
    if line:
        clauses.append("line = ?"); params.append(line)
    if start_date:
        clauses.append("prod_date >= ?"); params.append(start_date)
    if end_date:
        clauses.append("prod_date <= ?"); params.append(end_date)
    if thk_min is not None:
        clauses.append("thk >= ?"); params.append(float(thk_min))
    if thk_max is not None:
        clauses.append("thk <= ?"); params.append(float(thk_max))
    if coil_pos:
        clauses.append("coil_pos = ?"); params.append(coil_pos)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return read_sql(f"SELECT * FROM coil{where} ORDER BY prod_date", tuple(params))
