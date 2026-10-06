"""diagnose_distribution: 재질 분포 진단 (에이전트 도구)."""
from tools import analysis
from tools.terms import warning_text


def diagnose_distribution(grade, line=None, start_date=None, end_date=None,
                          baseline_start=None, baseline_end=None, properties=None) -> dict:
    """YS/TS/EL(BH) 평균·표준편차·스펙 만족률·Cpk를 기준 기간과 비교하고 1σ 기준으로 상향/하향을 판정한다."""
    r = analysis.diagnose(grade, line, start_date, end_date, baseline_start, baseline_end, properties)
    r["warning_texts"] = [warning_text(w) for w in r["warnings"]]
    return r
