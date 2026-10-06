"""trace_defect: 표면결함 원인 공정 추적 (에이전트 도구)."""
from tools import analysis


def trace_defect(defect_type, grade=None, line=None, start_date=None, end_date=None) -> dict:
    """결함 발생률을 대상 기간과 기준 기간으로 비교하고, 원인 인자를 효과크기로 순위화한다."""
    return analysis.defect_trace(defect_type, grade, line, start_date, end_date)
