"""분석 엔진: 대시보드와 에이전트 도구가 함께 쓰는 계산 함수.

모든 수치는 여기서 계산하고, LLM은 결과를 해석만 한다.
"""

import numpy as np
import pandas as pd
from scipy import stats

from tools.datasource import get_source
from tools.ranking import rerank
from tools.domain import (DEFECTS, FACTORS, MECHANISMS, PROP_DECIMALS, PROP_UNIT, PROPS, STD_COLUMN,
                          factor_label, factor_unit)

JUDGE_SIGMA = 1.0      # knowledge_base 5장: 평균 이동 1σ 이상이면 상향/하향 분포
TREND_SIGMA = 0.5      # 참고용 '경향' 표시
MIN_N = 30             # 이보다 적으면 결론 대신 경고
CONFOUND_PP = 15.0     # 두 군의 구성비 차이가 이 %p 이상이면 교란 경고


# ---------------------------------------------------------------------------
# 데이터
# ---------------------------------------------------------------------------
def all_coils() -> pd.DataFrame:
    return get_source().coils.copy()


def grade_info(grade: str) -> dict:
    return dict(get_source().grade(grade))


def spec(grade: str) -> dict:
    """재질별 (하한, 상한). 데이터에 있는 재질만, 스펙이 없으면 (None, None)."""
    return get_source().spec(grade)


def available_factors(df: pd.DataFrame) -> list[str]:
    """데이터에 실제로 값이 있는 공정인자만 (업로드 데이터는 일부 인자가 없을 수 있다).

    "지시 대비" 인자(CT_dev 등)는 지시값이 한 가지뿐이면 실적 인자(CT)와 같은 정보라 뺀다.
    """
    out = []
    for f in FACTORS:
        if f not in df.columns or not df[f].notna().any():
            continue
        if f.endswith("_dev") and f"{f[:-4]}_aim" in df.columns and df[f"{f[:-4]}_aim"].nunique() <= 1:
            continue
        out.append(f)
    return out


def filter_coils(grade=None, line=None, thk_min=None, thk_max=None, coil_pos=None,
                 df: pd.DataFrame | None = None, thk_band=None, where: dict | None = None) -> pd.DataFrame:
    """where: {컬럼: [허용 값]} (규격약호·출강목표·용도코드·공장 등. 한 컬럼 안은 OR, 컬럼끼리는 AND).
    where["__any__"] = {컬럼: [값]}: 컬럼끼리 OR (prd_v4 L1 압연·정정 규격약호를 함께 고를 때)."""
    df = all_coils() if df is None else df
    for col, values in (where or {}).items():
        if col == "__any__":
            masks = [df[c].isin(list(v)) for c, v in values.items() if v and c in df.columns]
            if masks:
                hit = masks[0]
                for m in masks[1:]:
                    hit = hit | m
                df = df[hit]
        elif values and col in df.columns:
            df = df[df[col].isin(list(values))]
    if grade:
        df = df[df["grade"] == grade]
    if line:
        df = df[df["line"] == line]
    if thk_min is not None:
        df = df[df["thk"] >= thk_min]
    if thk_max is not None:
        df = df[df["thk"] <= thk_max]
    if coil_pos:
        df = df[df["coil_pos"] == coil_pos]
    if thk_band:
        df = df[df["thk_band"] == thk_band]
    return df


def split_period(df, start=None, end=None, base_start=None, base_end=None):
    """대상 기간과 기준 기간으로 나눈다. 기준 기간을 안 주면 대상 외 나머지 기간."""
    in_target = pd.Series(True, index=df.index)
    if start:
        in_target &= df["prod_date"] >= start
    if end:
        in_target &= df["prod_date"] <= end
    target = df[in_target]
    if base_start or base_end:
        in_base = pd.Series(True, index=df.index)
        if base_start:
            in_base &= df["prod_date"] >= base_start
        if base_end:
            in_base &= df["prod_date"] <= base_end
        baseline = df[in_base & ~in_target]
    else:
        baseline = df[~in_target]
    return target, baseline


# ---------------------------------------------------------------------------
# 통계
# ---------------------------------------------------------------------------
def _r(v, n=2):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), n)


def dist_stats(s: pd.Series, lo=None, hi=None, nd=1) -> dict:
    missing = int(s.isna().sum())  # 결측은 빼고 계산하고 개수만 알린다 (prd_v3 D3)
    s = s.dropna()
    n = len(s)
    if n == 0:
        return {"n": 0, "missing": missing}
    mean, std = s.mean(), s.std(ddof=1) if n > 1 else 0.0
    low = int((s < lo).sum()) if lo is not None else 0
    high = int((s > hi).sum()) if hi is not None else 0
    cpk = None
    if std and std > 0:
        cands = []
        if lo is not None:
            cands.append((mean - lo) / (3 * std))
        if hi is not None:
            cands.append((hi - mean) / (3 * std))
        cpk = min(cands) if cands else None
    has_spec = lo is not None or hi is not None
    return {"n": n, "missing": missing, "mean": _r(mean, nd), "std": _r(std, nd + 1), "min": _r(s.min(), nd),
            "max": _r(s.max(), nd),
            "spec_rate": _r(100 * (n - low - high) / n, 1) if has_spec else None,
            "below_spec": low, "above_spec": high, "cpk": _r(cpk, 2)}


def _judge(z):
    if z is None:
        return "비교 불가"
    if z >= JUDGE_SIGMA:
        return "상향 분포"
    if z <= -JUDGE_SIGMA:
        return "하향 분포"
    if z >= TREND_SIGMA:
        return "상향 경향"
    if z <= -TREND_SIGMA:
        return "하향 경향"
    return "정상"


def diagnose(grade, line=None, start=None, end=None, base_start=None, base_end=None,
             props=None, thk_min=None, thk_max=None, coil_pos=None, thk_band=None, where=None) -> dict:
    """대상 기간 재질 분포를 기준 기간과 비교한다."""
    sp = spec(grade)
    props = [p for p in (props or PROPS) if p in sp]
    df = filter_coils(grade, line, thk_min, thk_max, coil_pos, thk_band=thk_band, where=where)
    target, baseline = split_period(df, start, end, base_start, base_end)
    out = {"grade": grade, "line": line or "전체", "period": [start, end],
           "baseline": [base_start, base_end] if (base_start or base_end) else "대상 외 나머지 기간",
           "n_target": len(target), "n_baseline": len(baseline), "properties": {}, "warnings": []}
    if len(target) < MIN_N:
        out["warnings"].append({"code": "small_target", "n": len(target)})
    for p in props:
        lo, hi = sp[p]
        nd = PROP_DECIMALS.get(p, 1)
        t = dist_stats(target[p], lo, hi, nd)
        b = dist_stats(baseline[p], lo, hi, nd) if len(baseline) else {"n": 0}
        shift = z = None
        if t.get("n") and b.get("n") and b.get("std"):
            shift = t["mean"] - b["mean"]
            z = shift / b["std"]
        out["properties"][p] = {"spec": {"min": lo, "max": hi}, "unit": PROP_UNIT[p], "target": t,
                                "baseline": b, "shift": _r(shift, nd), "shift_sigma": _r(z, 2),
                                "judgement": _judge(z)}
    return out


def _cohen_d(a: pd.Series, b: pd.Series):
    a, b = a.dropna(), b.dropna()
    if len(a) < 3 or len(b) < 3:
        return None
    sp = np.sqrt(((len(a) - 1) * a.var() + (len(b) - 1) * b.var()) / (len(a) + len(b) - 2))
    return None if not sp or np.isnan(sp) else (a.mean() - b.mean()) / sp


def _composition(g1: pd.DataFrame, g2: pd.DataFrame, col: str) -> dict:
    c1 = g1[col].value_counts(normalize=True) * 100
    c2 = g2[col].value_counts(normalize=True) * 100
    keys = sorted(set(c1.index) | set(c2.index))
    rows = {k: {"group": _r(c1.get(k, 0), 1), "reference": _r(c2.get(k, 0), 1)} for k in keys}
    max_gap = max((abs(v["group"] - v["reference"]) for v in rows.values()), default=0)
    return {"share_pct": rows, "max_gap_pp": _r(max_gap, 1), "warning": max_gap >= CONFOUND_PP}


def _mechanism(family, factor: str, prop: str, factor_diff, prop_shift):
    entry = MECHANISMS.get(family or "", {}).get(factor)
    if not entry or prop not in entry["effect"]:
        return {"status": "지식베이스 근거 없음", "text": None, "easy": None, "expert": None, "source": None}
    sign = entry["effect"][prop]
    if factor_diff is None or prop_shift is None or factor_diff == 0 or prop_shift == 0:
        status = "판단 불가"
    else:
        status = "일치" if np.sign(factor_diff) * sign == np.sign(prop_shift) else "불일치"
    return {"status": status, "text": entry["text"], "easy": entry["easy"], "expert": entry["expert"],
            "source": f"knowledge_base.md {entry['sec']}"}


def comparison_groups(df, grade, prop, start=None, end=None, base_start=None, base_end=None, side="auto",
                      sigma: float = 1.0):
    """비교할 두 그룹을 정한다. 반환: (mode, side, group, ref).

    mode="period": 기간이 주어지고 나머지 기간 코일이 충분하면 이 기간 코일 vs 나머지 기간 코일
    mode="outlier": 아니면 문제 코일(스펙 또는 평균±sigma·σ 밖, 기본 1.0σ) vs 정상 코일. 화면 용어는 tools/terms.py
    """
    target, baseline = split_period(df, start, end, base_start, base_end)
    if (start or end) and len(baseline) >= MIN_N:
        return "period", None, target, baseline
    lo, hi = spec(grade).get(prop, (None, None))
    mean, std = df[prop].mean(), df[prop].std() * float(sigma)
    low_mask = (df[prop] < mean - std) | ((df[prop] < lo) if lo is not None else False)
    high_mask = (df[prop] > mean + std) | ((df[prop] > hi) if hi is not None else False)
    if side == "auto":  # 스펙 이탈이 더 많은 쪽, 같으면 1σ 이탈이 더 많은 쪽
        n_lo = int((df[prop] < lo).sum()) if lo is not None else 0
        n_hi = int((df[prop] > hi).sum()) if hi is not None else 0
        if n_lo == n_hi:
            n_lo, n_hi = int(low_mask.sum()), int(high_mask.sum())
        side = "low" if n_lo >= n_hi else "high"
    mask = low_mask if side == "low" else high_mask if side == "high" else (low_mask | high_mask)
    return "outlier", side, df[mask], df[~mask]


def compare(grade, prop, line=None, start=None, end=None, base_start=None, base_end=None,
            side="auto", thk_min=None, thk_max=None, coil_pos=None, top_n=10, thk_band=None, where=None,
            model: str = "effect", sigma: float = 1.0) -> dict:
    """문제 코일과 정상 코일의 인자를 비교해 원인 가능성 순위를 매긴다. model: tools/ranking.MODELS."""
    df = filter_coils(grade, line, thk_min, thk_max, coil_pos, thk_band=thk_band, where=where)
    family = grade_info(grade)["family"]
    mode, side, group, ref = comparison_groups(df, grade, prop, start, end, base_start, base_end, side, sigma)

    prop_shift = group[prop].mean() - ref[prop].mean() if len(group) and len(ref) else None
    both = pd.concat([group, ref])
    std_row = grade_info(grade)
    ranking = []
    insufficient = []  # 값이 있는 코일이 10개 미만이라 순위에서 뺀 인자 (prd_v3 D3)
    for f in available_factors(both):
        if both[f].notna().sum() < 10 or group[f].notna().sum() < 2 or ref[f].notna().sum() < 2:
            insufficient.append(f)
            continue
        if both[f].std() == 0:
            continue
        d = _cohen_d(group[f], ref[f])
        if d is None:
            continue
        g_mean, r_mean = group[f].mean(), ref[f].mean()
        valid = both[[f, prop]].dropna()
        r = valid[f].corr(valid[prop]) if len(valid) > 5 else None
        p = stats.ttest_ind(group[f].dropna(), ref[f].dropna(), equal_var=False).pvalue
        std_val = std_row.get(STD_COLUMN.get(f, ""), None)
        std_val = None if std_val is None or std_val != std_val else std_val
        ranking.append({
            "factor": f, "label": factor_label(f), "unit": factor_unit(f), "process": FACTORS[f][2],
            "group_mean": _r(g_mean, 4), "reference_mean": _r(r_mean, 4), "diff": _r(g_mean - r_mean, 4),
            "effect_size": _r(d, 2), "corr_with_prop": _r(r, 2), "p_value": float(f"{p:.2g}"),
            "standard": std_val, "group_vs_standard": _r(g_mean - std_val, 4) if std_val is not None else None,
            "mechanism": _mechanism(family, f, prop, g_mean - r_mean, prop_shift),
        })
    ranking, model_used, model_note = rerank(ranking, both, prop, model)

    confounders = {c: _composition(group, ref, c) for c in ("thk_band", "line", "coil_pos") if c in df.columns}
    # 경고는 코드로 두고 문장은 tools/narrative.py가 문체별로 만든다
    warnings = [{"code": "confounder", "column": c, "gap_pp": v["max_gap_pp"]}
                for c, v in confounders.items() if v["warning"]]
    if len(group) < MIN_N:
        warnings.append({"code": "small_group", "n": len(group)})
    return {"grade": grade, "family": family, "property": prop, "mode": mode,
            "side": side, "line": line or "전체", "period": [start, end],
            "n_group": len(group), "n_reference": len(ref),
            "prop_group_mean": _r(group[prop].mean(), PROP_DECIMALS.get(prop, 1)),
            "prop_reference_mean": _r(ref[prop].mean(), PROP_DECIMALS.get(prop, 1)),
            "prop_shift": _r(prop_shift, PROP_DECIMALS.get(prop, 1)), "ranking": ranking[:top_n], "all_factors": ranking,
            "confounders": confounders, "warnings": warnings, "insufficient": insufficient,
            "model": model_used, "model_note": model_note}


def defect_trace(defect_type, grade=None, line=None, start=None, end=None, top_n=8, where=None,
                 thk_min=None, thk_max=None, coil_pos=None) -> dict:
    """결함 발생률을 기간별로 비교하고, 결함 코일과 정상 코일의 인자를 비교한다."""
    if defect_type not in DEFECTS:
        return {"error": f"알 수 없는 결함 유형: {defect_type}", "available": list(DEFECTS)}
    df = filter_coils(grade, line, thk_min, thk_max, coil_pos, where=where)
    if "defect_type" not in df.columns:
        return {"error": "데이터에 표면결함(defect_type) 컬럼이 없습니다."}
    df = df.assign(defect_type=df["defect_type"].fillna("없음"))
    target, baseline = split_period(df, start, end)
    is_def = df["defect_type"] == defect_type

    def rate(x):
        return _r(100 * (x["defect_type"] == defect_type).mean(), 2) if len(x) else None

    monthly = (df.assign(hit=is_def).groupby("month")["hit"].mean() * 100).round(2).to_dict()
    related, process, cause = DEFECTS[defect_type]
    if (start or end) and len(baseline) >= MIN_N:
        # 기간 전체에 공정 변화가 걸렸으면 기간 안의 결함/정상 비교로는 차이가 안 보인다
        mode, hit, clean = "period", target, baseline
    else:
        mode = "defect"
        hit, clean = df[is_def], df[~is_def]
    rows = []
    for f in available_factors(df):
        d = _cohen_d(hit[f], clean[f]) if len(hit) >= 3 else None
        if d is None:
            continue
        sign = related.get(f)
        rows.append({"factor": f, "label": factor_label(f), "unit": factor_unit(f),
                     "defect_mean": _r(hit[f].mean(), 4), "normal_mean": _r(clean[f].mean(), 4),
                     "effect_size": _r(d, 2), "kb_related": sign is not None,
                     "kb_consistent": None if sign is None else bool(np.sign(d) == sign)})
    rows.sort(key=lambda x: -abs(x["effect_size"]))
    by_grade = (df.assign(hit=is_def).groupby("grade")["hit"].mean() * 100).round(2).to_dict()
    return {"defect_type": defect_type, "grade": grade or "전체", "line": line or "전체",
            "period": [start, end], "mode": mode, "rate_target_pct": rate(target), "rate_baseline_pct": rate(baseline),
            "count_target": int((target["defect_type"] == defect_type).sum()), "n_target": len(target),
            "monthly_rate_pct": monthly, "rate_by_grade_pct": by_grade,
            "kb_cause": {"process": process, "cause": cause, "source": "knowledge_base.md 4장"},
            "factor_ranking": rows[:top_n]}


# ---------------------------------------------------------------------------
# 대시보드 집계
# ---------------------------------------------------------------------------
def monthly_summary(grade, prop, line=None, thk_min=None, thk_max=None, coil_pos=None) -> pd.DataFrame:
    df = filter_coils(grade, line, thk_min, thk_max, coil_pos)
    lo, hi = spec(grade).get(prop, (None, None))
    g = df.groupby("month")[prop]
    out = pd.DataFrame({"n": g.size(), "mean": g.mean(), "std": g.std()})
    out["spec_rate"] = df.groupby("month")[prop].apply(
        lambda s: 100 * (((s >= lo) if lo is not None else True) & ((s <= hi) if hi is not None else True)).mean())
    return out.reset_index()


def overview_heatmap(prop: str, line=None, where=None) -> pd.DataFrame:
    """강종 × 월 평균의 강종 전체 평균 대비 편차(σ 단위)."""
    df = filter_coils(line=line, where=where)
    rows = []
    for grade, g in df.groupby("grade"):
        if prop not in g.columns or g[prop].isna().all():
            continue
        mu, sd = g[prop].mean(), g[prop].std()
        for month, m in g.groupby("month"):
            rows.append({"grade": grade, "month": month, "z": (m[prop].mean() - mu) / sd if sd else 0,
                         "mean": m[prop].mean(), "n": len(m)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 인사이트 문장: tools/narrative.py (문체별). 기존 호출 호환용.
# ---------------------------------------------------------------------------
def insights(diag: dict, comp: dict, style: str = "stat") -> dict:
    from tools.narrative import insights as _insights
    return _insights(diag, comp, style)


def production(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """연도별 생산량 (prd_v3 U8). 반환: (연도별 [year, coils, tons, months], 연도×냉연규격 [year, grade, coils])."""
    if df.empty:
        return pd.DataFrame(columns=["year", "coils", "tons", "months"]), pd.DataFrame(columns=["year", "grade", "coils"])
    d = df.assign(year=df["prod_date"].str[:4].astype(int))
    tons = d["weight"] if "weight" in d else pd.Series(np.nan, index=d.index)
    yearly = d.assign(_w=tons).groupby("year").agg(coils=("coil_no", "size"), tons=("_w", "sum"),
                                                   months=("month", "nunique")).reset_index()
    by_grade = d.groupby(["year", "grade"]).size().rename("coils").reset_index()
    return yearly, by_grade


THK_GROUPS = [(None, 0.75, "~0.75"), (0.75, 1.0, "0.75~1.0"), (1.0, 1.4, "1.0~1.4"), (1.4, None, "1.4~")]  # mm (prd_v4 M1)


def thickness_groups(df: pd.DataFrame, prop: str, spec_lohi) -> pd.DataFrame:
    """두께 구간별 재질 통계 (prd_v4 M1): band, n, mean, std, spec_rate, cpk."""
    lo, hi = spec_lohi
    rows = []
    for a, b, label in THK_GROUPS:
        m = pd.Series(True, index=df.index)
        if a is not None:
            m &= df["thk"] > a
        if b is not None:
            m &= df["thk"] <= b
        st = dist_stats(df.loc[m, prop], lo, hi, PROP_DECIMALS.get(prop, 1))
        if st.get("n"):
            rows.append({"band": label, **{k: st.get(k) for k in ("n", "mean", "std", "spec_rate", "cpk", "missing")}})
    return pd.DataFrame(rows)


def thickness_band(thk: pd.Series) -> pd.Series:
    out = pd.Series(None, index=thk.index, dtype=object)
    for a, b, label in THK_GROUPS:
        m = thk.notna()
        if a is not None:
            m &= thk > a
        if b is not None:
            m &= thk <= b
        out[m] = label
    return out


def defect_by_grade(defect_type, line=None, start=None, end=None, min_defects=5, **sub) -> pd.DataFrame:
    """강종별 결함률·원인 1순위 (prd_v4 M4). 결함 코일이 min_defects 미만이면 원인은 "표본 부족"."""
    rows = []
    for g in sorted(filter_coils(None, line, **sub)["grade"].dropna().unique()):
        r = defect_trace(defect_type, g, line, start, end, **sub)
        if "error" in r:
            continue
        top = r["factor_ranking"][0] if r["factor_ranking"] and r["count_target"] >= min_defects else None
        rows.append({"grade": g, "rate_target_pct": r["rate_target_pct"], "rate_baseline_pct": r["rate_baseline_pct"],
                     "count_target": r["count_target"], "n_target": r["n_target"],
                     "top_factor": top["label"] if top else "표본 부족",
                     "top_diff": top["defect_mean"] - top["normal_mean"] if top else None,
                     "top_unit": top["unit"] if top else ""})
    return pd.DataFrame(rows)


def defect_grade_month(defect_type, line=None, **sub) -> pd.DataFrame:
    """강종 × 월 결함률(%) (prd_v4 M4 히트맵): grade, month, rate."""
    df = filter_coils(None, line, **sub)
    if df.empty or "defect_type" not in df:
        return pd.DataFrame(columns=["grade", "month", "rate"])
    d = df.assign(hit=df["defect_type"].fillna("없음") == defect_type)
    return d.groupby(["grade", "month"])["hit"].mean().mul(100).round(2).rename("rate").reset_index()


# ---------------------------------------------------------------------------
# prd_v5 T5: 결함분석
# ---------------------------------------------------------------------------
def defect_pareto(grade, line=None, start=None, end=None, **sub) -> pd.DataFrame:
    """선택 강종 안의 결함 유형 순위 (파레토). defect, count, rate(%), cum_pct(누적 %), base_rate(나머지 기간 %)."""
    cols = ["defect", "count", "rate", "cum_pct", "base_rate"]
    df = filter_coils(grade, line, **sub)
    if df.empty or "defect_type" not in df:
        return pd.DataFrame(columns=cols)
    target, base = split_period(df, start, end)
    if start is None and end is None:
        target, base = df, df.iloc[0:0]
    hit = target["defect_type"].fillna("없음")
    cnt = hit[hit != "없음"].value_counts()
    if cnt.empty:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame({"defect": cnt.index, "count": cnt.values.astype(int)})
    out["rate"] = (100 * out["count"] / max(len(target), 1)).round(2)
    out["cum_pct"] = (100 * out["count"].cumsum() / out["count"].sum()).round(1)
    if len(base):
        b = base["defect_type"].fillna("없음").value_counts()
        out["base_rate"] = [round(100 * b.get(d, 0) / len(base), 2) for d in out["defect"]]
    else:
        out["base_rate"] = np.nan
    return out


def defect_compare(defect_type, line=None, start=None, end=None, **sub) -> pd.DataFrame:
    """같은 결함의 강종별 발생률 (타 강종 비교): grade, n, count, rate(%). 보는 기간 기준 (전체 기간이면 전체)."""
    df = filter_coils(None, line, **sub)
    if df.empty or "defect_type" not in df:
        return pd.DataFrame(columns=["grade", "n", "count", "rate"])
    if start is not None or end is not None:
        df, _ = split_period(df, start, end)
    d = df.assign(hit=df["defect_type"].fillna("없음") == defect_type)
    g = d.groupby("grade")["hit"].agg(n="size", count="sum").reset_index()
    g["count"] = g["count"].astype(int)
    g["rate"] = (100 * g["count"] / g["n"].clip(lower=1)).round(2)
    return g.sort_values("rate", ascending=False).reset_index(drop=True)
