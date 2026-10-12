"""오른쪽 질문 패널: 에이전트/오프라인 해석기 (prd_v2 R4)."""
import json
from datetime import datetime

import streamlit as st

import config
from agent import offline, router
from tools import terms as T
from tools.datasource import get_source
from ui.common import STEP_LABEL, badge

QUICK_ASKS = ["지금 화면을 해석해줘", "산점도 x축을 균열온도로 바꿔줘", "TS로 바꿔서 보여줘"]


def ask(q: str):
    st.session_state["queued"] = q


@st.dialog("분석 요약을 외부로 보냅니다")
def confirm_external(question: str):
    st.markdown("지금 **내 파일** 데이터로 분석 중이고 실행 모드가 **에이전트**입니다.")
    st.markdown("- OpenAI로 보내는 것: 질문, 분석 결과 요약(평균·순위·코일번호 등)\n- 보내지 않는 것: 원본 행 데이터 전체")
    st.caption("회사 보안 규정상 외부 전송이 안 되면 '오프라인으로 답변'을 누르거나 실행 모드를 오프라인으로 바꾸세요.")
    c1, c2 = st.columns(2)
    if c1.button("전송하고 분석", type="primary", width="stretch"):
        st.session_state["ext_ok"] = True
        st.session_state["queued"] = question
        st.rerun()
    if c2.button("오프라인으로 답변", width="stretch"):
        st.session_state["queued"] = question
        st.session_state["force_offline_once"] = True
        st.rerun()


def _report_card(rep: dict, style: str):
    j = rep.get("judgement")
    if j and j.get("shift") is not None:
        st.markdown(f"{badge(j['judgement'], style)} {j['property']} {j['shift']:+g} ({j['shift_sigma']:+.2f}σ)"
                    + (f" · 만족률 {j['spec_rate']}%" if j.get("spec_rate") is not None else "")
                    + (f" · Cpk {j['cpk']}" if j.get("cpk") is not None else ""))
    if rep.get("causes"):
        st.markdown(" ".join(f":{'blue' if c['mechanism'] == '일치' else 'gray'}-badge[{c['rank']}. {c['label']} "
                             f"{c['effect_size']:+.1f}]" for c in rep["causes"]))
    if d := rep.get("defect"):
        tops = " ".join(f":blue-badge[{f['label']} {f['effect_size']:+.1f}]" for f in d["top_factors"][:2])
        st.markdown(f":red-badge[{d['type']} {d['rate_baseline_pct']}% → {d['rate_target_pct']}%] {tops}")
    for c in rep.get("coils", [])[:3]:
        tops = " ".join(f":gray-badge[{f['label']} {f['z']:+.1f}]" for f in c["top_factors"][:2])
        st.markdown(f":orange-badge[{c['coil_no']}] {tops}")


def _message_md(q: str, m: dict) -> str:
    steps = "\n".join(f"- {STEP_LABEL.get(c['name'], c['name'])}: `{json.dumps(c['input'], ensure_ascii=False)}`"
                      for c in m.get("tools", []))
    who = config.MODEL if m.get("mode") == "agent" else "오프라인 해석기"
    return (f"# 원인분석 리포트\n\n질문: {q}\n\n작성 {datetime.now():%Y-%m-%d %H:%M} · {who} · {get_source().name}\n\n"
            f"{m['content']}\n\n## 분석 과정\n\n{steps}\n")


def _examples() -> list[str]:
    ex = list(QUICK_ASKS)
    df = get_source().coils
    if "trial_flag" in df and (df["trial_flag"] == "Y").any():
        ex.append(f"{df.loc[df['trial_flag'] == 'Y', 'coil_no'].iloc[0]} 코일 양산이랑 비교해줘")
    return ex


def render(state: dict, run_mode: str):
    style = state["style"]
    eff = router.effective_mode(run_mode)
    st.markdown("##### 분석 " + ("에이전트" if eff == "agent" else "도우미 (오프라인)"))
    st.caption(f"{config.MODEL} · 질문하면 해석하고 그래프 조건·변수를 바꿔줍니다." if eff == "agent" else
               "외부 통신 없이 질문에서 강종·기간·재질·결함·코일번호를 찾아 대시보드를 바꾸고 규칙 기반으로 해석합니다.")
    question = st.session_state.get("chat_q") or st.session_state.pop("queued", None)
    box = st.container(height=640, border=True)
    with box:
        if not st.session_state.chat and not question:
            st.markdown("**이렇게 물어보세요**")
            st.markdown("- 원인 분석: *\"5월 CAL 590C 항복강도가 낮은데 원인이 뭐야?\"*\n"
                        "- 코일 단건: *\"C2604xxxxx 코일 양산이랑 비교해줘\"*, *\"열연코일 HC... 분석\"*\n"
                        "- 그래프 조작: *\"산점도 x축을 균열온도로 바꿔줘\"*\n- 문체: *\"전문가 문체로\"*")
            st.caption("사이드바의 데모 질문(S1~S6)을 누르면 바로 분석합니다. 분석이 끝나면 대시보드가 결과에 맞게 바뀝니다.")
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
                _report_card(rep, style)
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

    st.chat_input("대시보드에 대해 질문하세요", key="chat_q")
    if question:
        mode = run_mode
        if st.session_state.pop("force_offline_once", False):
            mode = "offline"
        elif (get_source().kind == "upload" and router.effective_mode(mode) == "agent"
              and not st.session_state.get("ext_ok")):
            confirm_external(question)
            return
        _answer(question, state, mode, box)
    if st.session_state.chat:
        st.button("대화 지우기", on_click=lambda: st.session_state.update(chat=[]), width="stretch",
                  icon=":material/delete_sweep:")


def _answer(question: str, state: dict, mode: str, box):
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
                result, used_mode, notice = router.answer(question, state, history, mode, on_tool)
            except Exception as e:  # 예상 못 한 오류도 대화에 문장으로 남긴다
                status.update(label="분석 실패", state="error", expanded=False)
                st.session_state.chat.append({"role": "assistant", "error": True,
                                              "content": f"분석 중 오류가 발생했습니다: {type(e).__name__}: {e}"})
                st.rerun()
            status.update(label=f"완료 · {len(result.tool_calls)}단계", state="complete", expanded=False)
    st.session_state.chat.append({
        "role": "assistant", "content": (f"*{notice}*\n\n" if notice else "") + result.text,
        "report": result.report, "mode": used_mode,
        "tools": [{"name": c.name, "input": c.input, "is_error": c.is_error} for c in result.tool_calls]})
    if result.changed:
        st.session_state["pending"] = {k: result.state[k] for k in result.changed}
        st.session_state["toast"] = "분석 결과에 맞게 대시보드를 바꿨습니다."
    st.rerun()
