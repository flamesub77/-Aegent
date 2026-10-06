"""데이터 소스: 분석 엔진이 쓰는 코일 데이터와 강종 스펙을 한 곳에서 제공한다.

- SampleSource: files/steel.db (가상 데이터)
- UploadSource: 사용자가 올린 파일 (tools/upload.py가 표준 컬럼으로 바꾼 DataFrame)

현재 소스는 실행 컨텍스트(스레드)별로 정한다. Streamlit은 세션마다 스크립트를 따로 실행하므로
app.py가 매 실행 첫머리에 use_source()를 부르면 세션끼리 섞이지 않는다.
"""
from contextvars import ContextVar
from functools import lru_cache

import numpy as np
import pandas as pd

from tools import db

REQUIRED = ["coil_no", "prod_date", "grade", "line"]
SPEC_COLUMNS = {  # 재질 → (하한 컬럼, 상한 컬럼)
    "YS": ("ys_min", "ys_max"), "TS": ("ts_min", "ts_max"), "EL": ("el_min", None), "BH": ("bh_min", None),
    "rbar": ("rbar_min", None), "n_value": ("n_min", None), "dr": (None, "dr_max"),
}


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


class DataSource:
    """정규화된 코일 DataFrame + 강종 스펙."""

    def __init__(self, coils: pd.DataFrame, grades: pd.DataFrame, name: str, kind: str):
        missing = [c for c in REQUIRED if c not in coils.columns]
        if missing:
            raise ValueError(f"필수 컬럼이 없습니다: {missing}")
        self.name, self.kind = name, kind
        self.coils = self._prepare(coils)
        self.grades = grades.set_index("grade", drop=False) if len(grades) else grades

    @staticmethod
    def _prepare(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["prod_date"] = pd.to_datetime(df["prod_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        df = df[df["prod_date"].notna()]
        df["month"] = df["prod_date"].str[:7]
        if "thk" in df:
            df["thk_band"] = pd.cut(df["thk"], [0, 0.75, 1.0, 1.4, 99],
                                    labels=["~0.75", "0.75~1.0", "1.0~1.4", "1.4~"]).astype(str)
        if {"r0", "r45", "r90"} <= set(df.columns):  # prd_v2 R1: r̄, Δr 자동 계산
            df["rbar"] = ((df["r0"] + 2 * df["r45"] + df["r90"]) / 4).round(3)
            df["dr"] = ((df["r0"] - 2 * df["r45"] + df["r90"]) / 2).round(3)
        df["has_defect"] = df["defect_type"].fillna("없음") != "없음" if "defect_type" in df else False
        df["passed"] = df["judge"] == "합격" if "judge" in df else np.nan
        return df.reset_index(drop=True)

    # ---- 조회 -------------------------------------------------------------
    def has(self, col: str) -> bool:
        return col in self.coils.columns and self.coils[col].notna().any()

    def grade_codes(self) -> list[str]:
        return sorted(self.coils["grade"].dropna().unique().tolist())

    def lines(self) -> list[str]:
        return sorted(self.coils["line"].dropna().unique().tolist())

    def date_range(self) -> tuple[str, str]:
        return self.coils["prod_date"].min(), self.coils["prod_date"].max()

    def grade(self, code: str) -> dict:
        """강종 스펙 한 줄. 스펙 표에 없는 강종이면 빈 스펙과 family=None."""
        if code not in set(self.coils["grade"]):
            raise ValueError(f"알 수 없는 강종 코드: {code}")
        if len(self.grades) and code in self.grades.index:
            return self.grades.loc[code].to_dict()
        return {"grade": code, "family": None, "lines": "/".join(
            sorted(self.coils.loc[self.coils["grade"] == code, "line"].unique()))}

    def spec(self, code: str) -> dict:
        """재질별 (하한, 상한). 데이터에 있는 재질만. 스펙이 없으면 (None, None)."""
        g = self.grade(code)
        out = {}
        for prop, (lo_col, hi_col) in SPEC_COLUMNS.items():
            if not self.has(prop):
                continue
            lo, hi = _num(g.get(lo_col)) if lo_col else None, _num(g.get(hi_col)) if hi_col else None
            if prop == "BH" and lo is None:  # BH는 BH 강종만
                continue
            if prop == "BH" and self.coils.loc[self.coils["grade"] == code, "BH"].isna().all():
                continue
            out[prop] = (lo, hi)
        return out


@lru_cache(maxsize=1)
def sample_source() -> DataSource:
    return DataSource(db.fetch_coils(), db.load_grade_master(), "샘플 데이터 (steel.db)", "sample")


_current: ContextVar[DataSource | None] = ContextVar("datasource", default=None)


def use_source(src: DataSource | None):
    """현재 실행 컨텍스트의 데이터 소스를 바꾼다. None이면 샘플."""
    _current.set(src)


def get_source() -> DataSource:
    return _current.get() or sample_source()
