"""에이전트 실행 결과를 구조화된 JSON으로 정리한다. 수치는 도구 출력에서만 가져온다."""
import json

VIEW_CHARTS = {
    "재질 편차": ["강종×월 편차 히트맵", "분포 히스토그램", "월별 박스플롯"],
    "원인 분석": ["인자 기여도", "원인 인자 산점도", "인자 일별 추이", "교란 요인 구성비"],
    "표면결함": ["월별 결함 발생률", "결함 원인 인자"],
    "코일 단건 분석": ["양산 대비 재질 위치", "양산 대비 공정 차이"],
    "Raw Data": ["코일 원천 데이터 표"],
}


def _last(calls, name):
    for c in reversed(calls):
        if c.name == name and not c.is_error:
            return c.input, json.loads(c.output)
    return None, None


def build_report(calls, text: str, state: dict | None) -> dict:
    """판정, 원인 순위, 차트 목록, 리포트 본문을 담은 dict."""
    report = {"judgement": None, "causes": [], "defect": None, "coils": [], "warnings": [], "charts": [], "text": text}

    d_in, diag = _last(calls, "diagnose_distribution")
    c_in, comp = _last(calls, "compare_groups")
    if diag:
        props = diag.get("properties", {})
        prop = (c_in or {}).get("target_property") or next(iter(props), None)
        if prop in props:
            p = props[prop]
            report["judgement"] = {"grade": diag["grade"], "line": diag["line"], "period": diag["period"],
                                   "property": prop, "shift": p["shift"], "shift_sigma": p["shift_sigma"],
                                   "judgement": p["judgement"], "spec_rate": p["target"].get("spec_rate"),
                                   "cpk": p["target"].get("cpk"), "n": diag["n_target"]}
        report["warnings"] += diag.get("warning_texts", [])
    if comp:
        report["causes"] = [{"rank": r["rank"], "factor": r["factor"], "label": r["label"],
                             "diff": r["diff"], "unit": r["unit"], "effect_size": r["effect_size"],
                             "mechanism": r["mechanism"]["status"], "source": r["mechanism"]["source"]}
                            for r in comp.get("ranking", [])[:3]]
        report["warnings"] += comp.get("warning_texts", [])
    _, defect = _last(calls, "trace_defect")
    if defect and "error" not in defect:
        report["defect"] = {"type": defect["defect_type"], "rate_target_pct": defect["rate_target_pct"],
                            "rate_baseline_pct": defect["rate_baseline_pct"],
                            "top_factors": [{"factor": r["factor"], "label": r["label"],
                                             "effect_size": r["effect_size"], "kb_consistent": r["kb_consistent"]}
                                            for r in defect["factor_ranking"][:3]]}
    _, coil = _last(calls, "analyze_coil")
    if coil and "error" not in coil:
        report["coils"] = [{"coil_no": c["coil_no"], "grade": c["grade"], "trial": c["trial"],
                            "key_property": c["key_property"], "n_baseline": c["n_baseline"],
                            "top_factors": [{"factor": f["factor"], "label": f["label"], "z": f["z"]}
                                            for f in c["top_factors"][:3]]} for c in coil["coils"]]
    if state:
        report["charts"] = VIEW_CHARTS.get(state.get("view"), [])
    report["warnings"] = list(dict.fromkeys(report["warnings"]))
    return report
