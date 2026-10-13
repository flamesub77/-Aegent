"""Claude(Anthropic) 어댑터: Messages API 도구 사용 루프 (직접 루프).

- 도구 정의는 registry의 OpenAI 형식을 name·description·input_schema로 바꿔 쓴다.
- 응답 content는 그대로 다음 요청에 붙인다 (thinking·fallback 블록 보존).
- 거절(refusal) 대비: 지원 모델이면 서버 쪽 fallbacks="default"를 켠다 (Claude API 전용 베타).
"""
import anthropic

import config
from agent.agent import AgentResult, ToolCall
from agent.prompts import build_system_prompt
from agent.providers import ProviderError, first_message, run_tool_json
from tools.registry import DashboardContext, tool_schemas

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}
EFFORT = "medium"  # 여러 단계 도구 호출에 맞춘 기본 (환경변수로 바꿀 수 있음)


def _tools() -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tool_schemas()]


def _why(e: Exception) -> str:
    if isinstance(e, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return "Claude에 연결할 수 없어"
    if isinstance(e, anthropic.AuthenticationError):
        return "Claude API 키가 올바르지 않아"
    if isinstance(e, anthropic.RateLimitError):
        return "Claude 요청 한도를 넘어"
    if isinstance(e, anthropic.NotFoundError):
        return "Claude 모델 이름이 올바르지 않아"
    if isinstance(e, anthropic.APIStatusError):
        return f"Claude 오류({e.status_code})로"
    return "Claude 호출에 실패해"


def _create(client, model: str, **kw):
    kw.update(model=model, max_tokens=16000, output_config={"effort": EFFORT})
    if model in FALLBACK_MODELS:
        return client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kw)
    return client.messages.create(**kw)


def _text(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text")


def run(question, state, history, api_key, model, on_tool=None) -> AgentResult:
    client = anthropic.Anthropic(api_key=api_key)
    ctx = DashboardContext(state)
    system, tools = build_system_prompt(), _tools()
    messages = [{"role": m["role"], "content": m["content"]} for m in (history or []) if m.get("content")]
    messages.append({"role": "user", "content": first_message(question, state)})
    calls: list[ToolCall] = []
    try:
        for _ in range(config.MAX_AGENT_TURNS):
            response = _create(client, model, system=system, tools=tools, messages=messages)
            if response.stop_reason == "refusal":
                return AgentResult("요청이 안전 정책에 의해 거절되었습니다. 질문을 바꿔 다시 시도해 주세요.",
                                   calls, ctx.state, ctx.changed, "refusal")
            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                continue
            uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not uses:
                text = _text(response)
                if response.stop_reason == "max_tokens":
                    text += "\n\n(응답이 길이 제한으로 잘렸습니다.)"
                return AgentResult(text, calls, ctx.state, ctx.changed, response.stop_reason)
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for u in uses:  # 병렬 호출 결과는 한 user 메시지에 모아 돌려준다
                args, out, is_error = run_tool_json(u.name, u.input, ctx)
                calls.append(ToolCall(u.name, args, out, is_error))
                if on_tool:
                    on_tool(calls[-1])
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": out, "is_error": is_error})
            messages.append({"role": "user", "content": results})
    except anthropic.AnthropicError as e:
        raise ProviderError(_why(e)) from e
    return AgentResult(f"도구 호출이 최대 횟수({config.MAX_AGENT_TURNS}회)에 도달해 분석을 중단했습니다.",
                       calls, ctx.state, ctx.changed, "max_turns")


def check_key(api_key: str) -> tuple[bool, str]:
    try:
        anthropic.Anthropic(api_key=api_key, timeout=15, max_retries=0).models.list(limit=1)
        return True, "사용 가능"
    except anthropic.AuthenticationError:
        return False, "키가 올바르지 않아요."
    except (anthropic.APIConnectionError, anthropic.APITimeoutError):
        return False, "Claude에 연결할 수 없어요 (네트워크 확인)."
    except anthropic.APIStatusError as e:
        return False, f"확인 실패 (오류 {e.status_code})"


def complete(api_key, model, system, prompt) -> str:
    try:
        r = _create(anthropic.Anthropic(api_key=api_key), model, system=system,
                    messages=[{"role": "user", "content": prompt}])
    except anthropic.AnthropicError as e:
        raise ProviderError(_why(e)) from e
    if r.stop_reason == "refusal":
        raise ProviderError("Claude가 요청을 거절해")
    return _text(r)
