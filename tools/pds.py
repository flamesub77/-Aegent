"""회사 양식(coil data(pds).xlsx) 읽기 (prd_v3 D1).

양식은 제강 → 연주 → 열연 → 냉연 순서의 165열이고, 같은 이름의 열(Heat번호, 두께, YP 등)이 공정마다
반복된다. 그래서 이름이 아니라 열 위치로 공정 블록을 나눈 뒤, 블록마다 표준 컬럼 이름으로 바꾼다.
양식에 없는 항목(합금화 온도, 냉연 결함 등)은 맨 뒤 "추가 열"로 받는다. 없으면 그 분석만 건너뛴다.
"""
import re

import numpy as np
import pandas as pd

# 블록 시작 열 (양식 1행에서 처음 나오는 위치로 찾는다)
BLOCK_START = [("제강", "Heat번호"), ("연주", "Slab번호"), ("열연", "코일번호"), ("냉연", "냉연코일번호")]
COLD_END = "BH"  # 냉연 블록의 마지막 열. 그 뒤는 추가 열

# 블록별 원본 열 → 표준 컬럼
STEEL = {
    "Heat번호": "heat_no", "2차정련코드": "refine_code", "Tundish온도": "tundish_temp",
    "C": "C", "Mn": "Mn", "Si": "Si", "P": "P", "S": "S", "Sn": "Sn", "Sol_Al": "Al", "Tot_Al": "Tot_Al",
    "Nb": "Nb", "Ti": "Ti", "V": "V", "Cr": "Cr", "Mo": "Mo", "Ni": "Ni", "Cu": "Cu", "B": "B", "Ca": "Ca",
    "N": "N", "H": "H", "CEQ": "CEQ", "종점온도": "ep_temp", "종점산소(ppm)": "ep_O", "취련횟수": "blow_cnt",
    "LF 총처리시간(분)": "lf_time", "RH 총처리시간(분)": "rh_time", "최저 진공도(torr)": "vac_min",
    "2torr이하 처리시간(분)": "vac_time", "최종합금철 투입후 환류시간(분)": "circ_time",
}
CAST = {
    "Slab번호": "slab_no", "주속": "cast_speed", "주속 편차": "cast_speed_dev", "Slab두께": "slab_thk",
    "Slab폭": "slab_wid", "MLAC 적중률(±3mm)": "mlac", "몰드파우더": "mold_powder", "SEN 종류": "sen_type",
}
HOT = {
    "코일번호": "hot_coil_no", "공장": "hot_plant", "두께": "hot_thk", "압연규격약호": "spec_roll",
    "정정규격약호": "spec_fin", "SRT지시": "SRT_aim", "RDT지시": "RDT_aim", "FDT지시": "FDT_aim", "CT지시": "CT_aim",
    "SRT": "SRT", "RDT": "RDT", "FDT": "FDT", "CT": "CT", "냉각패턴": "cool_pattern", "통과공정": "route",
    "YP": "hot_YS", "TS": "hot_TS", "EL": "hot_EL",
}
COLD = {
    "냉연코일번호": "coil_no", "열연코일번호": "hot_coil_no", "Slab번호": "slab_no", "Heat번호": "heat_no",
    "생산일자": "prod_date", "공장": "plant", "라인": "line", "두께": "thk", "폭": "width", "중량": "weight",
    "냉연규격": "grade", "출강목표": "aim", "용도": "use_code", "라인스피드": "line_speed", "HS": "HS", "SS": "SS",
    "SCS(GJS)": "SCS", "RCS(RQ)": "RCS", "RHS(LTHS)": "RHS", "OAS": "OA", "SPM_EL": "SPM",
    "시편채취위치": "coil_pos", "YP설계": "spec_YS", "TS설계": "spec_TS", "EL설계": "spec_EL",
    "N-value설계": "spec_n_value", "BH설계": "spec_BH", "YP": "YS", "TS": "TS", "EL": "EL", "N-value": "n_value",
    "r0": "r0", "r45": "r45", "r90": "r90", "r-bar": "rbar_given", "BH": "BH",
}
EXTRA = {
    "합금화온도": "GA_temp", "도금욕온도": "pot_temp", "디스케일링압력": "descale_press", "산세속도": "pickle_speed",
    "HCl농도": "hcl_conc", "냉연결함": "defect_type", "냉연결함등급": "defect_grade", "판정": "judge",
    "시생산여부": "trial_flag",
}
BLOCK_MAP = {"제강": STEEL, "연주": CAST, "열연": HOT, "냉연": COLD, "추가": EXTRA}
TEXT = {"heat_no", "refine_code", "slab_no", "mold_powder", "sen_type", "hot_coil_no", "hot_plant", "spec_roll",
        "spec_fin", "cool_pattern", "route", "coil_no", "prod_date", "plant", "line", "grade", "aim", "use_code",
        "coil_pos", "spec_YS", "spec_TS", "spec_EL", "spec_n_value", "spec_BH", "defect_type", "defect_grade",
        "judge", "trial_flag"}
SPEC_PROPS = ["YS", "TS", "EL", "n_value", "BH"]
AIM_STD = {"SRT": "SRT_aim", "RDT": "RDT_aim", "FDT": "FDT_aim", "CT": "CT_aim"}  # (실적 − 지시) 편차


def _base(col) -> str:
    """pandas가 중복 열에 붙인 ".1" 같은 꼬리를 뗀다."""
    return re.sub(r"\.\d+$", "", str(col)).strip()


def is_pds(columns) -> bool:
    names = {_base(c) for c in columns}
    return {"냉연코일번호", "냉연규격", "Slab번호", "압연규격약호"} <= names


def blocks(columns) -> dict:
    """열 위치 → 블록 이름."""
    names = [_base(c) for c in columns]
    starts = []
    for block, first in BLOCK_START:
        idx = names.index(first) if first in names else None
        if block != "제강" and idx is not None:  # 앞 블록 시작보다 뒤에서 찾는다
            prev = starts[-1][1] if starts else 0
            idx = next((i for i in range(prev + 1, len(names)) if names[i] == first), None)
        if idx is not None:
            starts.append((block, idx))
    out = {}
    for k, (block, idx) in enumerate(starts):
        end = starts[k + 1][1] if k + 1 < len(starts) else len(names)
        for i in range(idx, end):
            out[i] = block
    cold = [i for i, b in out.items() if b == "냉연"]
    if cold:
        last = max((i for i in cold if names[i] == COLD_END), default=None)
        if last is not None:
            for i in cold:
                if i > last:
                    out[i] = "추가"
    return out


def parse_spec(text) -> tuple:
    """'185~265' → (185, 265), '34↑' → (34, None), '~600' / '600↓' → (None, 600)."""
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return None, None
    s = str(text).replace(" ", "").replace("이상", "↑").replace("이하", "↓")
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", s)]
    if not nums:
        return None, None
    if "~" in s and len(nums) >= 2:
        return nums[0], nums[1]
    if s.startswith("~") or "↓" in s:
        return None, nums[0]
    return nums[0], None


def standardize(raw: pd.DataFrame) -> pd.DataFrame:
    """pds 양식 DataFrame → 표준 컬럼 DataFrame (분석 엔진 입력)."""
    where = blocks(raw.columns)
    cols = {}
    for i, col in enumerate(raw.columns):
        std = BLOCK_MAP.get(where.get(i, ""), {}).get(_base(col))
        if std and (std not in cols or where[i] in ("냉연", "추가")):  # 같은 표준 이름이면 뒤 블록(제품) 우선
            cols[std] = raw.iloc[:, i]
    df = pd.DataFrame(cols)
    for c in df.columns:
        if c in TEXT:
            s = df[c].astype("string").str.strip()
            df[c] = s.mask(s.isin(["", "-", "N/A", "nan", "None"]))
        else:  # 숫자 칸의 "-", "N/A" 같은 문자는 결측으로 (D3)
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "prod_date" in df:
        df["prod_date"] = pd.to_datetime(df["prod_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for prop in SPEC_PROPS:
        if f"spec_{prop}" in df:
            lohi = df[f"spec_{prop}"].map(parse_spec)
            df[f"spec_{prop}_lo"] = [x[0] for x in lohi]
            df[f"spec_{prop}_hi"] = [x[1] for x in lohi]
            df = df.drop(columns=f"spec_{prop}")
    for f, aim in AIM_STD.items():
        if f in df and aim in df:
            df[f"{f}_dev"] = df[f] - df[aim]
    if {"thk", "hot_thk"} <= set(df.columns):
        df["RED"] = ((1 - df["thk"] / df["hot_thk"]) * 100).round(1)
    if "line" in df:
        df["line"] = df["line"].replace({"CGL": "CGL_GA", "GA": "CGL_GA"})
    if "trial_flag" in df:
        df["trial_flag"] = df["trial_flag"].map(
            lambda v: "Y" if str(v).strip().upper() in ("Y", "1", "TRUE", "시생산", "O") else "N")
    return df


def grade_table(df: pd.DataFrame, base: pd.DataFrame | None = None) -> pd.DataFrame:
    """코일별 SPEC·지시값을 강종 단위로 모아 grade_master 형식으로. base(샘플 grade_master)의 family 등은 유지."""
    spec_cols = {"YS": ("ys_min", "ys_max"), "TS": ("ts_min", "ts_max"), "EL": ("el_min", None),
                 "n_value": ("n_min", None), "BH": ("bh_min", None)}
    rows = []
    for grade, g in df.groupby("grade"):
        row = {"grade": grade}
        for prop, (lo_col, hi_col) in spec_cols.items():
            for side, col in (("lo", lo_col), ("hi", hi_col)):
                src = f"spec_{prop}_{side}"
                if col and src in g and g[src].notna().any():
                    row[col] = g[src].mode().iloc[0]
        for f, aim in AIM_STD.items():
            if aim in g and g[aim].notna().any():
                row[f"std_{f}"] = g[aim].mode().iloc[0]
        row["lines"] = "/".join(sorted(g["line"].dropna().unique()))
        rows.append(row)
    out = pd.DataFrame(rows)
    if base is not None and len(base):
        base = base.set_index("grade")
        out = out.set_index("grade")
        for col in base.columns:  # 파일에 없는 값만 base로 채운다 (family, aim_*, rbar_min 등)
            if col not in out:
                out[col] = base[col].reindex(out.index)
            else:
                out[col] = out[col].fillna(base[col].reindex(out.index))
        out = out.reset_index()
    return out
