"""분석 엔진: 대시보드와 에이전트 도구가 함께 쓰는 계산 함수.

모든 수치는 여기서 계산하고, LLM은 결과를 해석만 한다.
"""

import numpy as np
import pandas as pd
from scipy import stats

from tools.datasource import get_source
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
    """데이터에 실제로 값이 있는 공정인자만 (업로드 데이터는 일부 인자가 없을 수 있다)."""
    return [f for f in FACTORS if f in df.columns and df[f].notna().any()]


def filter_coils(grade=None, line=None, thk_min=None, thk_max=None, coil_pos=None,
                 df: pd.DataFrame | None = None, thk_band=None) -> pd.DataFrame:
    df = all_coils() if df is None else df
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
    s = s.dropna()
    n = len(s)
    if n == 0:
        return {"n": 0}
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
    return {"n": n, "mean": _r(mean, nd), "std": _r(std, nd + 1), "min": _r(s.min(), nd), "max": _r(s.max(), nd),
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
             props=None, thk_min=None, thk_max=None, coil_pos=None, thk_band=None) -> dict:
    """대상 기간 재질 분포를 기준 기간과 비교한다."""
    sp = spec(grade)
    props = [p for p in (props or PROPS) if p in sp]
    df = filter_coils(grade, line, thk_min, thk_max, coil_pos, thk_band=thk_band)
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


def comparison_groups(df, grade, prop, start=None, end=None, base_start=None, base_end=None, side="auto"):
    """비교할 두 그룹을 정한다. 반환: (mode, side, group, ref).

    mode="period": 기간이 주어지고 나머지 기간 코일이 충분하면 이 기간 코일 vs 나머지 기간 코일
    mode="outlier": 아니면 문제 코일(스펙 또는 평균±1σ 밖) vs 정상 코일. 화면 용어는 tools/terms.py
    """
    target, baseline = split_period(df, start, end, base_start, base_end)
    if (start or end) and len(baseline) >= MIN_N:
        return "period", None, target, baseline
    lo, hi = spec(grade).get(prop, (None, None))
    mean, std = df[prop].mean(), df[prop].std()
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
            side="auto", thk_min=None, thk_max=None, coil_pos=None, top_n=10, thk_band=None) -> dict:
    """비교군과 기준군의 인자를 비교해 기여도 순위를 매긴다."""
    df = filter_coils(grade, line, thk_min, thk_max, coil_pos, thk_band=thk_band)
    family = grade_info(grade)["family"]
    mode, side, group, ref = comparison_groups(df, grade, prop, start, end, base_start, base_end, side)

    prop_shift = group[prop].mean() - ref[prop].mean() if len(group) and len(ref) else None
    both = pd.concat([group, ref])
    std_row = grade_info(grade)
    ranking = []
    for f in available_factors(both):
        if both[f].notna().sum() < 10 or both[f].std() == 0:
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
    ranking.sort(key=lambda x: -abs(x["effect_size"]))
    for i, row in enumerate(ranking, 1):
        row["rank"] = i

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
            "confounders": confounders, "warnings": warnings}


def defect_trace(defect_type, grade=None, line=None, start=None, end=None, top_n=8) -> dict:
    """결함 발생률을 기간별로 비교하고, 결함 코일과 정상 코일의 인자를 비교한다."""
    if defect_type not in DEFECTS:
        return {"error": f"알 수 없는 결함 유형: {defect_type}", "available": list(DEFECTS)}
    df = filter_coils(grade, line)
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


def overview_heatmap(prop: str, line=None) -> pd.DataFrame:
    """강종 × 월 평균의 강종 전체 평균 대비 편차(σ 단위)."""
    df = filter_coils(line=line)
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
