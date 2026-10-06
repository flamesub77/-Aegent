"""코일 단건 분석 (prd_v2 R3): 시생산·클레임 코일을 같은 조건 양산 실적과 비교한다."""
import re

import numpy as np
import pandas as pd

from tools import analysis as A
from tools.datasource import get_source
from tools.domain import FACTORS, PROP_DECIMALS, PROP_UNIT, STD_COLUMN, factor_label, factor_unit

ID_TYPES = {"coil_no": "냉연코일번호", "hot_coil_no": "열연코일번호", "slab_no": "슬라브번호", "heat_no": "히트번호"}
PROCESS_ORDER = ["제강", "연주", "열연", "산세", "냉연", "소둔", "도금", "조질"]
MIN_BASE = 30
MATERIAL_PROPS = ["YS", "TS", "EL", "BH", "rbar", "n_value", "dr"]


def _robust(s: pd.Series):
    """중앙값과 MAD 기반 표준편차. 양산 기준에 이상 기간 코일이 섞여도 흔들리지 않게 한다."""
    s = s.dropna()
    med = s.median()
    mad = 1.4826 * (s - med).abs().median()
    return med, (mad if mad > 0 else s.std())


def parse_ids(text) -> list[str]:
    """쉼표·줄바꿈·공백·탭으로 구분된 번호 목록 (엑셀 한 열 붙여넣기 포함)."""
    if isinstance(text, (list, tuple)):
        text = "\n".join(map(str, text))
    return list(dict.fromkeys(t for t in re.split(r"[\s,;]+", str(text).strip()) if t))


def find_coils(ids, id_type: str = "coil_no") -> dict:
    """번호로 냉연코일을 찾는다. 슬라브·열연·히트번호면 딸린 냉연코일을 모두 펼친다."""
    df = get_source().coils
    ids = parse_ids(ids)
    if id_type not in ID_TYPES:
        return {"error": f"번호 종류는 {list(ID_TYPES)} 중 하나"}
    if id_type not in df.columns:
        return {"error": f"데이터에 {ID_TYPES[id_type]}({id_type}) 컬럼이 없습니다.", "found": [], "missing": ids}
    col = df[id_type].astype(str)
    hit = df[col.isin(ids)]
    missing = [i for i in ids if i not in set(col)]
    suggestions = {}
    for i in missing:
        cands = col[col.str.contains(re.escape(i), case=False, na=False)].unique()[:5].tolist()
        if cands:
            suggestions[i] = cands
    lineage_cols = [c for c in ("slab_no", "hot_coil_no", "coil_no", "heat_no", "grade", "line", "prod_date",
                                "thk", "trial_flag") if c in df.columns]
    return {"id_type": id_type, "found": hit["coil_no"].tolist(), "missing": missing, "suggestions": suggestions,
            "lineage": hit[lineage_cols].sort_values([c for c in ("slab_no", "hot_coil_no", "coil_no") if c in hit])
            .to_dict("records")}


def _baseline(df: pd.DataFrame, coil: pd.Series, exclude: set, months: int, same_line: bool, same_thk: bool):
    """양산 비교 기준. 30개 미만이면 두께 → 라인 → 기간 순으로 조건을 넓힌다."""
    base = df[(df["grade"] == coil["grade"]) & ~df["coil_no"].isin(exclude)]
    if "trial_flag" in base:
        base = base[base["trial_flag"].fillna("N") != "Y"]
    date = pd.Timestamp(coil["prod_date"])
    start = (date - pd.DateOffset(months=months)).strftime("%Y-%m-%d")
    conds = {"강종": coil["grade"], "기간": f"{start} ~ {coil['prod_date']}"}
    use_line = same_line and "line" in base
    use_thk = same_thk and "thk_band" in base
    use_period = True
    widened = []

    def pick():
        b = base
        if use_period:
            b = b[(b["prod_date"] >= start) & (b["prod_date"] <= coil["prod_date"])]
        if use_line:
            b = b[b["line"] == coil["line"]]
        if use_thk:
            b = b[b["thk_band"] == coil["thk_band"]]
        return b

    b = pick()
    for step in ("thk", "line", "period"):
        if len(b) >= MIN_BASE:
            break
        if step == "thk" and use_thk:
            use_thk, _ = False, widened.append("두께 구간")
        elif step == "line" and use_line:
            use_line, _ = False, widened.append("라인")
        elif step == "period":
            use_period, _ = False, widened.append("기간(전체로)")
        b = pick()
    if use_line:
        conds["라인"] = coil["line"]
    if use_thk:
        conds["두께 구간"] = coil["thk_band"]
    if not use_period:
        conds["기간"] = "전체"
    return b, conds, widened


def _material_rows(coil, base, spec: dict) -> list[dict]:
    rows = []
    for p in MATERIAL_PROPS:
        if p not in base.columns or pd.isna(coil.get(p)) or base[p].notna().sum() < 5:
            continue
        v, (mu, sd) = float(coil[p]), _robust(base[p])
        lo, hi = spec.get(p, (None, None))
        judge = None
        if lo is not None or hi is not None:
            judge = "미달" if lo is not None and v < lo else "초과" if hi is not None and v > hi else "합격"
        nd = PROP_DECIMALS.get(p, 1)
        rows.append({"prop": p, "unit": PROP_UNIT[p], "value": round(v, nd), "mass_median": round(mu, nd),
                     "mass_std": round(sd, nd + 1), "z": round((v - mu) / sd, 2) if sd else None,
                     "percentile": round(100 * (base[p] < v).mean(), 1), "spec": {"min": lo, "max": hi},
                     "judge": judge})
    return rows


def _factor_rows(coil, base, family, key_prop, key_diff, grade_row) -> list[dict]:
    rows = []
    for f in A.available_factors(base):
        if pd.isna(coil.get(f)) or base[f].notna().sum() < 5:
            continue
        v, (mu, sd) = float(coil[f]), _robust(base[f])
        z = (v - mu) / sd if sd else None
        std_val = grade_row.get(STD_COLUMN.get(f, ""), None)
        std_val = None if std_val is None or std_val != std_val else float(std_val)
        out_std = bool(std_val is not None and sd and abs(v - std_val) > 2 * sd)
        mech = A._mechanism(family, f, key_prop, v - mu, key_diff) if key_prop else None
        rows.append({"factor": f, "label": factor_label(f), "unit": factor_unit(f), "process": FACTORS[f][2],
                     "value": round(v, 4), "mass_median": round(mu, 4), "mass_std": round(sd, 4),
                     "z": round(z, 2) if z is not None else None, "standard": std_val,
                     "out_of_standard": out_std, "mechanism": mech})
    rows.sort(key=lambda r: -abs(r["z"] or 0))
    return rows


def analyze_coil(ids, id_type: str = "coil_no", months: int = 3, same_line: bool = True,
                 same_thk: bool = True) -> dict:
    """코일별 재질 위치(양산 대비 z·백분위)와 공정 차이, 여러 코일이면 공통으로 벗어난 인자.

    z는 양산 중앙값·MAD(이상치에 강한 표준편차) 기준이다.
    """
    found = find_coils(ids, id_type)
    if "error" in found:
        return found
    src = get_source()
    df = src.coils
    targets = df[df["coil_no"].isin(found["found"])]
    exclude = set(targets["coil_no"])
    results = []
    for _, coil in targets.iterrows():
        base, conds, widened = _baseline(df, coil, exclude, months, same_line, same_thk)
        spec = src.spec(coil["grade"])
        materials = _material_rows(coil, base, spec)
        key = max(materials, key=lambda m: abs(m["z"] or 0), default=None)
        key_prop = key["prop"] if key and key["z"] and abs(key["z"]) >= 1 else None
        key_diff = (key["value"] - key["mass_median"]) if key_prop else None
        grade_row = src.grade(coil["grade"])
        factors = _factor_rows(coil, base, grade_row.get("family"), key_prop, key_diff, grade_row)
        results.append({"coil_no": coil["coil_no"], "grade": coil["grade"], "line": coil["line"],
                        "prod_date": coil["prod_date"], "thk": coil.get("thk"),
                        "trial": coil.get("trial_flag") == "Y", "n_baseline": len(base),
                        "baseline_ids": base["coil_no"].tolist(),
                        "baseline_conditions": conds, "widened": widened, "key_property": key_prop,
                        "materials": materials, "factors": factors,
                        "warnings": ([{"code": "widened", "text": f"비교할 양산 코일이 적어 {', '.join(widened)} 조건을 넓혔습니다."}]
                                     if widened else [])
                                    + ([{"code": "small_group", "n": len(base)}] if len(base) < MIN_BASE else [])})
    return {"id_type": id_type, "query": parse_ids(ids), "missing": found["missing"],
            "suggestions": found["suggestions"], "lineage": found["lineage"], "coils": results,
            "common": _common(results)}


def _common(results: list[dict]) -> list[dict]:
    """여러 코일에서 같은 방향으로 |z| ≥ 1.5인 인자."""
    if len(results) < 2:
        return []
    by = {}
    for r in results:
        for f in r["factors"]:
            if f["z"] is not None and abs(f["z"]) >= 1.5:
                by.setdefault(f["factor"], []).append(np.sign(f["z"]))
    out = []
    for f, signs in by.items():
        same = max(signs.count(1.0), signs.count(-1.0))
        if same >= max(2, len(results) / 2):
            out.append({"factor": f, "label": factor_label(f), "coils": same, "of": len(results),
                        "direction": "+" if signs.count(1.0) >= signs.count(-1.0) else "-"})
    return sorted(out, key=lambda x: -x["coils"])


def compact(result: dict, top: int = 6) -> dict:
    """에이전트 도구용 요약 (코일별 상위 인자만)."""
    out = {k: v for k, v in result.items() if k not in ("coils", "lineage")}
    out["lineage"] = result.get("lineage", [])[:20]
    out["coils"] = [{**{k: v for k, v in c.items() if k not in ("factors", "baseline_ids")},
                     "top_factors": c["factors"][:top]}
                    for c in result.get("coils", [])[:10]]
    return out
