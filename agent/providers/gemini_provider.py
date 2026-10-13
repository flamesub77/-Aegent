"""Gemini 어댑터 (google-genai): 함수 호출 루프. 자동 함수 호출은 끄고 도구는 registry가 실행한다.

Gemini 함수 선언은 OpenAPI 부분집합이라 additionalProperties 같은 키를 지운 스키마를 넘긴다.
"""
from google import genai
from google.genai import errors, types

import config
from agent.agent import AgentResult, ToolCall
from agent.prompts import build_system_prompt
from agent.providers import ProviderError, first_message, run_tool_json
from tools.registry import DashboardContext, tool_schemas

_DROP = {"additionalProperties", "strict"}


def _clean(schema):
    if isinstance(schema, dict):
        return {k: _clean(v) for k, v in schema.items() if k not in _DROP}
    if isinstance(schema, list):
        return [_clean(v) for v in schema]
    return schema


def _config(system: str, tools: bool = True):
    decls = [types.FunctionDeclaration(name=t["name"], description=t["description"], parameters=_clean(t["parameters"]))
             for t in tool_schemas()] if tools else None
    return types.GenerateContentConfig(
        system_instruction=system, max_output_tokens=config.MAX_TOKENS,
        tools=[types.Tool(function_declarations=decls)] if decls else None,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True) if decls else None)


def _why(e: Exception) -> str:
    code = getattr(e, "code", None)
    if code in (401, 403) or "API key" in str(e):
        return "Gemini API 키가 올바르지 않아"
    if code == 429:
        return "Gemini 요청 한도를 넘어"
    if code == 404:
        return "Gemini 모델 이름이 올바르지 않아"
    if code:
        return f"Gemini 오류({code})로"
    return "Gemini에 연결할 수 없어"


def run(question, state, history, api_key, model, on_tool=None) -> AgentResult:
    client = genai.Client(api_key=api_key)
    ctx = DashboardContext(state)
    cfg = _config(build_system_prompt())
    contents = [types.Content(role="model" if m["role"] == "assistant" else "user", parts=[types.Part(text=m["content"])])
                for m in (history or []) if m.get("content")]
    contents.append(types.Content(role="user", parts=[types.Part(text=first_message(question, state))]))
    calls: list[ToolCall] = []
    try:
        for _ in range(config.MAX_AGENT_TURNS):
            response = client.models.generate_content(model=model, contents=contents, config=cfg)
            fcalls = response.function_calls or []
            if not fcalls:
                return AgentResult(response.text or "", calls, ctx.state, ctx.changed, "completed")
            contents.append(response.candidates[0].content)
            parts = []
            for fc in fcalls:
                args, out, is_error = run_tool_json(fc.name, dict(fc.args or {}), ctx)
                calls.append(ToolCall(fc.name, args, out, is_error))
                if on_tool:
                    on_tool(calls[-1])
                parts.append(types.Part.from_function_response(name=fc.name, response={"result": out}))
            contents.append(types.Content(role="user", parts=parts))
    except (errors.APIError, OSError) as e:
        raise ProviderError(_why(e)) from e
    return AgentResult(f"도구 호출이 최대 횟수({config.MAX_AGENT_TURNS}회)에 도달해 분석을 중단했습니다.",
                       calls, ctx.state, ctx.changed, "max_turns")


def check_key(api_key: str) -> tuple[bool, str]:
    try:
        next(iter(genai.Client(api_key=api_key).models.list()), None)
        return True, "사용 가능"
    except (errors.APIError, OSError) as e:
        why = _why(e)
        return False, ("키가 올바르지 않아요." if "키" in why else f"{why} 확인하지 못했어요.")


def complete(api_key, model, system, prompt) -> str:
    try:
        r = genai.Client(api_key=api_key).models.generate_content(model=model, contents=prompt,
                                                                  config=_config(system, tools=False))
    except (errors.APIError, OSError) as e:
        raise ProviderError(_why(e)) from e
    return r.text or ""
