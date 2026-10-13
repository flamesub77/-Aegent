"""머리글: "{강종} 품질 현황" 제목 + 오른쪽 위 같은 높이 버튼 (prd_v5 H1·H3 → prd_v7 H1).

◐ 테마(자동·라이트·다크) · 🔑 AI 키(OpenAI·Claude·Gemini) · [오프라인 | AI 모드] · 🔗 링크.
prd_v8: 이 버튼들은 맨 위 고정 상단바(app.py)에 `toolbar()`로 그린다. 제목·🤖 AI 보고서는 app.py.
"""
from urllib.parse import urlencode

import streamlit as st

import config
from agent import providers
from ui import ai, session
from ui.theme import THEMES, theme_params

STATUS_BADGE = {"ok": ":green-badge[:material/check_circle: 사용 가능]", "bad": ":red-badge[:material/error: 키 오류]",
                "env": ":blue-badge[:material/key: .env 키 사용 중]", "none": ":gray-badge[키 없음]",
                "pkg": ":orange-badge[패키지 없음]", "env_bad": ":red-badge[:material/error: .env 키 거부됨]"}
KEY_HINT = {"openai": "sk-...", "anthropic": "sk-ant-...", "gemini": "AIza..."}


def key_status(p: str) -> str:
    if not providers.installed(p):
        return "pkg"
    if ai.user_key(p):
        return st.session_state["api_status"].get(p, "ok")
    if ai.env_rejected(p):
        return "env_bad"
    return "env" if config.has_api_key(provider=p) else "none"


def _check_key(p: str):
    key = (st.session_state.get(f"api_key_input_{p}") or "").strip()
    st.session_state[f"api_key_input_{p}"] = ""  # 입력칸에 남기지 않는다
    if not key:
        return
    ok, msg = providers.check_key(p, key)
    if ok:
        st.session_state["api_keys"][p] = key
        st.session_state["api_status"][p] = "ok"
        (st.session_state.get("env_bad") or {}).pop(p, None)
        st.session_state["ai_provider"] = p  # 방금 확인한 AI를 쓰고, AI 모드로 (prd_v5 H2)
        st.session_state["run_mode"] = "ai"
    st.session_state["api_msg"] = (p, "ok" if ok else "bad", msg)


def _clear_key(p: str):
    st.session_state["api_keys"].pop(p, None)
    st.session_state["api_status"].pop(p, None)
    st.session_state["api_msg"] = (p, "ok", "키를 지웠어요.")


def _set_model(p: str):
    v = (st.session_state.get(f"ai_model_{p}") or "").strip()
    st.session_state["ai_models"][p] = v


def theme_menu(current: str, query: dict):
    """◐ 하나짜리 드롭다운: 같은 주소에 테마 옵션만 바꿔 다시 연다 (세션 ID가 있어 화면은 유지)."""
    base = {k: v for k, v in query.items() if k not in ("embed", "embed_options", "th")}
    with st.popover(":material/contrast:", help=f"테마: {THEMES[current]}", width="content"):
        for choice, label in THEMES.items():
            href = "?" + urlencode(base | theme_params(choice))
            st.html(f"<a class='theme-item{' on' if choice == current else ''}' href='{href}' target='_self'>"
                    f"{'✓ ' if choice == current else ''}{label}</a>")


def key_popover():
    with st.popover(":material/key:", help="AI 키 (OpenAI · Claude · Gemini). 키는 앱이 켜져 있는 동안 메모리에만 둬요.",
                    width="content"):
        st.markdown("**AI 키**")
        names = list(config.PROVIDERS)
        usable = [p for p in names if ai.has_key(p) and providers.installed(p)]
        if usable:
            if ai.provider() not in usable:
                st.session_state["ai_provider"] = usable[0]
            st.selectbox("AI 모드에서 쓸 AI", usable, key="ai_provider", format_func=providers.label)
        else:
            st.caption("키를 넣으면 AI 모드로 바뀌어요.")
        tabs = st.tabs([providers.label(p) for p in names])
        for tab, p in zip(tabs, names):
            with tab:
                status = key_status(p)
                st.markdown(STATUS_BADGE[status])
                if status == "pkg":
                    st.caption(f"`pip install {providers.PIP_NAME[p]}` 후 앱을 다시 켜면 쓸 수 있어요.")
                    continue
                if ai.user_key(p):
                    st.caption(f"입력한 키: `{config.mask_key(ai.user_key(p))}`")
                elif status == "env":
                    st.caption("`.env` 파일의 키를 쓰고 있어요. 다른 키를 쓰려면 아래에 넣으세요.")
                elif status == "env_bad":
                    st.caption("`.env` 파일의 키를 제공자가 거부했어요(만료·폐기된 키). 새 키를 아래에 넣거나 `.env`를 고친 뒤 앱을 다시 켜세요.")
                st.text_input("키", type="password", key=f"api_key_input_{p}", placeholder=KEY_HINT[p],
                              label_visibility="collapsed")
                c1, c2 = st.columns(2)
                c1.button("확인", key=f"key_ok_{p}", on_click=_check_key, args=(p,), type="primary", width="stretch")
                c2.button("지우기", key=f"key_del_{p}", on_click=_clear_key, args=(p,), width="stretch",
                          disabled=not ai.user_key(p))
                st.session_state.setdefault(f"ai_model_{p}", ai.model(p))
                st.text_input("모델", key=f"ai_model_{p}", on_change=_set_model, args=(p,),
                              help="비워 두면 .env 기본값을 써요.")
                if (msg := st.session_state.get("api_msg")) and msg[0] == p:
                    (st.success if msg[1] == "ok" else st.error)(msg[2])
        st.caption("키는 파일·로그·주소창에 남기지 않아요. 새로 고침해도 8시간 동안 유지되고, 앱을 끄면 사라져요. "
                   "오프라인 모드에서는 키가 있어도 외부로 보내지 않아요.")


def toolbar(theme: str, query: dict, mode_widget=None):
    """상단바 오른쪽 도구 (prd_v8 U1): ◐ 테마 · 🔑 API 키 · [오프라인 | AI 모드] · 🔗 공유.
    호출한 쪽의 가로 컨테이너 안에 내용 폭으로 차례로 그린다 (같은 높이 36px는 ui/theme.py .st-key-tools)."""
    theme_menu(theme, query)
    key_popover()
    if mode_widget:
        mode_widget()
    with st.popover(":material/link:", help="지금 필터로 열리는 링크 (세션 정보는 빠짐)", width="content"):
        st.caption("이 링크를 열면 지금과 같은 필터·화면으로 열려요. 대화·업로드 파일·API 키는 포함되지 않아요.")
        st.code(session.share_link(), language=None, wrap_lines=True)
