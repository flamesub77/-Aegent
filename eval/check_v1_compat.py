"""v2 데이터 재생성 후 v1 컬럼·정답지가 그대로인지 확인한다.

실행: python -m eval.check_v1_compat <v1 스냅샷 폴더>
"""
import sqlite3
import sys
from pathlib import Path

import pandas as pd

import config


def main(v1_dir: str) -> bool:
    v1 = Path(v1_dir)
    ok = True
    for name in ("coil_data.csv", "grade_master.csv", "answer_key.csv"):
        old = pd.read_csv(v1 / name, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        new = pd.read_csv(config.DATA_DIR / name, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        same_cols = list(old.columns) == list(new.columns[: len(old.columns)])
        same_vals = same_cols and old.equals(new[old.columns])
        added = [c for c in new.columns if c not in old.columns]
        print(f"{name}: 행 {len(old)}→{len(new)}, 기존 컬럼 순서 {'동일' if same_cols else '다름'}, "
              f"기존 값 {'동일' if same_vals else '다름'}, 추가 컬럼 {added}")
        ok &= same_vals
    for table in ("coil", "grade_master"):
        with sqlite3.connect(v1 / "steel.db") as a, sqlite3.connect(config.DB_PATH) as b:
            old = pd.read_sql(f"SELECT * FROM {table}", a)
            new = pd.read_sql(f"SELECT * FROM {table}", b)
        same = old.equals(new[old.columns])
        print(f"steel.db {table}: 기존 값 {'동일' if same else '다름'}")
        ok &= same
    print("결과:", "v1 호환 OK" if ok else "v1과 다름")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1]) else 1)
