"""prd_v7: 엑셀 기반 기본 정보, 공정 조건 요약, 불량 코일 명칭, 작은 히스토그램 지시값 선."""
import pytest

from tools import analysis as A
from tools import charts as C
from tools import terms as T
from tools.datasource import use_source


@pytest.fixture(autouse=True)
def _sample():
    use_source(None)
    yield
    use_source(None)


def test_overview_uses_excel_values_only():
    df = A.filter_coils("HSLA590C")
    rows = dict(A.grade_overview(df, "HSLA590C"))
    assert not any("계열" in k or "이름" in k for k in rows)
    sp = A.excel_spec(df)
    assert set(sp) <= set(A.EXCEL_SPEC) and "rbar" not in sp  # r̄ 하한은 엑셀 SPEC 열이 아니라서 빠진다
    assert "용도코드" in rows and "(" in rows["용도코드"]  # 코드 (코일 수), 용도 이름 없음


def test_process_overview_only_present_factors():
    cal = A.process_overview(A.filter_coils("HSLA590C", "CAL"))
    names = [r["factor"] for r in cal]
    assert names == [f for f in A.PROC_FACTORS if f in names]  # 공정 순서
    assert {"CT", "SS", "SPM"} <= set(names) and "GA_temp" not in names  # CAL에는 합금화 없음
    ct = next(r for r in cal if r["factor"] == "CT")
    assert ct["n"] > 0 and ct["min"] <= ct["mean"] <= ct["max"]


def test_mini_hist_aim_mark():
    df = A.filter_coils("HSLA590C")
    svg = C.mini_hist_svg(df["CT"], (None, None), None, mark=600.0)
    assert "stroke-dasharray='2,2'" in svg


def test_bad_coil_wording():
    assert T.t("group_outlier") == "불량 코일" and T.t("mode_outlier") == "불량 코일 vs 정상 코일"
    assert T.t("side_label") == "불량 코일 기준"
