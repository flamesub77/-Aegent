"""머리글: "{강종} 품질 현황" 제목 + 오른쪽 위 같은 크기 버튼 4개 (prd_v5 H1·H3).

◐ 테마(자동·라이트·다크) · 🔑 AI 키(OpenAI·Claude·Gemini) · 🤖 AI 보고서 · 🔗 링크.
"""
from urllib.parse import urlencode

import streamlit as st

import config
from agent import providers
from ui import ai, session
from ui.theme import THEMES, theme_params

STATUS_BADGE = {"ok": ":green-badge[:material/check_circle: 사용 가능]", "bad": ":red-badge[:material/error: 키 오류]",
                "env": ":blue-badge[:material/key: .env 키 사용 중]", "none": ":gray-badge[키 없음]",
                "pkg": ":orange-badge[패키지 없음]"}
KEY_HINT = {"openai": "sk-...", "anthropic": "sk-ant-...", "gemini": "AIza..."}


def key_status(p: str) -> str:
    if not providers.installed(p):
        return "pkg"
    if ai.user_key(p):
        return st.session_state["api_status"].get(p, "ok")
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
    with st.popover("◐", help=f"테마: {THEMES[current]}", width="stretch"):
        for choice, label in THEMES.items():
            href = "?" + urlencode(base | theme_params(choice))
            st.html(f"<a class='theme-item{' on' if choice == current else ''}' href='{href}' target='_self'>"
                    f"{'✓ ' if choice == current else ''}{label}</a>")


def key_popover():
    with st.popover("🔑", help="AI 키 (OpenAI · Claude · Gemini). 키는 앱이 켜져 있는 동안 메모리에만 둬요.", width="stretch"):
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


def render(title: str, theme: str, query: dict) -> bool:
    """반환: 🤖 AI 보고서 버튼을 눌렀는지 (팝업은 app.py가 연다)."""
    left, b1, b2, b3, b4 = st.columns([8.6, 0.62, 0.62, 1.7, 0.62], vertical_alignment="bottom", gap="small")
    left.title(title)
    with b1:
        theme_menu(theme, query)
    with b2:
        key_popover()
    report = b3.button("🤖 AI 보고서", width="stretch", help="회사 PPT 양식으로 그래프 위주 2~3장 (항목 선택·미리보기·다운로드). "
                                                        "AI 모드면 요약 문장을 AI가 써요.")
    with b4.popover("🔗", help="지금 필터로 열리는 링크 (세션 정보는 빠짐)", width="stretch"):
        st.caption("이 링크를 열면 지금과 같은 필터·화면으로 열려요. 대화·업로드 파일·API 키는 포함되지 않아요.")
        st.code(session.share_link(), language=None, wrap_lines=True)
    return report
