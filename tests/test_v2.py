"""prd_v2 R1~R6 기능 테스트 (API 없이)."""
import builtins
import importlib
import json
import socket
import sys
from pathlib import Path

import pandas as pd
import pytest

from agent import offline, router
from tools import analysis as A
from tools import coil_lookup as L
from tools import dashboard_state as ds
from tools import narrative as N
from tools import terms as T
from tools import upload as U
from tools.datasource import DataSource, get_source, sample_source, use_source

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _sample_source():
    use_source(None)
    yield
    use_source(None)


# ---------------------------------------------------------------------------
# 1단계: 데이터 소스·스키마
# ---------------------------------------------------------------------------
def test_rbar_and_dr_are_derived():
    df = get_source().coils
    r = df.iloc[0]
    assert r["rbar"] == pytest.approx((r["r0"] + 2 * r["r45"] + r["r90"]) / 4, abs=1e-3)
    assert r["dr"] == pytest.approx((r["r0"] - 2 * r["r45"] + r["r90"]) / 2, abs=1e-3)


def test_lineage_columns_and_split_coils():
    df = get_source().coils
    assert {"slab_no", "hot_coil_no", "trial_flag"} <= set(df.columns)
    assert df["hot_coil_no"].duplicated().any()  # 분할(1:N) 계보가 있다
    assert (df["trial_flag"] == "Y").sum() > 0


def test_upload_source_same_as_sample():
    """샘플 CSV를 업로드 소스로 올리면 분석 결과가 샘플 DB와 같다."""
    base = A.compare("HSLA590C", "YS", "CAL", "2026-05-01", "2026-05-31")
    raw = pd.read_csv("files/coil_data.csv", encoding="utf-8-sig")
    df = U.apply_mapping(raw, U.suggest_mapping(raw.columns))
    use_source(U.build_source(df, "coil_data.csv"))
    up = A.compare("HSLA590C", "YS", "CAL", "2026-05-01", "2026-05-31")
    assert get_source().kind == "upload"
    assert [r["factor"] for r in up["ranking"][:5]] == [r["factor"] for r in base["ranking"][:5]]
    assert up["prop_shift"] == base["prop_shift"]


def test_missing_factor_columns_are_skipped():
    df = sample_source().coils[["coil_no", "prod_date", "grade", "line", "YS", "CT", "thk"]].copy()
    use_source(DataSource(df, sample_source().grades.reset_index(drop=True), "partial", "upload"))
    c = A.compare("HSLA590C", "YS", "CAL", "2026-05-01", "2026-05-31")
    assert [r["factor"] for r in c["ranking"]] == ["CT"]
    assert set(A.spec("HSLA590C")) == {"YS"}
    assert "error" in A.defect_trace("슬리버")


def test_dashboard_ranges_follow_source():
    df = sample_source().coils
    part = df[(df.grade == "LC340") & (df.prod_date < "2026-03-01")]
    use_source(DataSource(part, sample_source().grades.reset_index(drop=True), "part", "upload"))
    assert ds.grades() == ["LC340"] and str(ds.data_range()[1]) < "2026-03-01"
    assert ds.defaults()["grade"] == "LC340"


def test_app_modules_import_without_openai(monkeypatch):
    """openai 미설치 PC: 에이전트 모듈은 필요할 때만 불러오고 오프라인으로 답한다."""
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "openai" or name.startswith("openai."):
            raise ImportError("no openai")
        return real_import(name, *a, **k)

    for m in ("agent.agent", "agent.router"):
        importlib.import_module(m)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    for m in ("agent.agent", "agent.router"):
        importlib.reload(sys.modules[m])  # 모듈 로딩 시점에 openai를 부르지 않아야 성공한다
    monkeypatch.setattr("config.has_api_key", lambda: True)
    res, mode, notice = router.answer("5월 590C YS 원인", ds.defaults(), mode="auto")
    assert mode == "offline" and "openai" in notice


# ---------------------------------------------------------------------------
# R1 r값·n값
# ---------------------------------------------------------------------------
def test_s2_rbar_down_and_ss_first():
    d = A.diagnose("IF340_OUT", None, "2026-03-01", "2026-03-31")
    assert d["properties"]["rbar"]["judgement"] == "하향 분포"
    top = A.compare("IF340_OUT", "rbar", None, "2026-03-01", "2026-03-31")["ranking"][0]
    assert top["factor"] == "SS" and top["mechanism"]["status"] == "일치"


def test_formability_spec_only_where_defined():
    assert A.spec("IF270_IN")["rbar"] == (1.8, None) and A.spec("IF270_IN")["dr"] == (None, 0.7)
    assert A.spec("LC340")["rbar"] == (None, None)
    s = A.diagnose("LC340", props=["rbar"])["properties"]["rbar"]["target"]
    assert s["spec_rate"] is None and s["mean"] is not None


# ---------------------------------------------------------------------------
# R2 업로드
# ---------------------------------------------------------------------------
def test_korean_cp949_upload_maps_and_validates():
    raw, sheets = U.read_file((FIX / "korean_cp949.csv").read_bytes(), "korean_cp949.csv")
    m = U.suggest_mapping(raw.columns)
    assert m["코일번호"] == "coil_no" and m["권취온도"] == "CT" and m["열연코일번호"] == "hot_coil_no"
    assert m["항복강도"] == "YS" and m["n값"] == "n_value" and m["시생산여부"] == "trial_flag"
    df = U.apply_mapping(raw, m)
    rep = U.validate(df, raw, m, sample_source().grades.reset_index(drop=True))
    assert rep["ok"] and rep["bad_rows"] == 0
    src = U.build_source(df, "korean", drop_bad=rep["bad_mask"])
    use_source(src)
    assert set(ds.grades()) == {"HSLA590C", "IF340_OUT"} and src.has("rbar")
    top = A.compare("HSLA590C", "YS", "CAL", "2026-05-01", "2026-05-31")["ranking"][0]
    assert top["factor"] == "CT"


def test_missing_required_column_is_error():
    raw, sheets = U.read_file((FIX / "missing_line.xlsx").read_bytes(), "missing_line.xlsx")
    m = U.suggest_mapping(raw.columns)
    assert m["코일NO"] == "coil_no" and sheets == ["Sheet1"]
    rep = U.validate(U.apply_mapping(raw, m), raw, m)
    assert not rep["ok"] and any(i["code"] == "missing_required" for i in rep["issues"])


def test_bad_rows_reported():
    raw, _ = U.read_file((FIX / "bad_rows.csv").read_bytes(), "bad_rows.csv")
    m = U.suggest_mapping(raw.columns)
    df = U.apply_mapping(raw, m)
    rep = U.validate(df, raw, m)
    codes = {i["code"]: i["count"] for i in rep["issues"]}
    assert codes["duplicate"] == 1 and codes["bad_date"] == 1 and codes["non_numeric"] == 1
    src = U.build_source(df, "bad", drop_bad=rep["bad_mask"])
    assert len(src.coils) == 38


def test_ppm_conversion_and_template():
    df = U.apply_mapping(pd.DataFrame({"coil_no": ["A"], "N": [35.0]}), {"coil_no": "coil_no", "N": "N"}, ppm_columns=["N"])
    assert df["N"].iloc[0] == pytest.approx(0.0035)
    xls = pd.ExcelFile(__import__("io").BytesIO(U.template_excel()))
    assert xls.sheet_names == ["coil", "컬럼 정의", "grade_master"]


def test_mapping_saved_and_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "MAPPING_DIR", tmp_path)
    U.save_mapping("사내양식", {"코일번호": "coil_no"}, ["N"])
    assert U.list_mappings() == ["사내양식"] and U.load_mapping("사내양식")["ppm_columns"] == ["N"]


# ---------------------------------------------------------------------------
# R3 코일 단건 분석
# ---------------------------------------------------------------------------
def test_find_coils_expands_hot_coil_and_suggests():
    df = get_source().coils
    hc = df[df["hot_coil_no"].duplicated(keep=False)]["hot_coil_no"].iloc[0]
    f = L.find_coils(hc, "hot_coil_no")
    assert len(f["found"]) == 2 and f["lineage"][0]["hot_coil_no"] == hc
    f = L.find_coils("C26050", "coil_no")
    assert f["missing"] == ["C26050"] and f["suggestions"]["C26050"]
    assert L.parse_ids("A1, A2\nA3\tA1") == ["A1", "A2", "A3"]


def test_analyze_coil_structure_and_baseline():
    coil = get_source().coils.query("grade == 'HSLA590C' and trial_flag == 'N'").iloc[100]["coil_no"]
    r = L.analyze_coil(coil)["coils"][0]
    assert r["n_baseline"] >= L.MIN_BASE and r["coil_no"] == coil
    assert {m["prop"] for m in r["materials"]} >= {"YS", "TS", "EL", "rbar", "n_value"}
    assert all(0 <= m["percentile"] <= 100 for m in r["materials"])
    assert r["factors"] == sorted(r["factors"], key=lambda f: -abs(f["z"] or 0))


def test_trial_coils_changed_factor_found():
    """생성 규칙상 '바꾼 인자'가 있는 시생산 코일에서 그 인자가 상위 3위 안에 드는 비율 (정답지는 테스트만 읽는다)."""
    key = pd.read_csv("files/trial_key.csv").fillna("")
    key = key[key["changed_factor"] != ""]
    hits = sum(k.changed_factor in [f["factor"] for f in L.analyze_coil(k.coil_no)["coils"][0]["factors"][:3]]
               for k in key.itertuples())
    assert hits / len(key) >= 0.8


def test_trial_coils_excluded_from_baseline():
    trial = get_source().coils.query("trial_flag == 'Y'")["coil_no"].tolist()
    df = get_source().coils
    coil = df[df.coil_no == trial[0]].iloc[0]
    base, conds, widened = L._baseline(df, coil, {coil.coil_no}, 3, True, True)
    assert not set(base["coil_no"]) & set(trial)


# ---------------------------------------------------------------------------
# R4 오프라인 모드
# ---------------------------------------------------------------------------
DEMO = [
    ("5월 CAL 590C 항복강도가 낮은데 원인이 뭐야?", dict(grade="HSLA590C", line="CAL", start="2026-05-01", prop="YS", view="원인 분석")),
    ("3월 극저 외판 연신율 미달이 늘었어. 원인 분석해줘", dict(grade="IF340_OUT", start="2026-03-01", prop="EL")),
    ("2월 440R 인장강도가 높게 나오고 연신율도 떨어졌어", dict(grade="LC440R", start="2026-02-01", prop="TS")),
    ("4월 340 항복강도가 전반적으로 올라간 것 같아", dict(grade="LC340", start="2026-04-01", prop="YS")),
    ("1월 극저 내판 슬리버 결함 원인 찾아줘", dict(grade="IF270_IN", start="2026-01-01", defect="슬리버", view="표면결함")),
    ("6월 GA재 파우더링이 많아졌는데 이유가 뭐야?", dict(line="CGL_GA", start="2026-06-01", defect="파우더링", view="표면결함")),
]


@pytest.mark.parametrize("q,expected", DEMO)
def test_offline_parses_demo_questions(q, expected):
    r = offline.answer(q, ds.defaults())
    assert {k: r.changed.get(k) for k in expected} == expected
    assert r.stop_reason == "offline" and len(r.text) > 50


def test_offline_answers_mention_injected_cause():
    for q, word in [(DEMO[0][0], "권취온도"), (DEMO[1][0], "균열온도"), (DEMO[4][0], "주조속도"), (DEMO[5][0], "합금화")]:
        assert word in offline.answer(q, ds.defaults()).text


def test_offline_coil_question_and_unknown():
    coil = get_source().coils.iloc[10]["coil_no"]
    r = offline.answer(f"{coil} 코일 양산이랑 비교해줘", ds.defaults())
    assert r.changed["view"] == "코일 단건 분석" and r.changed["coil_ids"] == coil
    assert "이렇게 물어보세요" in offline.answer("안녕하세요", ds.defaults()).text


def test_offline_makes_no_network_calls(monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("외부 통신 시도")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    for q, _ in DEMO:
        router.answer(q, ds.defaults(), mode="offline")
    coil = get_source().coils.iloc[10]["coil_no"]
    router.answer(f"{coil} 분석", ds.defaults(), mode="offline")


def test_router_falls_back_without_key(monkeypatch):
    monkeypatch.setattr("config.has_api_key", lambda: False)
    res, mode, notice = router.answer(DEMO[0][0], ds.defaults(), mode="auto")
    assert mode == "offline" and "키" in notice
    res, mode, notice = router.answer(DEMO[0][0], ds.defaults(), mode="offline")
    assert mode == "offline" and notice is None


# ---------------------------------------------------------------------------
# R5 문체, R6 용어
# ---------------------------------------------------------------------------
BANNED_EASY = ["이탈군", "층별", "교란", "기준군", "비교군"]


def _all_text(ins):
    return " ".join(ins["summary"] + ins["actions"] + ins["warnings"])


def test_three_styles_share_numbers_and_easy_has_no_jargon():
    d = A.diagnose("HSLA590C", None, "2026-05-01", "2026-05-31")
    c = A.compare("HSLA590C", "YS", None, "2026-05-01", "2026-05-31")
    texts = {s: _all_text(N.insights(d, c, s)) for s in T.STYLES}
    shift = f"{abs(d['properties']['YS']['shift']):.1f}"
    assert all(shift in t for t in texts.values())
    assert "Orowan" in texts["expert"] and "것 같아요" in texts["easy"]
    # 전체 기간 비교는 비교 조건 차이 경고가 나오는 경우: 쉬운 말에는 통계 용어가 없어야 한다
    d = A.diagnose("HSLA590C")
    c = A.compare("HSLA590C", "YS")
    assert c["warnings"]
    texts = {s: _all_text(N.insights(d, c, s)) for s in T.STYLES}
    assert not any(w in texts["easy"] for w in BANNED_EASY)
    assert not any(w in texts["expert"] for w in ["이탈군", "층별"])
    assert "층별" in texts["stat"] and "나눠서 다시 비교" in texts["easy"]


def test_full_period_group_names():
    c = A.compare("HSLA590C", "YS")
    grp, ref = T.group_names(c["mode"], c["side"], "easy")
    assert grp.startswith("문제 코일") and ref == "정상 코일"
    assert T.group_names(c["mode"], c["side"], "stat")[0].startswith("이탈군")


def test_coil_story_styles():
    coil = pd.read_csv("files/trial_key.csv").fillna("").query("changed_factor == 'CT'").coil_no.iloc[0]
    r = L.analyze_coil(coil)["coils"][0]
    for s in T.STYLES:
        lines = N.coil_story(r, s)
        assert lines and all(isinstance(x, str) for x in lines)


def test_style_flows_into_agent_prompt():
    from agent.prompts import build_system_prompt
    assert "구어체" in build_system_prompt("easy") and "Orowan" in build_system_prompt("expert")
    assert "이탈군" in build_system_prompt("easy")  # 쓰지 말라는 규칙 문장에만 등장
