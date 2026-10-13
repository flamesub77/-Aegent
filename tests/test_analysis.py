"""LLM 없이 분석 엔진만으로 PRD 3장 데모 질문 조건의 원인을 찾는지 검증한다.

정답지 파일은 읽지 않는다. 기대값은 PRD에 적힌 시나리오 설명에서 옮겼다.
"""
import pytest

from tools import analysis as A
from tools import dashboard_state as ds

MATERIAL = [
    # (강종, 재질, 라인, 시작, 끝, 기대 방향, 기대 1순위 인자)
    ("HSLA590C", "YS", "CAL", "2026-05-01", "2026-05-31", "하향", "CT"),
    ("IF340_OUT", "EL", "CGL_GA", "2026-03-01", "2026-03-31", "하향", "SS"),
    ("LC440R", "TS", None, "2026-02-01", "2026-02-28", "상향", "P"),
    ("LC340", "YS", "CAL", "2026-04-01", "2026-04-30", "상향", "SPM"),
]


@pytest.mark.parametrize("grade,prop,line,start,end,direction,factor", MATERIAL)
def test_material_scenarios(grade, prop, line, start, end, direction, factor):
    d = A.diagnose(grade, line, start, end)
    assert d["properties"][prop]["judgement"] == f"{direction} 분포"
    c = A.compare(grade, prop, line, start, end)
    top = c["ranking"][0]
    assert top["factor"] == factor and top["mechanism"]["status"] == "일치"


@pytest.mark.parametrize("defect,grade,line,start,end,factor", [
    ("슬리버", "IF270_IN", None, "2026-01-01", "2026-01-31", "cast_speed"),
    ("파우더링", None, "CGL_GA", "2026-06-01", "2026-06-30", "GA_temp"),
])
def test_defect_scenarios(defect, grade, line, start, end, factor):
    r = A.defect_trace(defect, grade, line, start, end)
    assert r["rate_target_pct"] > 3 * r["rate_baseline_pct"]
    assert r["factor_ranking"][0]["factor"] == factor and r["factor_ranking"][0]["kb_consistent"]


def test_normal_period_is_not_flagged():
    d = A.diagnose("HSLA590C", "CAL", "2026-02-01", "2026-02-28")
    assert d["properties"]["YS"]["judgement"] in ("정상", "상향 경향", "하향 경향")


def test_cpk_and_spec_rate():
    s = A.dist_stats(__import__("pandas").Series([10.0, 12.0, 14.0]), lo=8, hi=16)
    assert s["spec_rate"] == 100.0 and s["cpk"] == round((16 - 12) / (3 * 2.0), 2)


def test_full_period_uses_deviant_comparison():
    c = A.compare("HSLA590C", "YS")
    assert c["mode"] == "outlier" and c["side"] in ("low", "high")


def test_insights_have_numbers_and_actions():
    d = A.diagnose("HSLA590C", "CAL", "2026-05-01", "2026-05-31")
    c = A.compare("HSLA590C", "YS", "CAL", "2026-05-01", "2026-05-31")
    ins = A.insights(d, c)
    assert "평소보다 낮게 나옴" in ins["summary"][0] and any("권취온도" in a for a in ins["actions"])


def test_dashboard_update_validation():
    new, applied, errors = ds.apply_update(ds.defaults(), {"start_date": "2026-06-30", "end_date": "2026-01-01"})
    assert errors and new["start"] == ds.defaults()["start"]
    new, applied, errors = ds.apply_update(ds.defaults(), {"line": "CGL", "prop": "BH"})
    assert new["line"] == "CGL_GA" and new["prop"] == "YS" and errors
