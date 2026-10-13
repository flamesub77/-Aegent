"""AI 분석 도우미: 오른쪽 아래 떠 있는 아이콘 → 팝업 (prd_v3 U6). 에이전트/오프라인 해석기 (prd_v2 R4).

팝업은 기본으로 닫혀 있다. 질문하면 답한 뒤 앱 전체를 다시 그려 대시보드를 바꾸고, 팝업은 다시 연다.
대화는 session_state["chat"]에 있고 ui/session.py가 새로 고침 뒤에도 복원한다.
"""
import json
from datetime import datetime

import streamlit as st

import config
from agent import offline, providers, router
from tools.datasource import get_source
from ui import ai as AI
from ui.common import STEP_LABEL, badge

QUICK_ASKS = ["지금 화면을 해석해줘", "산점도 x축을 소둔온도로 바꿔줘", "TS로 바꿔서 보여줘"]


def ask(q: str):
    """질문을 넣고 팝업을 연다 (사이드바 데모 질문·예시 버튼)."""
    st.session_state["queued"] = q
    st.session_state["agent_open"] = True


def _close():
    st.session_state["agent_open"] = False
    st.session_state["fab_seen"] = _n_answers()


def _n_answers() -> int:
    return sum(1 for m in st.session_state.get("chat", []) if m["role"] == "assistant")


# 스크롤하면 아이콘·말풍선이 살짝 늦게 따라와 제자리로 돌아오는 효과 (prd_v4 A1).
# st.html(unsafe_allow_javascript=True)로 페이지에 직접 넣고, 스크롤 리스너는 한 번만 붙인다.
_LAG_JS = """
<script>
(function () {
  const doc = document;
  const main = doc.querySelector('[data-testid="stMain"]');
  if (!main || main.__fabLag) return;
  main.__fabLag = true;
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  let last = main.scrollTop, timer = null;
  main.addEventListener('scroll', function () {
    const d = main.scrollTop - last; last = main.scrollTop;
    const off = Math.max(-36, Math.min(36, -d * 0.8));
    const els = [doc.querySelector('.st-key-agent_fab'), doc.querySelector('.st-key-agent_bubble')];
    els.forEach(function (el) { if (el) { el.style.transition = 'none';
      el.style.transform = 'translateY(' + off + 'px) scale(0.93)'; } });
    clearTimeout(timer);
    timer = setTimeout(function () { els.forEach(function (el) { if (el) {
      el.style.transition = 'transform .45s cubic-bezier(.2,.8,.2,1)'; el.style.transform = 'none'; } }); }, 90);
  }, {passive: true});
})();
</script>
"""


def fab(run_mode: str, api_key: str | None):
    """떠 있는 아이콘 (밝은색). 새 답변 수 배지, 오프라인 표시, 마우스를 올리면 말풍선, 스크롤 지연 움직임."""
    offline_now = AI.effective() == "offline"
    if st.button("🤖", key="agent_fab", help="AI에게 묻기"):
        st.session_state["agent_open"] = True
    unread = _n_answers() - st.session_state.get("fab_seen", 0)
    html = "<div class='fab-tip'>AI에게 묻기</div>"
    if unread > 0 and not st.session_state.get("agent_open"):
        html += f"<div class='fab-badge'>{unread}</div>"
    if offline_now:
        html += ("<div class='fab-off'>오프라인</div><style>.st-key-agent_fab button{border-color:#94A3B8 !important;"
                 "filter: saturate(.35);}</style>")
    st.html(html)
    st.html(_LAG_JS, unsafe_allow_javascript=True)


def _bubble_off():
    st.session_state["bubble_off"] = True


def bubble(questions: list[str], signature: str):
    """화면이 바뀌면 아이콘을 누르기 전에 추천 질문을 말풍선으로 (prd_v4 A2). 같은 화면 조건에서는 한 번만, 8초 뒤 사라짐."""
    if (not questions or st.session_state.get("agent_open") or st.session_state.get("bubble_off")
            or st.session_state.get("bubble_sig") == signature):
        return
    st.session_state["bubble_sig"] = signature
    with st.container(key="agent_bubble"):
        st.markdown("💡 **이런 걸 물어보세요**")
        for i, q in enumerate(questions[:2]):
            st.button(q, key=f"bubble_q{i}", on_click=ask, args=(q,), width="stretch")
        c1, c2 = st.columns([3, 1])
        c1.button("다시 보지 않기", key="bubble_never", on_click=_bubble_off, type="tertiary")
        c2.button("✕", key="bubble_close", type="tertiary", help="닫기")


def _report_card(rep: dict):
    j = rep.get("judgement")
    if j and j.get("shift") is not None:
        st.markdown(f"{badge(j['judgement'])} {j['property'].replace('YS', 'YP')} {j['shift']:+g}"
                    + (f" · 만족률 {j['spec_rate']}%" if j.get("spec_rate") is not None else ""))
    if rep.get("causes"):
        st.markdown(" ".join(f":{'blue' if c['mechanism'] == '일치' else 'gray'}-badge[{c['rank']}. {c['label']}]"
                             for c in rep["causes"]))
    if d := rep.get("defect"):
        tops = " ".join(f":blue-badge[{f['label']}]" for f in d["top_factors"][:2])
        st.markdown(f":red-badge[{d['type']} {d['rate_baseline_pct']}% → {d['rate_target_pct']}%] {tops}")
    for c in rep.get("coils", [])[:3]:
        tops = " ".join(f":gray-badge[{f['label']}]" for f in c["top_factors"][:2])
        st.markdown(f":orange-badge[{c['coil_no']}] {tops}")


def _message_md(q: str, m: dict) -> str:
    steps = "\n".join(f"- {STEP_LABEL.get(c['name'], c['name'])}: `{json.dumps(c['input'], ensure_ascii=False, default=str)}`"
                      for c in m.get("tools", []))
    who = m.get("ai") or ("AI" if m.get("mode") == "agent" else "오프라인 해석기")
    return (f"# 원인분석 리포트\n\n질문: {q}\n\n작성 {datetime.now():%Y-%m-%d %H:%M} · {who} · {get_source().name}\n\n"
            f"{m['content']}\n\n## 분석 과정\n\n{steps}\n")


def _examples() -> list[str]:
    ex = list(QUICK_ASKS)
    df = get_source().coils
    if "trial_flag" in df and (df["trial_flag"] == "Y").any():
        ex.append(f"{df.loc[df['trial_flag'] == 'Y', 'coil_no'].iloc[0]} 코일 양산이랑 비교해줘")
    return ex


@st.dialog("AI 분석 도우미", width="large", on_dismiss=_close)
def popup(state: dict, run_mode: str, api_key: str | None):
    with st.container(key="agent_panel"):
        render(state, run_mode, api_key)


def render(state: dict, run_mode: str, api_key: str | None = None):
    eff = AI.effective()
    st.caption(f"🤖 AI 모드 · {AI.label()} · 질문하면 해석하고 대시보드 조건을 바꿔줘요." if eff == "agent" else
               "🔒 오프라인 · 외부 통신 없이 질문에서 강종·기간·재질·결함·코일번호를 찾아 대시보드를 바꾸고 규칙대로 해석해요. "
               "AI로 답하게 하려면 위 고정바에서 AI 모드를 고르고 🔑에 키를 넣으세요.")
    question = st.session_state.pop("chat_q", None) or st.session_state.pop("queued", None)
    box = st.container(height=480, border=True)
    with box:
        if not st.session_state.chat and not question:
            st.markdown("**이렇게 물어보세요**")
            st.markdown("- 원인 분석: *\"5월 CAL 590C 항복강도가 낮은데 원인이 뭐야?\"*\n"
                        "- 단일 코일: *\"C2604xxxxx 코일 양산이랑 비교해줘\"*\n"
                        "- 그래프 조작: *\"산점도 x축을 소둔온도로 바꿔줘\"*\n- 모델: *\"랜덤포레스트로 원인 순위 봐줘\"*")
            for i, q in enumerate(_examples()):
                st.button(q, key=f"quick{i}", on_click=ask, args=(q,), width="stretch")
        prev_q = None
        for i, m in enumerate(st.session_state.chat):
            with st.chat_message(m["role"]):
                if m["role"] == "user":
                    prev_q = m["content"]
                    st.markdown(m["content"])
                    continue
                rep = m.get("report") or {}
                if m.get("mode") == "offline" and rep.get("recognized"):
                    st.markdown(" ".join(f":green-badge[{x}]" for x in rep["recognized"]))
                _report_card(rep)
                st.markdown(m["content"])
                if m.get("error"):
                    continue
                if m.get("mode") == "offline" and not rep.get("understood", True):
                    for j, q in enumerate(offline.EXAMPLES[:4]):
                        st.button(q, key=f"ex_{i}_{j}", on_click=ask, args=(q,), width="stretch")
                c1, c2 = st.columns([3, 2])
                with c1.popover(f"분석 과정 {len(m.get('tools', []))}단계", width="stretch"):
                    for c in m.get("tools", []):
                        st.markdown(f"**{STEP_LABEL.get(c['name'], c['name'])}** "
                                    f"{':red-badge[오류]' if c['is_error'] else ''}")
                        st.code(json.dumps(c["input"], ensure_ascii=False, default=str), language="json")
                c2.download_button("리포트", _message_md(prev_q or "", m), f"agent_report_{i}.md", "text/markdown",
                                   key=f"dl_msg{i}", width="stretch", icon=":material/download:")
    pending = st.session_state.get("ext_pending")
    if pending:  # 내 파일 + 에이전트: 외부 전송을 한 번 확인 (팝업 안이라 다이얼로그 대신 인라인)
        st.warning(f"지금 **내 파일** 데이터로 분석 중이고 **AI 모드**예요. 질문과 분석 결과 요약(평균·순위·"
                   f"코일번호 등)이 {AI.label()}로 보내져요. 원본 행 데이터 전체는 보내지 않아요.", icon=":material/cloud_upload:")
        c1, c2 = st.columns(2)
        if c1.button("전송하고 분석", type="primary", width="stretch"):
            st.session_state["ext_ok"] = True
            question = st.session_state.pop("ext_pending")
        elif c2.button("오프라인으로 답변", width="stretch"):
            st.session_state["force_offline_once"] = True
            question = st.session_state.pop("ext_pending")
    with st.form("ask_form", clear_on_submit=True, border=False):
        c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
        typed = c1.text_input("질문", placeholder="대시보드에 대해 질문하세요", label_visibility="collapsed")
        if c2.form_submit_button("보내기", type="primary", width="stretch") and typed.strip():
            question = typed.strip()
    if question:
        mode = run_mode
        if st.session_state.pop("force_offline_once", False):
            mode = "offline"
        elif (get_source().kind == "upload" and AI.effective() == "agent"
              and not st.session_state.get("ext_ok")):
            st.session_state["ext_pending"] = question
            st.rerun(scope="fragment")
        _answer(question, state, mode, api_key, box)
    if st.session_state.chat:
        st.button("대화 지우기", on_click=lambda: st.session_state.update(chat=[], fab_seen=0), width="stretch",
                  icon=":material/delete_sweep:")


def _answer(question: str, state: dict, mode: str, api_key: str | None, box):
    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.chat if not m.get("error")][-8:]
    st.session_state.chat.append({"role": "user", "content": question})
    with box:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            status = st.status("분석을 시작합니다…", expanded=True)

            def on_tool(c):
                label = STEP_LABEL.get(c.name, c.name)
                status.update(label=f"{label} 중…")
                status.write(f"{'⚠️' if c.is_error else '✓'} {label}")

            try:
                result, used_mode, notice = router.answer(question, state, history, mode, on_tool, **AI.kwargs())
                if providers.is_auth_error(notice):  # 거부된 키는 기억해 키 오류로 보여주고 다음부터 오프라인으로
                    AI.mark_rejected()
                    notice += " 🔑에서 새 키를 넣으세요."
            except Exception as e:  # 예상 못 한 오류도 대화에 문장으로 남긴다 (키는 메시지에 넣지 않는다)
                status.update(label="분석 실패", state="error", expanded=False)
                st.session_state.chat.append({"role": "assistant", "error": True,
                                              "content": f"분석 중 오류가 발생했어요: {type(e).__name__}"})
                st.session_state["agent_open"] = True
                st.rerun()
            status.update(label=f"완료 · {len(result.tool_calls)}단계", state="complete", expanded=False)
    st.session_state.chat.append({
        "role": "assistant", "content": (f"*{notice}*\n\n" if notice else "") + result.text,
        "report": result.report, "mode": used_mode, "ai": AI.label() if used_mode == "agent" else None,
        "tools": [{"name": c.name, "input": c.input, "is_error": c.is_error} for c in result.tool_calls]})
    st.session_state["fab_seen"] = _n_answers()  # 팝업이 열린 채로 본 답변
    st.session_state["agent_open"] = True
    if result.changed:
        st.session_state["pending"] = {k: result.state[k] for k in result.changed}
        st.session_state["toast"] = "화면을 바꿨어요."
    st.rerun()
