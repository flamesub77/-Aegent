"""실행 모드에 따라 AI 에이전트 또는 오프라인 해석기로 답한다 (prd_v2 R4 → prd_v5 H2·H3).

mode: "ai"(AI 모드: 쓸 수 있는 키가 있으면 고른 AI, 없거나 실패하면 오프라인) · "offline"(외부 통신 없음).
v4 값 "auto"·"agent"는 "ai"로 본다. provider: openai | anthropic | gemini.
"""
import config
from agent import offline

MODE_LABEL = {"offline": "오프라인", "ai": "AI 모드"}


def normalize(mode: str | None) -> str:
    mode = (mode or config.APP_MODE or "ai").lower()
    return "offline" if mode == "offline" else "ai"


def effective_mode(mode: str | None = None, api_key: str | None = None, provider: str | None = None) -> str:
    """실제로 쓸 모드 ("agent" | "offline"): 키가 없으면 AI를 쓸 수 없다. api_key: 화면에서 입력한 키."""
    if normalize(mode) == "offline":
        return "offline"
    return "agent" if config.has_api_key(api_key, provider=provider or config.DEFAULT_PROVIDER) else "offline"


def check_key(api_key: str, provider: str = "openai") -> tuple[bool, str]:
    """키 확인: 모델 목록 조회처럼 가벼운 호출. 반환 (사용 가능 여부, 안내). 키는 기록하지 않는다."""
    from agent import providers
    return providers.check_key(provider, api_key)


def answer(question: str, state: dict, history=None, mode: str | None = None, on_tool=None,
           api_key: str | None = None, provider: str | None = None, model: str | None = None):
    """반환: (AgentResult, 실제 사용 모드, 안내 문구 또는 None). api_key: 화면에서 입력한 키 (없으면 .env)."""
    from agent import providers
    provider = provider or config.DEFAULT_PROVIDER
    if effective_mode(mode, api_key, provider) == "offline":
        notice = None if normalize(mode) == "offline" else \
            f"{providers.label(provider)} API 키가 없어 오프라인 해석기로 답했어요."
        return offline.answer(question, state, on_tool), "offline", notice
    try:
        return providers.run(provider, question, state, history, api_key, model, on_tool), "agent", None
    except providers.ProviderError as e:
        return offline.answer(question, state, on_tool), "offline", f"{e} 오프라인 해석기로 대신 답했어요."
