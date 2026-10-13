"""AI 모드 설정 (prd_v5 H2·H3): 오프라인/AI 모드, 제공자(OpenAI·Claude·Gemini)별 키·모델.

키는 서버 메모리 세션(ui/session.py KEPT)에만 둔다. 파일·로그·주소창에 남기지 않는다.
session_state: run_mode("offline"|"ai"), ai_provider, api_keys{제공자: 키}, api_status{제공자: ok|bad}, ai_models{제공자: 모델}
"""
import streamlit as st

import config
from agent import providers, router


def init():
    st.session_state.setdefault("api_keys", {})
    st.session_state.setdefault("api_status", {})
    st.session_state.setdefault("ai_models", {})
    old = st.session_state.pop("api_key", None)  # v4 세션의 OpenAI 키
    if old and isinstance(old, str):
        st.session_state["api_keys"].setdefault("openai", old)
    if not isinstance(st.session_state.get("api_status"), dict):
        st.session_state["api_status"] = {}
    st.session_state.setdefault("ai_provider", config.DEFAULT_PROVIDER)
    if "run_mode" not in st.session_state:  # 기본: 키가 있으면 AI 모드, 없으면 오프라인 (prd_v5 H2)
        st.session_state["run_mode"] = "ai" if config.APP_MODE == "ai" and any_key() else "offline"
    st.session_state["run_mode"] = router.normalize(st.session_state["run_mode"])


def provider() -> str:
    return st.session_state.get("ai_provider") or config.DEFAULT_PROVIDER


def user_key(p: str | None = None) -> str | None:
    return (st.session_state.get("api_keys") or {}).get(p or provider())


def model(p: str | None = None) -> str:
    p = p or provider()
    return config.provider_model(p, (st.session_state.get("ai_models") or {}).get(p))


def has_key(p: str | None = None) -> bool:
    return config.has_api_key(user_key(p), provider=p or provider())


def any_key() -> bool:
    return any(has_key(p) for p in config.PROVIDERS)


def mode() -> str:
    return st.session_state.get("run_mode", "offline")


def effective() -> str:
    """실제로 쓸 모드: "agent" | "offline"."""
    return router.effective_mode(mode(), user_key(), provider())


def label() -> str:
    """배지·팝업용: "Claude · claude-sonnet-5-5"."""
    return f"{providers.label(provider())} · {model() or '모델 미지정'}"


def kwargs() -> dict:
    """router.answer에 넘길 값."""
    return {"api_key": user_key(), "provider": provider(), "model": model()}
