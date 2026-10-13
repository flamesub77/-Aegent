"""OpenAI 어댑터: Responses API 함수 호출 루프는 agent/agent.py (v1부터 쓰던 것)."""
import openai
from openai import OpenAI

import config
from agent.providers import ProviderError


def _why(e: Exception) -> str:
    if isinstance(e, (openai.APIConnectionError, openai.APITimeoutError)):
        return "OpenAI에 연결할 수 없어"
    if isinstance(e, openai.AuthenticationError):
        return "OpenAI API 키가 올바르지 않아"
    if isinstance(e, openai.RateLimitError):
        return "OpenAI 요청 한도를 넘어"
    if isinstance(e, openai.APIStatusError):
        return f"OpenAI 오류({e.status_code})로"
    return "OpenAI 호출에 실패해"


def run(question, state, history, api_key, model, on_tool=None):
    from agent.agent import run_agent
    try:
        return run_agent(question, state, history, client=OpenAI(api_key=api_key), on_tool=on_tool, model=model)
    except openai.OpenAIError as e:
        raise ProviderError(_why(e)) from e


def check_key(api_key: str) -> tuple[bool, str]:
    try:
        OpenAI(api_key=api_key, timeout=15, max_retries=0).models.list()
        return True, "사용 가능"
    except openai.AuthenticationError:
        return False, "키가 올바르지 않아요."
    except (openai.APIConnectionError, openai.APITimeoutError):
        return False, "OpenAI에 연결할 수 없어요 (네트워크 확인)."
    except openai.APIStatusError as e:
        return False, f"확인 실패 (오류 {e.status_code})"


def complete(api_key, model, system, prompt) -> str:
    try:
        kw = dict(model=model, instructions=system, input=prompt, max_output_tokens=config.MAX_TOKENS)
        if config.REASONING_EFFORT:
            kw["reasoning"] = {"effort": "low"}
        return OpenAI(api_key=api_key).responses.create(**kw).output_text or ""
    except openai.OpenAIError as e:
        raise ProviderError(_why(e)) from e
