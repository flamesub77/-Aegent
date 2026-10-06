"""실행 모드에 따라 에이전트(OpenAI) 또는 오프라인 해석기로 답한다 (prd_v2 R4).

mode: "auto"(키가 있으면 에이전트, 실패하면 오프라인) · "agent" · "offline"(외부 통신 없음).
"""
import config
from agent import offline

MODE_LABEL = {"auto": "자동", "agent": "에이전트", "offline": "오프라인"}


def effective_mode(mode: str | None = None) -> str:
    """실제로 쓸 모드: 키가 없으면 에이전트를 쓸 수 없다."""
    mode = mode or config.APP_MODE
    if mode == "offline":
        return "offline"
    return "agent" if config.has_api_key() else "offline"


def answer(question: str, state: dict, history=None, mode: str | None = None, on_tool=None):
    """반환: (AgentResult, 실제 사용 모드, 안내 문구 또는 None)."""
    mode = mode or config.APP_MODE
    if effective_mode(mode) == "offline":
        notice = None if mode == "offline" else "OpenAI API 키가 없어 오프라인 해석기로 답했어요."
        return offline.answer(question, state, on_tool), "offline", notice
    try:
        from agent.agent import run_agent
        import openai
    except ImportError:
        return offline.answer(question, state, on_tool), "offline", "openai 패키지가 없어 오프라인 해석기로 답했어요."
    try:
        return run_agent(question, state, history, on_tool=on_tool), "agent", None
    except (openai.APIConnectionError, openai.APITimeoutError) as e:
        why = "OpenAI에 연결할 수 없어"
    except openai.AuthenticationError:
        why = "OpenAI API 키가 올바르지 않아"
    except openai.RateLimitError:
        why = "OpenAI 요청 한도를 넘어"
    except openai.APIStatusError as e:
        why = f"OpenAI 오류({e.status_code})로"
    return offline.answer(question, state, on_tool), "offline", f"{why} 오프라인 해석기로 대신 답했어요."
