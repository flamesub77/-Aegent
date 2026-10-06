"""회사 데이터 업로드 (prd_v2 R2): 파일 읽기 → 컬럼 매핑 → 검증 → DataSource.

업로드 파일은 메모리에서만 처리하고 디스크에 저장하지 않는다. 매핑 설정(JSON)만 mappings/에 저장한다.
"""
import io
import json
import re
from pathlib import Path

import pandas as pd

import config
from tools import db
from tools.datasource import REQUIRED, DataSource
from tools.domain import FACTORS

ELEMENTS = ["C", "Mn", "Si", "P", "S", "N", "Al", "Ti", "Nb", "B"]

# 표준 컬럼: (설명, 단위, 종류) — 양식 다운로드와 매핑 화면에 쓴다
STANDARD = {
    "coil_no": ("냉연코일번호", "-", "text"), "hot_coil_no": ("열연코일번호", "-", "text"),
    "slab_no": ("슬라브번호", "-", "text"), "heat_no": ("히트번호", "-", "text"),
    "prod_date": ("생산일(소둔)", "yyyy-mm-dd", "date"), "grade": ("강종코드", "-", "text"),
    "line": ("소둔라인 (CAL / CGL_GA)", "-", "text"), "trial_flag": ("시생산 여부 (Y/N)", "-", "text"),
    **{el: (f"{el} 성분", "wt%", "num") for el in ELEMENTS},
    **{f: (v[0], v[1], "num") for f, v in FACTORS.items() if f not in ELEMENTS},
    "thk": ("제품 두께", "mm", "num"), "width": ("제품 폭", "mm", "num"),
    "coil_pos": ("시험 위치 (T/M/B)", "-", "text"),
    "YS": ("항복강도", "MPa", "num"), "TS": ("인장강도", "MPa", "num"), "EL": ("연신율", "%", "num"),
    "YR": ("항복비", "-", "num"), "BH": ("소부경화량", "MPa", "num"),
    "r0": ("r값 0°", "-", "num"), "r45": ("r값 45°", "-", "num"), "r90": ("r값 90°", "-", "num"),
    "n_value": ("n값 (가공경화지수)", "-", "num"),
    "defect_type": ("표면결함 유형 (없음/슬리버/...)", "-", "text"), "defect_grade": ("결함 등급", "-", "text"),
    "judge": ("판정 (합격 또는 사유)", "-", "text"),
}
MATERIALS = ["YS", "TS", "EL", "BH", "r0", "r45", "r90", "n_value"]

# 사내 표기 → 표준 컬럼 (정규화한 이름으로 비교: 소문자, 공백·기호 제거)
ALIASES = {
    "coil_no": ["코일번호", "냉연코일번호", "냉연코일no", "코일no", "coilno", "coil", "냉연번호", "제품번호"],
    "hot_coil_no": ["열연코일번호", "열연코일no", "열연번호", "hotcoilno", "hrcoilno", "모코일번호"],
    "slab_no": ["슬라브번호", "슬라브no", "slabno", "slab"],
    "heat_no": ["히트번호", "히트no", "heatno", "heat", "용강번호", "차지번호", "charge"],
    "prod_date": ["생산일", "생산일자", "소둔일", "소둔일자", "작업일", "작업일자", "date", "proddate", "생산일시"],
    "grade": ["강종", "강종코드", "강종명", "grade", "steelgrade", "규격"],
    "line": ["라인", "소둔라인", "line", "공장", "설비"],
    "trial_flag": ["시생산", "시생산여부", "시작품", "trial", "trialflag", "생산구분"],
    "cast_speed": ["주조속도", "연주속도", "castspeed"], "superheat": ["과열도", "superheat"],
    "SRT": ["재가열온도", "추출온도", "srt", "sdt"], "FDT": ["마무리온도", "사상출측온도", "fdt", "fet"],
    "CT": ["권취온도", "ct", "coilingtemp"], "descale_press": ["디스케일링압력", "디스케일압력"],
    "hot_thk": ["열연두께", "모재두께", "hotthk"], "pickle_speed": ["산세속도"], "hcl_conc": ["염산농도", "hcl농도", "hcl"],
    "RED": ["압하율", "냉간압하율", "냉연압하율", "red", "reduction"],
    "SS": ["균열온도", "소둔온도", "ss", "soaking"], "line_speed": ["라인속도", "통판속도", "소둔속도"],
    "OA": ["과시효온도", "oa", "과시효"], "pot_temp": ["도금욕온도", "포트온도", "pot"],
    "GA_temp": ["합금화온도", "ga온도", "gatemp"], "SPM": ["spm", "spm연신율", "조질연신율", "skp", "skinpass"],
    "thk": ["두께", "제품두께", "thk", "thickness"], "width": ["폭", "제품폭", "width"],
    "coil_pos": ["시험위치", "채취위치", "시편위치", "coilpos"],
    "YS": ["항복강도", "ys", "yp", "항복점"], "TS": ["인장강도", "ts"], "EL": ["연신율", "el", "elongation"],
    "YR": ["항복비", "yr"], "BH": ["bh", "소부경화", "소부경화량"],
    "r0": ["r0", "r값0", "r0도"], "r45": ["r45", "r값45", "r45도"], "r90": ["r90", "r값90", "r90도"],
    "n_value": ["n값", "n", "nvalue", "가공경화지수"],
    "defect_type": ["결함", "결함유형", "표면결함", "defect", "defecttype"], "defect_grade": ["결함등급", "defectgrade"],
    "judge": ["판정", "합부", "합부판정", "judge"],
}
for el in ELEMENTS:
    ALIASES[el] = [el.lower()]


def _norm(name: str) -> str:
    return re.sub(r"[\s_\-\(\)\[\]/.·]", "", str(name)).lower()


_ALIAS_INDEX = {_norm(a): std for std, names in ALIASES.items() for a in names + [std]}


# ---------------------------------------------------------------------------
def read_file(data: bytes, filename: str, sheet: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    """CSV(UTF-8/CP949 자동) 또는 XLSX를 읽는다. 반환: (DataFrame, 시트 목록)."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xls")):
        xls = pd.ExcelFile(io.BytesIO(data))
        sheets = xls.sheet_names
        return xls.parse(sheet or sheets[0]), sheets
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc), []
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV 인코딩을 알 수 없습니다 (UTF-8, CP949만 지원).")


def suggest_mapping(columns) -> dict:
    """원본 컬럼 → 표준 컬럼 제안. 못 찾으면 None. 한 표준 컬럼에는 하나만."""
    out, used = {}, set()
    for col in columns:
        std = _ALIAS_INDEX.get(_norm(col))
        if std and std not in used:
            out[col], _ = std, used.add(std)
        else:
            out[col] = None
    return out


def apply_mapping(df: pd.DataFrame, mapping: dict, ppm_columns=()) -> pd.DataFrame:
    """매핑된 컬럼만 표준 이름으로 남긴다. ppm_columns의 성분은 wt%로 바꾼다."""
    pairs = {src: std for src, std in mapping.items() if std}
    out = df[list(pairs)].rename(columns=pairs).copy()
    for col, (_, _, kind) in STANDARD.items():
        if col not in out:
            continue
        if kind == "num":
            out[col] = pd.to_numeric(out[col], errors="coerce")
        elif kind == "text":
            out[col] = out[col].astype("string").str.strip()
    for col in ppm_columns:
        if col in out:
            out[col] = out[col] / 10000
    if "line" in out:
        out["line"] = out["line"].replace({"CGL": "CGL_GA", "GA": "CGL_GA"})
    if "trial_flag" in out:
        out["trial_flag"] = out["trial_flag"].map(
            lambda v: "Y" if str(v).strip().upper() in ("Y", "1", "TRUE", "시생산", "시작품", "O") else "N")
    return out


def validate(df: pd.DataFrame, raw: pd.DataFrame | None = None, mapping: dict | None = None,
             grades: pd.DataFrame | None = None) -> dict:
    """문제 항목을 건수·예시와 함께. raw/mapping을 주면 숫자 변환 실패도 원본 기준으로 센다."""
    issues, bad_rows = [], pd.Series(False, index=df.index)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        issues.append({"code": "missing_required", "level": "error", "count": len(missing),
                       "text": f"필수 컬럼이 매핑되지 않았습니다: {', '.join(STANDARD[c][0] for c in missing)}"})
    if not any(c in df.columns for c in MATERIALS):
        issues.append({"code": "no_material", "level": "error", "count": 1,
                       "text": "재질 컬럼(YS·TS·EL·r값·n값 등)이 하나도 없습니다."})
    if "prod_date" in df.columns:
        bad = pd.to_datetime(df["prod_date"], errors="coerce").isna()
        if bad.any():
            bad_rows |= bad
            issues.append({"code": "bad_date", "level": "warn", "count": int(bad.sum()),
                           "text": "날짜를 읽을 수 없는 행", "examples": df.loc[bad, "prod_date"].astype(str).head(3).tolist()})
    if raw is not None and mapping:
        for src, std in mapping.items():
            if std and STANDARD.get(std, ("", "", ""))[2] == "num" and std in df.columns:
                was = raw[src].notna() & raw[src].astype(str).str.strip().ne("")
                bad = was & df[std].isna()
                if bad.any():
                    issues.append({"code": "non_numeric", "level": "warn", "count": int(bad.sum()),
                                   "text": f"{std}({src}) 숫자가 아닌 값", "examples": raw.loc[bad, src].astype(str).head(3).tolist()})
    for col in ("coil_no", "grade", "line"):
        if col in df.columns:
            bad = df[col].isna() | (df[col].astype(str).str.strip() == "")
            if bad.any():
                bad_rows |= bad
                issues.append({"code": f"empty_{col}", "level": "warn", "count": int(bad.sum()),
                               "text": f"{STANDARD[col][0]}이 비어 있는 행"})
    if "coil_no" in df.columns:
        dup = df["coil_no"].duplicated(keep="first") & df["coil_no"].notna()
        if dup.any():
            bad_rows |= dup
            issues.append({"code": "duplicate", "level": "warn", "count": int(dup.sum()),
                           "text": "중복된 코일번호 (첫 행만 남김)", "examples": df.loc[dup, "coil_no"].astype(str).head(3).tolist()})
    if grades is not None and "grade" in df.columns:
        no_spec = sorted(set(df["grade"].dropna()) - set(grades["grade"]))
        if no_spec:
            issues.append({"code": "no_spec", "level": "info", "count": len(no_spec),
                           "text": "스펙이 없는 강종 (분포만 표시, 스펙 판정 안 함)", "examples": no_spec[:5]})
    return {"rows": len(df), "bad_rows": int(bad_rows.sum()), "bad_mask": bad_rows,
            "ok": not any(i["level"] == "error" for i in issues), "issues": issues}


def build_source(df: pd.DataFrame, name: str, grades: pd.DataFrame | None = None,
                 use_sample_spec: bool = True, drop_bad: pd.Series | None = None) -> DataSource:
    """검증한 DataFrame으로 DataSource를 만든다. grades가 없으면 샘플 스펙(같은 강종 코드만) 사용."""
    if drop_bad is not None:
        df = df[~drop_bad]
    df = df.drop_duplicates("coil_no", keep="first")
    if grades is None:
        grades = db.load_grade_master() if use_sample_spec else pd.DataFrame(columns=["grade"])
        grades = grades[grades["grade"].isin(df["grade"].unique())]
    return DataSource(df, grades, name, "upload")


def read_grades(data: bytes, filename: str) -> pd.DataFrame:
    g, _ = read_file(data, filename)
    if "grade" not in g.columns:
        raise ValueError("강종 스펙 파일에 grade 컬럼이 필요합니다 (grade_master.csv 형식).")
    return g


# ---------------------------------------------------------------------------
def template_excel() -> bytes:
    """빈 데이터 시트 + 컬럼 정의 시트."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(columns=list(STANDARD)).to_excel(w, sheet_name="coil", index=False)
        pd.DataFrame([{"컬럼": c, "설명": d, "단위": u, "필수": "O" if c in REQUIRED else "",
                       "다른 이름 예시": ", ".join(ALIASES.get(c, [])[:3])}
                      for c, (d, u, _) in STANDARD.items()]).to_excel(w, sheet_name="컬럼 정의", index=False)
        db.load_grade_master().head(0).to_excel(w, sheet_name="grade_master", index=False)
    return buf.getvalue()


MAPPING_DIR = config.BASE_DIR / "mappings"


def save_mapping(name: str, mapping: dict, ppm_columns=()) -> Path:
    MAPPING_DIR.mkdir(exist_ok=True)
    path = MAPPING_DIR / f"{re.sub(r'[^0-9A-Za-z가-힣_-]', '_', name)}.json"
    path.write_text(json.dumps({"mapping": mapping, "ppm_columns": list(ppm_columns)}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def list_mappings() -> list[str]:
    return sorted(p.stem for p in MAPPING_DIR.glob("*.json")) if MAPPING_DIR.exists() else []


def load_mapping(name: str) -> dict:
    return json.loads((MAPPING_DIR / f"{name}.json").read_text(encoding="utf-8"))
