"""prd_v5: 탭 이름·옛 이름 호환, 소둔온도, 한 줄 해석, 결함 순위·비교, 데이터 편집, AI 제공자 어댑터, AI 보고서."""
import json
import sys
import types
from types import SimpleNamespace

import pandas as pd
import pytest

import config
from agent import providers, router
from tools import analysis as A
from tools import dashboard_state as ds
from tools import edits as E
from tools import narrative as N
from tools import report_ppt as R
from tools import spc
from tools.datasource import get_source, use_source


@pytest.fixture(autouse=True)
def _sample():
    use_source(None)
    yield
    use_source(None)


def test_views_renamed_and_old_names_accepted():
    assert ds.VIEWS == ["재질개요", "공정분석", "결함분석", "코일분석", "데이터"]
    for old, new in [("재질 현황", "재질개요"), ("원인 분석", "공정분석"), ("표면결함", "결함분석"),
                     ("단일 코일 분석", "코일분석"), ("Raw Data", "데이터")]:
        assert ds.apply_update(ds.defaults(), {"view": old})[0]["view"] == new
    assert ds.defaults()["view"] == "재질개요"


def test_annealing_temp_label_and_alias():
    from agent import offline
    from tools.domain import factor_label
    assert factor_label("SS") == "소둔온도 SS"
    assert offline.answer("산점도를 균열온도로 바꿔줘", ds.defaults()).changed.get("factor") == "SS"
    assert offline.answer("산점도를 소둔온도로 바꿔줘", ds.defaults()).changed.get("factor") == "SS"


def test_sample_covers_2019_and_new_grades():
    src = get_source()
    lo, hi = src.date_range()
    assert lo[:4] == "2019" and hi[:4] == "2026"
    assert {"DP780", "TRIP780", "MART1180", "IF260_IN"} <= set(src.grade_codes())
    assert {"EGL", "CGL_GI"} <= set(src.lines()) and src.coils["plant"].nunique() >= 2
    assert {"롤 마크", "스크래치"} <= set(src.coils["defect_type"].unique())
    assert src.grade("DP780")["family"] == "DP"


def test_new_family_mechanism_in_ranking():
    comp = A.compare("DP780", "TS")
    assert comp["family"] == "DP"
    assert any(r["mechanism"]["status"] != "지식베이스 근거 없음" for r in comp["all_factors"] if r["factor"] in ("SS", "RCS"))


def test_chart_notes_are_one_line():
    d = A.diagnose("HSLA590C", "CAL", "2026-05-01", "2026-05-31")
    c = A.compare("HSLA590C", "YS", "CAL", "2026-05-01", "2026-05-31")
    for title, lines in (N.note_distribution(d, "YS", "이 기간 코일", "나머지 기간 코일"), N.note_contribution(c, "차이 크기"),
                         N.note_scatter(c, "CT", "YS"), N.note_confounders(c)):
        assert title and len(lines) <= 1 and all(len(x) <= 70 for x in lines)
    assert "권취온도" in N.note_contribution(c, "차이 크기")[0]


def test_defect_pareto_and_compare():
    p = A.defect_pareto("HSLA590C", None, "2026-01-01", "2026-06-30")
    assert len(p) and p["rate"].is_monotonic_decreasing and p["cum_pct"].iloc[-1] == 100.0
    rows = A.defect_compare(p["defect"].iloc[0], None, "2026-01-01", "2026-06-30")
    assert "HSLA590C" in set(rows["grade"]) and rows["rate"].is_monotonic_decreasing
    title, lines = N.note_defect_compare(rows, p["defect"].iloc[0], "HSLA590C")
    assert "위" in title and lines
    assert N.note_pareto(p, "HSLA590C")[0].startswith("HSLA590C 결함 1위")


def test_spc_presets():
    assert spc.PRESETS["기본"] == spc.DEFAULTS
    assert spc.PRESETS["작은 변화도 빨리"]["lam"] == 0.1 and spc.PRESETS["헛경보 줄이기"]["base_months"] == 12


def test_data_edits_exclude_change_undo_and_source():
    src = get_source()
    base = A.filter_coils("HSLA590C").head(50).reset_index(drop=True)
    shown = E.apply(base, E.empty(), drop_excluded=False)[["제외", "coil_no", "YS"]]
    edited = shown.copy()
    edited.loc[0, "제외"] = True
    edited.loc[1, "YS"] = 999.0
    edited.loc[1, "coil_no"] = "HACK"  # 번호 열은 잠금
    d = E.diff(shown, edited, E.empty(), original=base)
    c0, c1 = str(base.loc[0, "coil_no"]), str(base.loc[1, "coil_no"])
    assert c0 in d["excluded"] and d["changes"][(c1, "YS")]["new"] == 999.0
    assert d["changes"][(c1, "YS")]["old"] == base.loc[1, "YS"] and not any(k[1] == "coil_no" for k in d["changes"])
    assert E.summary(d) == "제외 1행, 변경 1칸" and len(E.log_rows(d)) == 2
    edited.loc[1, "coil_no"] = shown.loc[1, "coil_no"]
    back = E.diff(edited, edited.assign(YS=shown["YS"]), d, original=base)  # 원래 값으로 되돌리면 기록에서 빠진다
    assert (c1, "YS") not in back["changes"]
    new = E.edited_source(src, d)
    assert len(new.coils) == len(src.coils) - 1 and "수정 2건" in new.name and new.edit_note == "제외 1행, 변경 1칸"
    assert new.coils.set_index("coil_no").at[c1, "YS"] == 999.0
    assert len(src.coils) == len(get_source().coils)  # 원본은 그대로


def test_outlier_mask():
    df = pd.DataFrame({"coil_no": list("abcdefghij"), "TS": [600] * 9 + [5000]})
    m = E.outlier_mask(df, "TS", k=2.5, spec=(590, None))
    assert m.tolist() == [False] * 9 + [True]
    assert E.outlier_mask(df.assign(TS=[600] * 9 + [200]), "TS", k=10, spec=(590, None)).iloc[-1]  # SPEC 50% 밖


def test_router_modes_and_missing_packages(monkeypatch):
    assert router.normalize("auto") == "ai" and router.normalize("agent") == "ai" and router.normalize("offline") == "offline"
    monkeypatch.setattr(providers, "installed", lambda p: False)
    monkeypatch.setattr("config.has_api_key", lambda key=None, **k: True)
    res, mode, notice = router.answer("5월 590C YS 원인", ds.defaults(), mode="ai", provider="anthropic", api_key="k")
    assert mode == "offline" and "anthropic" in notice
    ok, msg = providers.check_key("gemini", "x")
    assert not ok and "google-genai" in msg


def test_provider_keys_resolved_per_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    monkeypatch.setattr(config, "ALLOW_SHARED_KEY", True)
    assert config.resolve_api_key(None, "anthropic") == "sk-ant-env"
    assert config.resolve_api_key("u", "gemini") == "u"
    assert config.provider_model("anthropic") == config.PROVIDERS["anthropic"][2]


def _block(**kw):
    return SimpleNamespace(**kw)


def test_anthropic_adapter_tool_loop(monkeypatch):
    """가짜 anthropic 모듈로 도구 루프 확인 (패키지·네트워크 없이)."""
    calls = []
    script = [
        SimpleNamespace(stop_reason="tool_use", content=[_block(type="tool_use", id="t1", name="update_dashboard",
                                                                input={"view": "원인 분석", "factor": "CT"})]),
        SimpleNamespace(stop_reason="end_turn", content=[_block(type="text", text="CT가 1순위예요.")]),
    ]

    class Msgs:
        def create(self, **kw):
            calls.append(kw)
            return script[len(calls) - 1]

    class Client:
        def __init__(self, **kw):
            self.messages = Msgs()
            self.beta = SimpleNamespace(messages=Msgs())

    class Err(Exception):
        pass

    fake = types.ModuleType("anthropic")
    fake.Anthropic = Client
    for name in ("AnthropicError", "APIConnectionError", "APITimeoutError", "AuthenticationError", "RateLimitError",
                 "NotFoundError", "APIStatusError"):
        setattr(fake, name, Err)
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    sys.modules.pop("agent.providers.anthropic_provider", None)
    from agent.providers import anthropic_provider as AP
    res = AP.run("원인?", ds.defaults(), None, "k", "claude-sonnet-5-5")
    assert res.text == "CT가 1순위예요." and res.state["view"] == "공정분석" and res.state["factor"] == "CT"
    first = calls[0]
    assert first["betas"] == [AP.FALLBACK_BETA] and first["fallbacks"] == "default"
    assert {t["name"] for t in first["tools"]} >= {"compare_groups", "update_dashboard"}
    assert all("input_schema" in t for t in first["tools"])
    second = calls[1]["messages"]
    assert second[-1]["content"][0]["type"] == "tool_result" and second[-1]["content"][0]["tool_use_id"] == "t1"
    sys.modules.pop("agent.providers.anthropic_provider", None)


def test_ai_report_parse_and_render():
    good = R.parse_ai('설명 {"summary": ["요약"], "notes": {"spc": ["경보 5/3"], "zzz": ["x"]}, "actions": ["CT 복귀"]}')
    assert good["notes"] == {"spc": ["경보 5/3"]} and good["actions"] == ["CT 복귀"]
    assert R.parse_ai("JSON 아님") is None
    assert R.filename("HSLA590C").startswith("HSLA590C_AI보고서_")
