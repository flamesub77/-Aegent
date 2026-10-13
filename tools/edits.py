"""데이터 탭 편집 (prd_v5 T6): 값 고치기 · 행 제외(이상치 제거) · 이상치 도우미 · 수정본 만들기.

편집 내용(draft)은 원본을 건드리지 않는 기록이다:
  {"changes": {(코일번호, 열): {"old", "new", "at"}}, "excluded": {코일번호: 시각}}
수정본 = 원본 coils에 draft를 적용한 새 DataSource (원본 파일·데이터는 그대로).
누가 바꿨는지는 남기지 않는다 (prd_v5 열린 질문: 아니오).
"""
import copy
from datetime import datetime

import numpy as np
import pandas as pd

from tools.datasource import DataSource

ID = "coil_no"
LOCKED = {"coil_no", "hot_coil_no", "slab_no", "heat_no", "month", "thk_band", "has_defect", "passed"}  # 번호·계산 열은 잠금


def empty() -> dict:
    return {"changes": {}, "excluded": {}}


def clone(draft: dict) -> dict:
    return copy.deepcopy(draft)


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _same(a, b) -> bool:
    if a is None or (isinstance(a, float) and np.isnan(a)) or a is pd.NA:
        return b is None or (isinstance(b, float) and np.isnan(b)) or b is pd.NA
    try:
        return bool(a == b) or (pd.isna(a) and pd.isna(b))
    except (TypeError, ValueError):
        return False


def apply(df: pd.DataFrame, draft: dict, drop_excluded: bool = True) -> pd.DataFrame:
    """draft를 적용한 사본. drop_excluded=False면 제외 행을 남기고 "제외" 열을 붙인다 (편집 표용)."""
    out = df.copy()
    pos = pd.Series(range(len(out)), index=out[ID].astype(str))
    for (coil, col), c in draft["changes"].items():
        if col in out.columns and coil in pos.index:
            i = pos[coil]
            i = i.iloc[0] if isinstance(i, pd.Series) else i
            try:
                out.iloc[i, out.columns.get_loc(col)] = c["new"]
            except (TypeError, ValueError):  # 형이 안 맞으면 object로 바꿔서
                out[col] = out[col].astype(object)
                out.iloc[i, out.columns.get_loc(col)] = c["new"]
    excluded = set(draft["excluded"])
    if drop_excluded:
        return out[~out[ID].astype(str).isin(excluded)].reset_index(drop=True)
    out.insert(0, "제외", out[ID].astype(str).isin(excluded))
    return out


def diff(shown: pd.DataFrame, edited: pd.DataFrame, draft: dict, original: pd.DataFrame | None = None) -> dict:
    """편집 표(shown → edited)의 바뀐 칸·제외 체크를 draft에 합친 새 draft. original: 처음 값(이전 값 기록용)."""
    new = clone(draft)
    if edited is None or edited.empty:
        return new
    ids = shown[ID].astype(str).tolist()
    orig = original.set_index(original[ID].astype(str)) if original is not None else None
    for col in edited.columns:
        if col not in shown.columns or col == ID:
            continue
        a, b = shown[col].tolist(), edited[col].tolist()
        for coil, x, y in zip(ids, a, b):
            if _same(x, y):
                continue
            if col == "제외":
                if y:
                    new["excluded"][coil] = _now()
                else:
                    new["excluded"].pop(coil, None)
                continue
            if col in LOCKED:
                continue
            first = new["changes"].get((coil, col), {}).get("old", orig[col].get(coil, x) if orig is not None and col in orig else x)
            if _same(first, y):
                new["changes"].pop((coil, col), None)  # 원래 값으로 되돌림
            else:
                new["changes"][(coil, col)] = {"old": first, "new": y, "at": _now()}
    return new


def outlier_mask(df: pd.DataFrame, col: str, k: float = 3.0, spec=(None, None)) -> pd.Series:
    """평균 ± kσ 밖 또는 SPEC에서 50% 이상 벗어난 값 (prd_v5 T6 이상치 도우미)."""
    if col not in df:
        return pd.Series(False, index=df.index)
    v = pd.to_numeric(df[col], errors="coerce")
    m, s = v.mean(), v.std()
    out = (v - m).abs() > k * s if s and s == s else pd.Series(False, index=df.index)
    lo, hi = spec
    if lo is not None:
        out |= v < lo * 0.5
    if hi is not None:
        out |= v > hi * 1.5
    return out.fillna(False)


def exclude(draft: dict, coils) -> dict:
    new = clone(draft)
    for c in coils:
        new["excluded"].setdefault(str(c), _now())
    return new


def summary(draft: dict) -> str:
    return f"제외 {len(draft['excluded'])}행, 변경 {len(draft['changes'])}칸"


def count(draft: dict) -> int:
    return len(draft["excluded"]) + len(draft["changes"])


def log_rows(draft: dict) -> pd.DataFrame:
    """기록 표: 시각 · 코일번호 · 무엇 · 이전 값 · 새 값."""
    rows = [{"시각": c["at"], "코일번호": coil, "무엇": col, "이전 값": c["old"], "새 값": c["new"]}
            for (coil, col), c in draft["changes"].items()]
    rows += [{"시각": at, "코일번호": coil, "무엇": "행 제외", "이전 값": "", "새 값": ""}
             for coil, at in draft["excluded"].items()]
    return pd.DataFrame(rows, columns=["시각", "코일번호", "무엇", "이전 값", "새 값"]).sort_values("시각", ascending=False)


def edited_source(src: DataSource, draft: dict, name: str | None = None) -> DataSource:
    """수정본 DataSource. 원본 이름 뒤에 (수정 n건), edit_note에 요약."""
    base = src.name.replace(" (기본)", "")
    df = apply(src.coils, draft)
    new = DataSource(df, src.grades.reset_index(drop=True) if len(src.grades) else src.grades,
                     name or f"{base} (수정 {count(draft)}건)", src.kind)
    new.edit_note = summary(draft)
    return new
