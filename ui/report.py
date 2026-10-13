"""🤖 AI 보고서 팝업 (prd_v4 P1 → prd_v5 R1): ① 항목 체크리스트 → ② 미리보기 → ③ PPT 다운로드.

AI 모드(키 있음)면 해석·요약·다음 조치 문장을 고른 AI가 쓴다. 숫자는 분석 결과만 넘기고 원본 행은 보내지 않는다.
AI 호출이 실패하거나 오프라인이면 규칙 문장으로 만든다.
"""
import streamlit as st

from agent import providers
from tools import report_ppt as R
from ui import ai


def _ai_text(chosen: list[str], ctx: dict) -> tuple[dict | None, str | None]:
    """(AI 문장, 실패 안내). 오프라인이면 (None, None)."""
    if ai.effective() != "agent":
        return None, None
    try:
        text = providers.complete(ai.provider(), ai.user_key(), R.AI_SYSTEM, R.ai_prompt(chosen, ctx), ai.model())
    except providers.ProviderError as e:
        if providers.is_auth_error(str(e)):
            ai.mark_rejected()
            return None, (f"{e} 규칙 문장으로 만들었어요. 키가 만료·폐기된 것 같아요. 오른쪽 위 🔑에서 새 키를 넣으면 "
                          "AI가 문장을 써요.")
        return None, f"{e} 규칙 문장으로 만들었어요."
    parsed = R.parse_ai(text)
    return parsed, None if parsed else "AI 응답 형식이 맞지 않아 규칙 문장으로 만들었어요."


@st.dialog("🤖 AI 보고서 (PPT)", width="large")
def dialog(ctx: dict):
    who = f"AI({ai.label()})가 해석 문장을 써요" if ai.effective() == "agent" else "오프라인이라 규칙 문장으로 써요"
    st.caption(f"`{R.TEMPLATE.name}` 양식으로 한 장에 그래프 2개씩, 고른 만큼 만들어요. 지금 화면 조건으로 계산하고, {who}.")
    st.markdown("**① 넣을 항목**")
    avail = R.available(ctx)
    cols = st.columns(2)
    chosen = []
    for i, k in enumerate(avail):
        name, default = R.ITEMS[k]
        if cols[i % 2].checkbox(name, value=default, key=f"rep_{k}"):
            chosen.append(k)
    missing = [R.ITEMS[k][0] for k in R.ITEMS if k not in avail]
    if missing:
        st.caption("지금 조건에서는 만들 수 없는 항목: " + ", ".join(missing))
    msg = R.check_count(len(chosen))
    if msg:
        st.warning(msg, icon=":material/info:")
        return
    st.caption(f"{len(chosen)}개 → {(len(chosen) + 1) // 2}장")
    sig = (tuple(chosen), ctx["signature"], ai.effective(), ai.provider())
    if st.button("② 미리보기 만들기", type="primary", width="stretch") or st.session_state.get("rep_sig") == sig:
        if st.session_state.get("rep_sig") != sig:
            with st.spinner("AI가 문장을 쓰고 그래프를 그리는 중…" if ai.effective() == "agent" else "그래프를 그리는 중…"):
                ai_text, warn = _ai_text(chosen, ctx)
                ctx = ctx | {"ai_text": ai_text}
                page_list = R.pages(chosen, ctx)
                st.session_state["rep_by"] = "ai" if ai_text else "rule"
                st.session_state["rep_warn"] = warn
                st.session_state["rep_previews"] = R.preview_pngs(page_list, ctx["footer"])
                st.session_state["rep_pptx"] = R.build_pptx(page_list, ctx["footer"])
                st.session_state["rep_sig"] = sig
        st.markdown(f":blue-badge[:material/smart_toy: AI 작성 · {ai.label()}]" if st.session_state.get("rep_by") == "ai"
                    else ":gray-badge[:material/rule: 규칙 작성]")
        if st.session_state.get("rep_warn"):
            st.caption(f"⚠️ {st.session_state['rep_warn']}")
        previews = st.session_state["rep_previews"]
        tabs = st.tabs([f"{i + 1}장" for i in range(len(previews))])
        for tab, png in zip(tabs, previews):
            tab.image(png, width="stretch")
        st.download_button("③ PPT 다운로드", st.session_state["rep_pptx"], R.filename(ctx["grade"]),
                           "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                           type="primary", width="stretch", icon=":material/download:")
