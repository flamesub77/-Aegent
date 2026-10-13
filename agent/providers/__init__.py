"""AI 제공자 어댑터 (prd_v5 H3): OpenAI · Claude(Anthropic) · Gemini.

도구 정의(tools/registry.py)와 시스템 프롬프트는 하나로 두고, 제공자마다 함수 호출 형식만 바꿔 준다.
각 SDK는 필요할 때만 불러오므로, 설치되지 않은 제공자는 그 제공자만 쓸 수 없고 앱은 그대로 뜬다.
오류는 ProviderError(쉬운 말 이유)로 바꿔 올리고, router가 오프라인 해석기로 대신 답한다.
"""
import importlib
import importlib.util
import json

import config

MODULES = {"openai": "agent.providers.openai_provider", "anthropic": "agent.providers.anthropic_provider",
           "gemini": "agent.providers.gemini_provider"}
PACKAGES = {"openai": "openai", "anthropic": "anthropic", "gemini": "google.genai"}
PIP_NAME = {"openai": "openai", "anthropic": "anthropic", "gemini": "google-genai"}


class ProviderError(Exception):
    """제공자 호출 실패. str(e)는 "OpenAI에 연결할 수 없어"처럼 문장 앞부분 (뒤에 "오프라인 해석기로 …"를 붙인다)."""


def is_auth_error(message: str | None) -> bool:
    """키가 거부된 실패인지 (어댑터들의 _why 문장 기준)."""
    return bool(message) and "키가 올바르지 않아" in message


def label(provider: str) -> str:
    return config.PROVIDERS.get(provider, (provider,))[0]


def installed(provider: str) -> bool:
    try:
        return importlib.util.find_spec(PACKAGES[provider]) is not None
    except (ModuleNotFoundError, KeyError, ValueError):
        return False


def _module(provider: str):
    if provider not in MODULES:
        raise ProviderError(f"알 수 없는 AI({provider})라서")
    if not installed(provider):
        raise ProviderError(f"{PIP_NAME[provider]} 패키지가 설치되지 않아")
    try:
        return importlib.import_module(MODULES[provider])
    except ImportError as e:
        raise ProviderError(f"{PIP_NAME[provider]} 패키지를 불러오지 못해") from e


def run(provider: str, question: str, state: dict, history=None, api_key: str | None = None,
        model: str | None = None, on_tool=None):
    """에이전트 실행 → AgentResult. 실패하면 ProviderError."""
    mod = _module(provider)
    key = config.resolve_api_key(api_key, provider)
    if not key:
        raise ProviderError(f"{label(provider)} API 키가 없어")
    model = config.provider_model(provider, model)
    if not model:
        raise ProviderError(f"{label(provider)} 모델 이름(.env의 {provider.upper()}_MODEL)이 없어")
    return mod.run(question, state, history, key, model, on_tool)


def check_key(provider: str, api_key: str) -> tuple[bool, str]:
    """키 확인: 모델 목록 조회처럼 가벼운 호출. 키는 기록하지 않는다."""
    try:
        return _module(provider).check_key(api_key)
    except ProviderError as e:
        return False, f"{e} 확인할 수 없어요."


def complete(provider: str, api_key: str | None, system: str, prompt: str, model: str | None = None) -> str:
    """도구 없이 문장만 받는다 (AI 보고서 요약). 실패하면 ProviderError."""
    key = config.resolve_api_key(api_key, provider)
    if not key:
        raise ProviderError(f"{label(provider)} API 키가 없어")
    return _module(provider).complete(key, config.provider_model(provider, model), system, prompt)


def run_tool_json(name: str, args, ctx):
    """공통 도구 실행: (입력 dict, 출력 JSON 문자열, 오류 여부)."""
    from tools.registry import run_tool
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            return {}, json.dumps({"error": "인자 JSON 파싱 실패"}, ensure_ascii=False), True
    args = dict(args or {})
    out, is_error = run_tool(name, args, ctx)
    return args, out, is_error


def first_message(question: str, state: dict) -> str:
    from tools import dashboard_state as ds
    return f"[현재 대시보드 상태] {json.dumps(ds.describe(state), ensure_ascii=False)}\n\n{question}"
