"""API 호출 없이 가짜 OpenAI 클라이언트로 에이전트 루프를 검증한다."""
import json
from types import SimpleNamespace as NS

from agent.agent import run_agent
from tools import dashboard_state as ds


def _fcall(i, name, args):
    item = NS(type="function_call", call_id=f"call_{i}", name=name, arguments=json.dumps(args))
    item.model_dump = lambda **kw: {"type": "function_call", "call_id": item.call_id, "name": name,
                                    "arguments": item.arguments}
    return item


class FakeClient:
    """scripted 응답을 차례로 돌려준다. 응답 = (text, [(name, args)...], status)."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.responses = NS(create=self._create)

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "input": list(kwargs["input"])})
        text, calls, status = self.script.pop(0)
        output = [_fcall(i, n, a) for i, (n, a) in enumerate(calls)]
        return NS(output=output, output_text=text, status=status, incomplete_details=None)


def test_agent_runs_tools_and_updates_dashboard():
    client = FakeClient([
        (None, [("compare_groups", {"grade": "HSLA590C", "target_property": "YS", "line": "CAL",
                                    "start_date": "2026-05-01", "end_date": "2026-05-31"}),
                ("update_dashboard", {"line": "CAL", "start_date": "2026-05-01", "end_date": "2026-05-31",
                                      "factor": "CT", "view": "원인 분석"})], "completed"),
        ("**판정**: YS 하향", [], "completed"),
    ])
    result = run_agent("5월 CAL 590C YS 낮은 원인?", ds.defaults(), client=client)

    assert [c.name for c in result.tool_calls] == ["compare_groups", "update_dashboard"]
    assert json.loads(result.tool_calls[0].output)["ranking"][0]["factor"] == "CT"
    assert result.state["factor"] == "CT" and result.state["view"] == "원인 분석"
    assert str(result.state["start"]) == "2026-05-01" and set(result.changed) >= {"start", "end", "line"}

    # 두 번째 요청에 function_call과 function_call_output이 짝지어 들어갔는지
    items = client.requests[1]["input"]
    assert [i["type"] for i in items[-4:]] == ["function_call", "function_call",
                                               "function_call_output", "function_call_output"]
    assert items[-1]["call_id"] == "call_1"
    assert "현재 대시보드 상태" in client.requests[0]["input"][0]["content"]
    assert client.requests[0]["instructions"] and client.requests[0]["tools"]


def test_invalid_dashboard_update_is_reported():
    client = FakeClient([(None, [("update_dashboard", {"grade": "DP780", "prop": "TS"})], "completed"),
                         ("완료", [], "completed")])
    result = run_agent("780DP로 바꿔", ds.defaults(), client=client)
    out = json.loads(result.tool_calls[0].output)
    assert out["errors"] and result.state["grade"] == ds.defaults()["grade"] and result.state["prop"] == "TS"


def test_agent_stops_at_max_turns(monkeypatch):
    import config
    monkeypatch.setattr(config, "MAX_AGENT_TURNS", 2)
    client = FakeClient([(None, [("search_knowledge", {"query": "CT"})], "completed")] * 2)
    result = run_agent("반복", ds.defaults(), client=client)
    assert result.stop_reason == "max_turns" and len(result.tool_calls) == 2


def test_structured_report_from_tool_outputs():
    client = FakeClient([
        (None, [("diagnose_distribution", {"grade": "HSLA590C", "line": "CAL", "start_date": "2026-05-01",
                                           "end_date": "2026-05-31"}),
                ("compare_groups", {"grade": "HSLA590C", "target_property": "YS", "line": "CAL",
                                    "start_date": "2026-05-01", "end_date": "2026-05-31"}),
                ("update_dashboard", {"view": "원인 분석"})], "completed"),
        ("리포트 본문", [], "completed"),
    ])
    rep = run_agent("질문", ds.defaults(), client=client).report
    assert rep["judgement"]["judgement"] == "하향 분포" and rep["judgement"]["property"] == "YS"
    assert rep["causes"][0]["factor"] == "CT" and rep["causes"][0]["mechanism"] == "일치"
    assert "인자 기여도" in rep["charts"] and rep["text"] == "리포트 본문"
