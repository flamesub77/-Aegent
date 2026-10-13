"""prd_v6: 재질 고정 순서, 스펙 불량 기준, 두께별·용도별 생산량, 강종 기본 정보, 코일분석 공장 조건·2년."""
import pandas as pd
import pytest

from tools import analysis as A
from tools import charts as C
from tools import coil_lookup as L
from tools import dashboard_state as ds
from tools import narrative as N
from tools.datasource import get_source, use_source
from tools.domain import PROP_ORDER


@pytest.fixture(autouse=True)
def _sample():
    use_source(None)
    yield
    use_source(None)


def test_material_order_and_auto_props():
    assert PROP_ORDER == ["YS", "TS", "EL", "n_value", "r0", "r45", "r90", "rbar", "BH"]
    assert list(A.spec("HSLA590C")) == ["YS", "TS", "EL", "n_value", "r0", "r45", "r90", "rbar"]  # BH 없는 강종
    assert list(A.spec("BH340_OUT"))[-1] == "BH"
    d = A.diagnose("HSLA590C")
    assert d["properties"]["r0"]["target"]["n"] > 0 and d["properties"]["r0"]["spec"] == {"min": None, "max": None}


def test_defect_rate_and_spec_basis():
    df = A.filter_coils("HSLA590C", "CAL")
    lo, hi = A.spec("HSLA590C")["YS"]
    rate, bad, n = A.defect_rate(df["YS"], lo, hi)
    assert n == df["YS"].notna().sum() and bad == int(((df["YS"] < lo) | (df["YS"] > hi)).sum())
    assert A.defect_rate(df["r0"])[0] is None
    _, _, g, r = A.comparison_groups(df, "HSLA590C", "YS", basis="spec")
    assert len(g) == bad and len(g) + len(r) == len(df)
    _, _, g_sigma, _ = A.comparison_groups(df, "HSLA590C", "YS", basis="sigma")
    assert len(g_sigma) > len(g)
    assert ds.apply_update(ds.defaults(), {"basis": "spec"})[0]["basis"] == "spec"
    assert ds.defaults()["basis"] == "sigma"  # S1~S6 평가 기준 유지


def test_defect_note_and_histogram():
    df = A.filter_coils("HSLA590C", "CAL")
    target, base = A.split_period(df, "2026-05-01", "2026-05-31")
    title, lines = N.note_defect_dist(target, base, "YS", A.spec("HSLA590C")["YS"])
    assert title.startswith("YP 불량률") and "나머지 기간" in lines[0]
    assert "SPEC 없음" in N.note_defect_dist(target, base, "r0", (None, None))[0]
    fig = C.defect_histogram(target, "YS", A.spec("HSLA590C")["YS"])
    assert {t.name.split(" ")[0] for t in fig.data} == {"합격", "불량"}
    fig = C.monthly_box(df, "YS", A.spec("HSLA590C")["YS"], defect_line=True)
    assert any(getattr(t, "name", "") == "불량률(%)" for t in fig.data)


def test_production_by_thickness_and_use():
    df = A.filter_coils("HSLA590C")
    thk = A.production_by(df, "thk_band")
    assert list(thk["key"]) == [b for b in ["~0.75", "0.75~1.0", "1.0~1.4", "1.4~"] if b in set(thk["key"])]
    assert thk["coils"].sum() == len(df) and abs(thk["share"].sum() - 100) < 0.5
    use = A.production_by(A.filter_coils(None), "use_code", top=3)
    assert len(use) == 4 and use["key"].iloc[-1] == "기타"
    assert "최다" in N.note_production_by(use, "용도")[0]


def test_grade_overview_rows():
    rows = dict(A.grade_overview(A.filter_coils("HSLA590C"), "HSLA590C"))
    assert rows["냉연규격"] == "HSLA590C" and "YP 440~600" in rows["SPEC"]  # v7: 엑셀 값만 (계열·이름 없음)
    assert "코일" in rows["생산"] and "%" in rows["라인"] and "mm" in rows["두께 · 폭"]


def test_coil_baseline_same_plant_and_two_years():
    src = get_source()
    coil = src.coils[src.coils["trial_flag"] == "Y"].iloc[0]["coil_no"]
    res = L.analyze_coil(coil)
    c = res["coils"][0]
    assert "공장" in c["baseline_conditions"] or "공장" in c["widened"]
    start = pd.Timestamp(c["prod_date"]) - pd.DateOffset(months=24)
    if "기간" in c["baseline_conditions"] and c["baseline_conditions"]["기간"] != "전체":
        assert c["baseline_conditions"]["기간"].startswith(start.strftime("%Y-%m-%d"))
    assert [m["prop"] for m in c["materials"]] == [p for p in L.MATERIAL_PROPS if p in {m["prop"] for m in c["materials"]}]
