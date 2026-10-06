"""OpenAI Responses API function calling 에이전트 루프."""
import json
from dataclasses import dataclass, field

import config
from agent.prompts import build_system_prompt
from agent.report import build_report
from tools import dashboard_state as ds
from tools.registry import DashboardContext, run_tool, tool_schemas


@dataclass
class ToolCall:
    name: str
    input: dict
    output: str
    is_error: bool


@dataclass
class AgentResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    state: dict | None = None          # 에이전트 실행 후 대시보드 상태
    changed: dict = field(default_factory=dict)
    stop_reason: str | None = None
    report: dict = field(default_factory=dict)  # 판정·원인 순위·차트 목록·본문 (UI·평가용)

    def __post_init__(self):
        if not self.report:
            self.report = build_report(self.tool_calls, self.text, self.state)


def _create(client, items, instructions, tools):
    kwargs = dict(model=config.MODEL, instructions=instructions, input=items, tools=tools,
                  max_output_tokens=config.MAX_TOKENS)
    if config.REASONING_EFFORT:
        kwargs["reasoning"] = {"effort": config.REASONING_EFFORT}
    return client.responses.create(**kwargs)


def run_agent(question: str, state: dict, history: list | None = None, client=None, on_tool=None) -> AgentResult:
    """질문과 현재 대시보드 상태를 받아 도구 호출을 반복한 뒤 답변과 바뀐 상태를 반환한다.

    history: 이전 대화의 [{"role": "user"|"assistant", "content": str}, ...]
    on_tool: 도구 실행 시마다 호출되는 콜백 (UI 진행 표시용)
    """
    if client is None:
        from openai import OpenAI  # openai 미설치 PC에서도 앱이 뜨도록 필요할 때만 불러온다
        client = OpenAI()
    ctx = DashboardContext(state)
    instructions = build_system_prompt(state.get("style", "easy"))
    tools = tool_schemas()
    items = list(history or []) + [{
        "role": "user",
        "content": f"[현재 대시보드 상태] {json.dumps(ds.describe(state), ensure_ascii=False)}\n\n{question}"}]
    calls: list[ToolCall] = []

    for _ in range(config.MAX_AGENT_TURNS):
        response = _create(client, items, instructions, tools)
        fcalls = [o for o in response.output if o.type == "function_call"]
        if not fcalls:
            text = response.output_text or ""
            reason = response.status
            if response.status == "incomplete":
                why = getattr(response.incomplete_details, "reason", None)
                reason = why or "incomplete"
                text = ("요청이 콘텐츠 정책에 의해 차단되었습니다. 질문을 바꿔 다시 시도해 주세요."
                        if why == "content_filter" else text + "\n\n(응답이 길이 제한으로 잘렸습니다.)")
            return AgentResult(text, calls, ctx.state, ctx.changed, reason)

        # reasoning 항목까지 포함해 출력 전체를 다음 입력에 이어 붙인다
        items += [o.model_dump(exclude_none=True) for o in response.output]
        for fc in fcalls:
            try:
                tool_input = json.loads(fc.arguments or "{}")
            except json.JSONDecodeError:
                output, is_error, tool_input = json.dumps({"error": "인자 JSON 파싱 실패"}), True, {}
            else:
                output, is_error = run_tool(fc.name, tool_input, ctx)
            calls.append(ToolCall(fc.name, tool_input, output, is_error))
            if on_tool:
                on_tool(calls[-1])
            items.append({"type": "function_call_output", "call_id": fc.call_id, "output": output})

    return AgentResult(f"도구 호출이 최대 횟수({config.MAX_AGENT_TURNS}회)에 도달해 분석을 중단했습니다.",
                       calls, ctx.state, ctx.changed, "max_turns")
