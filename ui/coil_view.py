"""코일분석 화면 (prd_v2 R3, prd_v3 W1·W2 → prd_v6 P1·P2): 시생산·클레임 코일 vs 같은 조건 양산 실적.

양산 비교 기준 = 같은 강종 · 라인 · 공장 · 두께 구간, 최근 2년. 재질은 고정 순서, 그래프마다 카드 제목 + 해석 한 줄.
"""
import io
from datetime import datetime

import pandas as pd
import streamlit as st

from tools import charts as C
from tools import coil_lookup as L
from tools import narrative as N
from tools import terms as T
from tools.datasource import get_source
from ui.theme import card_title, show
from tools.domain import PROP_DECIMALS, PROP_LABEL, PROP_SHORT, PROP_UNIT

JUDGE_BADGE = {"합격": ":green-badge[스펙 합격]", "미달": ":red-badge[스펙 미달]", "초과": ":red-badge[스펙 초과]"}


@st.cache_data(show_spinner="양산 실적과 비교하는 중…", max_entries=16)
def _analyze(source_key, ids, id_type, months, same_line, same_thk, same_plant=True, same_ss=False, same_ct=False):
    return L.analyze_coil(ids, id_type, months, same_line, same_thk, same_plant, same_ss, same_ct)


def _report_md(res: dict) -> str:
    out = ["# 단일 코일 분석 리포트", "", f"작성 {datetime.now():%Y-%m-%d %H:%M} · 데이터 {get_source().name}", ""]
    for c in res["coils"]:
        out += [f"## {c['coil_no']} ({c['grade']} · {c['line']} · {c['prod_date']}{' · 시생산' if c['trial'] else ''})", "",
                "양산 비교 기준: " + ", ".join(f"{k} {v}" for k, v in c["baseline_conditions"].items())
                + f" · 양산 {c['n_baseline']}개", "", *[f"- {x}" for x in N.coil_story(c)], "",
                "| 재질 | 값 | 양산 중앙값 | z | 백분위 | 스펙 |", "| --- | --- | --- | --- | --- | --- |",
                *[f"| {PROP_SHORT[m['prop']]} | {m['value']} | {m['mass_median']} | {m['z']} | {m['percentile']} | "
                  f"{m['judge'] or '-'} |" for m in c["materials"]], "",
                "| 공정 | 인자 | 값 | 양산 중앙값 | z | 표준조건 이탈 |", "| --- | --- | --- | --- | --- | --- |",
                *[f"| {f['process']} | {f['label']} | {f['value']} | {f['mass_median']} | {f['z']} | "
                  f"{'예' if f['out_of_standard'] else ''} |" for f in c["factors"][:12]], ""]
    if res["common"]:
        out += ["## 여러 코일 공통", *[f"- {x['label']} ({x['direction']}) {x['coils']}/{x['of']}개" for x in res["common"]]]
    return "\n".join(out)


def _report_xlsx(res: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame([{k: c[k] for k in ("coil_no", "grade", "line", "prod_date", "trial", "n_baseline", "key_property")}
                      for c in res["coils"]]).to_excel(w, sheet_name="요약", index=False)
        pd.DataFrame([{"coil_no": c["coil_no"], **{k: v for k, v in m.items() if k != "spec"}}
                      for c in res["coils"] for m in c["materials"]]).to_excel(w, sheet_name="재질", index=False)
        pd.DataFrame([{"coil_no": c["coil_no"], **{k: v for k, v in f.items() if k != "mechanism"},
                       "mechanism": (f.get("mechanism") or {}).get("status")}
                      for c in res["coils"] for f in c["factors"]]).to_excel(w, sheet_name="공정", index=False)
        if res["lineage"]:
            pd.DataFrame(res["lineage"]).to_excel(w, sheet_name="공정 순서", index=False)
    return buf.getvalue()


POS_HELP = ("회색 막대 = 같은 조건 양산 코일의 분포, 굵은 선 = 이 코일, 점선 = 양산 중앙값, 빨간 점선 = SPEC.\n\n"
            "백분위 = 양산 중 이 코일보다 낮은 코일 비율. z = 양산 중앙값에서 흩어짐(MAD) 몇 배 떨어졌는지예요.")
DIFF_HELP = ("공정 인자마다 이 코일이 양산 중앙값에서 얼마나 떨어졌는지(z)를 공정 순서로 보여줘요.\n\n"
             "막대가 ±1.5를 넘으면 진하게, 표준조건 관리범위를 벗어나면 빨간 테두리예요.")


def _pos_note(m: dict) -> tuple[str, str]:
    nd = PROP_DECIMALS.get(m["prop"], 1)
    u = "" if PROP_UNIT[m["prop"]] == "-" else PROP_UNIT[m["prop"]]
    judge = {"합격": " ✅", "미달": " ⚠️ 스펙 미달", "초과": " ⚠️ 스펙 초과"}.get(m["judge"], "")
    title = f"📍 {PROP_SHORT[m['prop']]} {m['value']:.{nd}f}{u} — 양산 중 {m['percentile']:.0f}% 위치{judge}"
    line = (f"양산 중앙값 {m['mass_median']:.{nd}f} · 차이 {m['value'] - m['mass_median']:+.{nd}f}{u}"
            + (f" ({m['z']:+.1f}σ)" if m["z"] is not None else ""))
    return title, line


PROC_POS_HELP = ("회색 막대 = 같은 조건 양산 코일의 공정값 분포, 굵은 선 = 이 코일, 점선 = 양산 중앙값, 초록 점선 = 표준조건.\n\n"
                 "양산과 가장 다른 공정 인자부터 보여줘요 (z = 양산 중앙값에서 흩어짐 몇 배).")
PROC_CARDS = 6  # 공정 위치 그래프 개수 (양산과 차이 큰 순)


def _fmt(v: float) -> str:
    return f"{v:.4g}" if abs(v) < 1 else f"{v:,.1f}"


def _proc_note(f: dict, base: pd.Series) -> tuple[str, str]:
    b = base.dropna()
    pct = (b < f["value"]).mean() * 100 if len(b) else 0
    u = f["unit"] if f["unit"] not in ("", "-") else ""
    title = f"📍 {f['label']} {_fmt(f['value'])}{u} ({f['z']:+.1f}σ)"  # 한 줄에 들어가게 짧게
    line = f"양산 {pct:.0f}% 위치 · 중앙값 {_fmt(f['mass_median'])}"
    if f["standard"] is not None:
        line += f" · 표준 {_fmt(f['standard'])}" + (" ⚠️ 이탈" if f["out_of_standard"] else "")
    return title, line


def _coil_block(c: dict, theme: str | None):
    src = get_source()
    with st.container(border=True):
        badges = [f":blue-badge[{c['coil_no']}]", f":gray-badge[{c['grade']}]", f":gray-badge[라인 {c['line']}]"]
        if c.get("plant"):
            badges.append(f":gray-badge[공장 {c['plant']}]")
        if c.get("thk") is not None:
            badges.append(f":gray-badge[두께 {c['thk']}mm]")
        badges.append(f":gray-badge[{c['prod_date']}]")
        badges.append(":orange-badge[시생산]" if c["trial"] else ":gray-badge[양산]")
        st.markdown(" ".join(badges))
        st.caption(("양산 비교 기준: " + " · ".join(f"{k} {v}" for k, v in c["baseline_conditions"].items())
                    + f" · 양산 {c['n_baseline']}개 (시생산·대상 코일 제외, 중앙값·MAD 기준)").replace("~", r"\~"))
        for w in c["warnings"]:
            st.warning(T.warning_text(w), icon=":material/tune:")
        story = N.coil_story(c)
        if story:
            st.markdown(f"**💡 {story[0]}**")
            for line in story[1:]:
                st.caption(line)
        mats = c["materials"]
        base = src.coils[src.coils["coil_no"].isin(c["baseline_ids"])]
        spec = src.spec(c["grade"])
        for i in range(0, len(mats), 3):
            cols = st.columns(3)
            for col, m in zip(cols, mats[i:i + 3]):
                title, line = _pos_note(m)
                with col.container(border=True, key=f"cpcard_{c['coil_no']}_{m['prop']}"):
                    st.markdown(card_title(title), unsafe_allow_html=True, help=POS_HELP)
                    show(C.coil_position(base[m["prop"]], m["value"], m["prop"], spec.get(m["prop"], (None, None))),
                         theme, key=f"cp_{c['coil_no']}_{m['prop']}", height=220)
                    st.markdown(f"<div class='card-note'>{line}</div>", unsafe_allow_html=True)
        procs = [f for f in c["factors"] if f.get("z") is not None and f["factor"] in base][:PROC_CARDS]
        if procs:
            st.markdown("<div class='ov-group'>⚙️ 공정 위치<span>양산과 차이가 큰 공정 인자 순</span></div>",
                        unsafe_allow_html=True)
        for i in range(0, len(procs), 3):
            cols = st.columns(3)
            for col, f in zip(cols, procs[i:i + 3]):
                title, line = _proc_note(f, base[f["factor"]])
                u = f["unit"] if f["unit"] not in ("", "-") else ""
                with col.container(border=True, key=f"ppcard_{c['coil_no']}_{f['factor']}"):
                    st.markdown(card_title(title), unsafe_allow_html=True, help=PROC_POS_HELP)
                    show(C.coil_position(base[f["factor"]], f["value"], f["factor"], (None, None), title=f["label"],
                                         xlabel=f"{f['label']}" + (f" ({u})" if u else ""), standard=f["standard"]),
                         theme, key=f"pp_{c['coil_no']}_{f['factor']}", height=220)
                    st.markdown(f"<div class='card-note'>{line}</div>", unsafe_allow_html=True)
        top = next((f for f in c["factors"] if f.get("z") is not None), None)
        with st.container(border=True, key=f"pdcard_{c['coil_no']}"):
            st.markdown(card_title("⚙️ 양산 대비 공정 차이" + (f" — 1위 {top['label']} {top['z']:+.1f}σ" if top else "")),
                        unsafe_allow_html=True, help=DIFF_HELP)
            show(C.process_diff(c["factors"]), theme, key=f"pd_{c['coil_no']}")
            outs = [f["label"] for f in c["factors"] if f.get("out_of_standard")]
            st.markdown(f"<div class='card-note'>{'표준조건 이탈: ' + ', '.join(outs[:4]) if outs else '표준조건 이탈 인자 없음'}</div>",
                        unsafe_allow_html=True)
        with st.expander("공정 인자 전체 표"):
            st.dataframe(pd.DataFrame([{"공정": f["process"], "인자": f["label"], "단위": f["unit"], "이 코일": f["value"],
                                        "양산 중앙값": f["mass_median"], "z": f["z"], "표준": f["standard"],
                                        "표준조건 이탈": "⚠" if f["out_of_standard"] else "",
                                        "야금 원리": T.mechanism((f.get("mechanism") or {}).get("status", ""))
                                        if f.get("mechanism") else "-"} for f in c["factors"]]),
                         hide_index=True, width="stretch")


MONTHS = {6: "최근 6개월", 12: "최근 1년", 24: "최근 2년", 36: "최근 3년", 60: "최근 5년"}
SAME = {"line": "라인", "plant": "공장", "thk": "두께 구간"}


def _tol_text(v) -> str:
    return "상관없음" if not v else f"±{v:g}℃ 이내"


def _params() -> dict:
    """지금 화면에 고른 분석 조건 (실행 버튼을 눌러야 결과에 반영)."""
    ss = st.session_state
    same = ss.get("coil_same") or []
    return {"ids": (ss.get("d_coil_ids") or "").strip(), "id_type": ss["d_id_type"], "months": ss["coil_months"],
            "same_line": "line" in same, "same_plant": "plant" in same, "same_thk": "thk" in same,
            "same_ss": ss.get("coil_ss"), "same_ct": ss.get("coil_ct")}


def _cond_text(p: dict) -> str:
    parts = ["같은 강종"] + [SAME[k] for k in SAME if p[f"same_{k}"]]
    parts += [f"{f} {_tol_text(p[f'same_{f.lower()}'])}" for f in ("SS", "CT") if p[f"same_{f.lower()}"]]
    return " · ".join(parts) + f" · {MONTHS[p['months']]}"


def _form(trial: list[str]):
    """분석 조건 카드: ① 대상 코일 ② 비교할 양산 ③ 실행."""
    ss = st.session_state
    ss.setdefault("coil_months", 24)
    ss.setdefault("coil_same", list(SAME))
    ss.setdefault("coil_ss", L.SIMILAR_TOL["SS"])  # 기본 SS ±10℃
    ss.setdefault("coil_ct", L.SIMILAR_TOL["CT"])  # 기본 CT ±20℃
    with st.container(border=True, key="coil_form"):
        st.markdown("<div class='coil-step'><b>1</b> 분석할 코일</div>", unsafe_allow_html=True)
        a, b = st.columns([1, 3.2], vertical_alignment="top")
        a.selectbox("번호 종류", list(L.ID_TYPES), key="d_id_type", format_func=L.ID_TYPES.get,
                    help="슬라브·열연코일·히트번호로 조회하면 딸린 냉연코일을 모두 분석합니다.")
        b.text_area("코일 번호", key="d_coil_ids", height=68,
                    placeholder="예: C260603643, C260402451" + (f"  (시생산 코일 예: {trial[0]})" if trial else ""),
                    help="여러 개면 쉼표·줄바꿈으로 구분해요. 엑셀 한 열을 그대로 붙여 넣어도 돼요.")
        st.markdown("<div class='coil-step'><b>2</b> 비교할 양산 코일</div>", unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns([1, 1.6, 1, 1], vertical_alignment="top")
        c1.selectbox("기간", list(MONTHS), key="coil_months", format_func=MONTHS.get,
                     help="이 코일 생산일 기준 과거 기간. 비교 코일이 30개 미만이면 CT → SS → 두께 → 공장 → 라인 → 기간 순으로 넓혀요.")
        c2.pills("같은 조건", list(SAME), key="coil_same", selection_mode="multi", format_func=SAME.get,
                 help="강종은 늘 같아요. 눌러서 켜고 끄세요.")
        c3.selectbox("소둔온도 SS", [0.0, *L.TOL_CHOICES["SS"]], key="coil_ss", format_func=_tol_text,
                     help="이 코일의 SS와 차이가 고른 폭 안인 양산 코일만 비교해요.")
        c4.selectbox("권취온도 CT", [0.0, *L.TOL_CHOICES["CT"]], key="coil_ct", format_func=_tol_text,
                     help="이 코일의 CT와 차이가 고른 폭 안인 양산 코일만 비교해요.")
        p = _params()
        with st.container(horizontal=True, vertical_alignment="center", key="coil_run_row"):
            summary = st.empty()
            run = st.button("분석 실행", key="coil_run_btn", type="primary", icon=":material/play_arrow:",
                            width="content")
    if run and not p["ids"]:
        st.toast("분석할 코일 번호를 먼저 넣어 주세요.", icon=":material/search:")
    elif run:
        ss["coil_run"] = p
    elif ss.pop("coil_autorun", False) and p["ids"]:  # AI·링크로 번호가 들어오면 바로 분석
        ss["coil_run"] = p
    return p, summary


def render(state: dict, source_key: str):
    theme = st.session_state.get("ui_theme")
    st.markdown(card_title(f"🔬 {T.t('single_coil')} · 같은 조건 양산과 비교"), unsafe_allow_html=True)
    p, summary = _form(src_trials())
    done = st.session_state.get("coil_run")
    note = f"<b>{_cond_text(p)}</b> 양산과 비교"
    if not p["ids"]:
        summary.markdown(f"<div class='coil-sum'>{note} · 번호를 넣고 <b>분석 실행</b>을 누르세요</div>",
                         unsafe_allow_html=True)
        return
    if not done:
        summary.markdown(f"<div class='coil-sum'>{note} · <b>분석 실행</b>을 누르세요</div>", unsafe_allow_html=True)
        return
    stale = done != p
    res = _analyze(source_key, done["ids"], done["id_type"], done["months"], done["same_line"], done["same_thk"],
                   done["same_plant"], done["same_ss"], done["same_ct"])
    if stale:
        summary.markdown(f"<div class='coil-sum stale'>조건이 바뀌었어요 · <b>분석 실행</b>을 누르면 반영돼요 "
                         f"(아래는 이전 조건 결과)</div>", unsafe_allow_html=True)
    elif res.get("coils"):
        n_base = [c["n_baseline"] for c in res["coils"]]
        rng = f"{min(n_base):,}" if min(n_base) == max(n_base) else f"{min(n_base):,}~{max(n_base):,}"
        summary.markdown(f"<div class='coil-sum'>{note} · 분석 코일 <b>{len(res['coils']):,}개</b> · "
                         f"비교 양산 <b>{rng}개</b></div>", unsafe_allow_html=True)
    else:
        summary.markdown(f"<div class='coil-sum'>{note}</div>", unsafe_allow_html=True)
    if "error" in res:
        st.error(res["error"])
        return
    if res["missing"]:
        sug = "; ".join(f"{k} → {', '.join(v[:3])}" for k, v in res["suggestions"].items())
        st.warning(f"찾지 못한 번호: {', '.join(res['missing'])}" + (f" · 비슷한 번호: {sug}" if sug else ""),
                   icon=":material/search_off:")
    if not res["coils"]:
        return
    d1, d2, _ = st.columns([1.4, 1.4, 2.2])
    d1.download_button("리포트 MD", _report_md(res), "coil_report.md", "text/markdown",
                       icon=":material/download:", width="stretch")
    d2.download_button("리포트 Excel", _report_xlsx(res), "coil_report.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       icon=":material/download:", width="stretch")
    if len(res["lineage"]) > 1 or done["id_type"] != "coil_no":
        with st.expander(f"{T.t('lineage')} (슬라브 → 열연코일 → 냉연코일) · {len(res['lineage'])}개", expanded=True):
            st.dataframe(pd.DataFrame(res["lineage"]), hide_index=True, width="stretch")
    if len(res["coils"]) > 1:
        st.markdown(f"**{len(res['coils'])}개 코일 요약**")
        st.dataframe(pd.DataFrame([{
            "코일": c["coil_no"], "강종": c["grade"], "시생산": "Y" if c["trial"] else "",
            "가장 벗어난 재질": PROP_LABEL.get(c["key_property"], "-") if c["key_property"] else "양산 수준",
            "가장 다른 공정 인자": f"{c['factors'][0]['label']} ({c['factors'][0]['z']:+.1f})" if c["factors"] else "-",
            "양산 비교 코일": c["n_baseline"]} for c in res["coils"]]), hide_index=True, width="stretch")
        if res["common"]:
            st.info("여러 코일에서 같은 방향으로 벗어난 인자: " + ", ".join(
                f"**{x['label']}** ({'높음' if x['direction'] == '+' else '낮음'}, {x['coils']}/{x['of']}개)"
                for x in res["common"]), icon=":material/join:")
    for c in res["coils"][:5]:
        _coil_block(c, theme)
    if len(res["coils"]) > 5:
        with st.expander(f"나머지 {len(res['coils']) - 5}개 코일"):
            for c in res["coils"][5:]:
                _coil_block(c, theme)


def src_trials() -> list[str]:
    df = get_source().coils
    return df.loc[df["trial_flag"] == "Y", "coil_no"].tolist() if "trial_flag" in df else []
