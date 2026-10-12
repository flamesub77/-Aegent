import json
import sqlite3

import pytest

from config import DATA_DIR
from tools import db
from tools.guard import BlockedFileError, ensure_allowed
from tools.knowledge import load_sections, search_knowledge
from tools.query import query_coils
from tools.registry import TOOL_FUNCTIONS, run_tool, tool_schemas


def test_db_is_read_only():
    with db.connect() as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM coil")


def test_grade_master_has_six_grades():
    assert sorted(db.grade_codes()) == sorted(
        ["IF270_IN", "IF340_OUT", "BH340_OUT", "LC340", "LC440R", "HSLA590C"])


def test_query_coils_filters():
    r = query_coils(grade="HSLA590C", line="CAL", start_date="2026-05-01", end_date="2026-05-31")
    assert r["count"] > 0
    assert r["by_grade"] == {"HSLA590C": r["count"]}
    assert r["by_line"] == {"CAL": r["count"]}
    assert "2026-05-01" <= r["date_range"][0] <= r["date_range"][1] <= "2026-05-31"


def test_query_coils_total_and_thickness():
    assert query_coils()["count"] == 4000
    r = query_coils(thk_min=1.5)
    df = db.fetch_coils(thk_min=1.5)
    assert r["count"] == len(df) and (df["thk"] >= 1.5).all()


def test_query_coils_rejects_unknown_grade_and_line():
    assert "error" in query_coils(grade="DP780")
    assert "error" in query_coils(line="EGL")


def test_query_coils_sql_injection_is_inert():
    df = db.fetch_coils(coil_pos="M' OR '1'='1")
    assert df.empty


@pytest.mark.parametrize("name", ["anomaly_scenarios.md", "answer_key.csv", "generate_data.py"])
def test_blocked_files(name):
    with pytest.raises(BlockedFileError):
        ensure_allowed(DATA_DIR / name)
    with pytest.raises(BlockedFileError):
        load_sections.__wrapped__(DATA_DIR / name)


def test_search_knowledge_finds_590_section():
    r = search_knowledge("590 석출경화 CT NbC")
    assert r["results"]
    assert "590" in r["results"][0]["source"]


def test_registry_matches_functions():
    names = {s["name"] for s in tool_schemas()}
    assert names == set(TOOL_FUNCTIONS) | {"get_dashboard_state", "update_dashboard"}


def test_run_tool_errors_are_reported():
    out, err = run_tool("nope", {})
    assert err
    out, err = run_tool("query_coils", {"bad_arg": 1})
    assert err and "잘못된 입력" in json.loads(out)["error"]


def test_analysis_tools_return_json():
    out, err = run_tool("diagnose_distribution", {"grade": "HSLA590C", "start_date": "2026-05-01",
                                                   "end_date": "2026-05-31"})
    assert not err and "YS" in json.loads(out)["properties"]
    out, err = run_tool("compare_groups", {"grade": "HSLA590C", "target_property": "YS"})
    assert not err and json.loads(out)["ranking"]


def test_search_knowledge_pins_grade_section():
    r = search_knowledge("CT", grade="IF340_OUT")
    assert r["results"][0]["source"].endswith("3.2 고강도 극저 외판 (IF340_OUT, Ti-Nb 복합 P첨가)")
    assert any("3.6" in x["source"] for x in r["results"])
    assert "error" in search_knowledge("CT", grade="DP780")


def test_query_coils_with_baseline():
    r = query_coils(grade="HSLA590C", start_date="2026-05-01", end_date="2026-05-31", include_baseline=True)
    assert r["count"] + r["baseline"]["count"] == query_coils(grade="HSLA590C")["count"]
