"""compare_groups: 이탈군/기준군 공정인자 비교 (에이전트 도구)."""
from tools import analysis
from tools.terms import warning_text


def compare_groups(grade, target_property, line=None, start_date=None, end_date=None,
                   baseline_start=None, baseline_end=None, side="auto") -> dict:
    """성분·공정인자별 효과크기·상관·p값으로 기여도를 순위화하고 교란 요인과 메커니즘 일치 여부를 반환한다."""
    r = analysis.compare(grade, target_property, line, start_date, end_date, baseline_start, baseline_end,
                         side=side, top_n=8)
    r.pop("all_factors", None)
    r["confounders"] = {k: {"max_gap_pp": v["max_gap_pp"], "warning": v["warning"]}
                        for k, v in r["confounders"].items()}
    r["warning_texts"] = [warning_text(w) for w in r["warnings"]]
    return r
