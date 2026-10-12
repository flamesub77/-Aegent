"""코일 단건 분석 화면 (prd_v2 R3): 시생산·클레임 코일 vs 같은 조건 양산 실적."""
import io
from datetime import datetime

import pandas as pd
import streamlit as st

from tools import charts as C
from tools import coil_lookup as L
from tools import narrative as N
from tools import terms as T
from tools.datasource import get_source
from tools.domain import PROP_DECIMALS, PROP_LABEL, PROP_SHORT, PROP_UNIT

JUDGE_BADGE = {"합격": ":green-badge[스펙 합격]", "미달": ":red-badge[스펙 미달]", "초과": ":red-badge[스펙 초과]"}


@st.cache_data(show_spinner="양산 실적과 비교하는 중…", max_entries=16)
def _analyze(source_key, ids, id_type, months, same_line, same_thk):
    return L.analyze_coil(ids, id_type, months, same_line, same_thk)


def _report_md(res: dict, style: str) -> str:
    out = [f"# 코일 단건 분석 리포트", "", f"작성 {datetime.now():%Y-%m-%d %H:%M} · 데이터 {get_source().name}", ""]
    for c in res["coils"]:
        out += [f"## {c['coil_no']} ({c['grade']} · {c['line']} · {c['prod_date']}{' · 시생산' if c['trial'] else ''})", "",
                "양산 비교 기준: " + ", ".join(f"{k} {v}" for k, v in c["baseline_conditions"].items())
                + f" · 양산 {c['n_baseline']}개", "", *[f"- {x}" for x in N.coil_story(c, style)], "",
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
            pd.DataFrame(res["lineage"]).to_excel(w, sheet_name="계보", index=False)
    return buf.getvalue()


def _material_card(col, m: dict):
    nd, u = PROP_DECIMALS.get(m["prop"], 1), PROP_UNIT[m["prop"]]
    u = "" if u == "-" else f" {u}"
    with col.container(border=True):
        st.markdown(f"**{PROP_SHORT[m['prop']]}** {JUDGE_BADGE.get(m['judge'], '')}")
        diff = m["value"] - m["mass_median"]
        st.markdown(f"### {m['value']:.{nd}f}{u}")
        st.caption(f"양산 {m['mass_median']:.{nd}f} ± {m['mass_std']:.{nd + 1}f} · 차이 {diff:+.{nd}f}"
                   + (f" ({m['z']:+.1f}σ)" if m["z"] is not None else ""))
        st.progress(min(max(m["percentile"] / 100, 0.0), 1.0), text=f"양산 중 {m['percentile']:.0f}% 위치")


def _coil_block(c: dict, style: str):
    src = get_source()
    with st.container(border=True):
        st.markdown(f"#### {c['coil_no']} · {c['grade']} · {c['line']} · {c['prod_date']}"
                    + (f" · {c['thk']}mm" if c.get("thk") is not None else "")
                    + (" :orange-badge[시생산]" if c["trial"] else " :gray-badge[양산]"))
        st.caption("양산 비교 기준: " + " · ".join(f"{k} {v}" for k, v in c["baseline_conditions"].items())
                   + f" · 양산 {c['n_baseline']}개 (시생산·대상 코일 제외, 중앙값·MAD 기준)")
        for w in c["warnings"]:
            st.warning(T.warning_text(w, style), icon=":material/tune:")
        with st.container(border=True):
            st.markdown("**해석**")
            for line in N.coil_story(c, style):
                st.markdown(f"- {line}")
        mats = c["materials"]
        for i in range(0, len(mats), 4):
            cols = st.columns(4)
            for col, m in zip(cols, mats[i:i + 4]):
                _material_card(col, m)
        base = src.coils[src.coils["coil_no"].isin(c["baseline_ids"])]
        spec = src.spec(c["grade"])
        cols = st.columns(3)
        for i, m in enumerate(mats):
            cols[i % 3].plotly_chart(C.coil_position(base[m["prop"]], m["value"], m["prop"], spec.get(m["prop"], (None, None)),
                                                     title=f"{PROP_SHORT[m['prop']]} 양산 분포 위 이 코일"),
                                     width="stretch", key=f"cp_{c['coil_no']}_{m['prop']}")
        st.plotly_chart(C.process_diff(c["factors"]), width="stretch", key=f"pd_{c['coil_no']}")
        with st.expander("공정 인자 전체 표"):
            st.dataframe(pd.DataFrame([{"공정": f["process"], "인자": f["label"], "단위": f["unit"], "이 코일": f["value"],
                                        "양산 중앙값": f["mass_median"], "z": f["z"], "표준": f["standard"],
                                        "표준조건 이탈": "⚠" if f["out_of_standard"] else "",
                                        "야금 원리": T.mechanism((f.get("mechanism") or {}).get("status", ""), style)
                                        if f.get("mechanism") else "-"} for f in c["factors"]]),
                         hide_index=True, width="stretch")


def render(state: dict, source_key: str):
    style = state["style"]
    st.markdown("##### 코일 단건 분석 · 시생산 코일을 같은 조건 양산 실적과 비교")
    c1, c2 = st.columns([1, 3])
    c1.selectbox("번호 종류", list(L.ID_TYPES), key="d_id_type", format_func=L.ID_TYPES.get,
                 help="슬라브·열연코일·히트번호로 조회하면 딸린 냉연코일을 모두 분석합니다.")
    c2.text_area("번호 (여러 개면 쉼표·줄바꿈, 엑셀 한 열 붙여넣기 가능)", key="d_coil_ids", height=68,
                 placeholder="예: C260603643, C260402451")
    o1, o2, o3 = st.columns(3)
    months = o1.number_input("양산 비교 기간 (최근 개월)", 1, 12, 3, key="coil_months")
    same_line = o2.toggle("같은 라인만", value=True, key="coil_same_line")
    same_thk = o3.toggle("같은 두께 구간만", value=True, key="coil_same_thk")
    ids = st.session_state.get("d_coil_ids", "") or ""
    trial = src_trials()
    if not ids.strip():
        st.info("분석할 번호를 입력하세요." + (f" 예: 시생산 코일 `{trial[0]}`" if trial else ""), icon=":material/search:")
        if trial:
            st.button(f"시생산 코일 {len(trial)}개 모두 분석", key="coil_all_trials",
                      on_click=lambda: st.session_state.update(d_coil_ids=", ".join(trial), d_id_type="coil_no"))
        return
    res = _analyze(source_key, ids, st.session_state["d_id_type"], months, same_line, same_thk)
    if "error" in res:
        st.error(res["error"])
        return
    if res["missing"]:
        sug = "; ".join(f"{k} → {', '.join(v[:3])}" for k, v in res["suggestions"].items())
        st.warning(f"찾지 못한 번호: {', '.join(res['missing'])}" + (f" · 비슷한 번호: {sug}" if sug else ""),
                   icon=":material/search_off:")
    if not res["coils"]:
        return
    d1, d2, _ = st.columns([1, 1, 3])
    d1.download_button("리포트 MD", _report_md(res, style), "coil_report.md", "text/markdown",
                       icon=":material/download:", width="stretch")
    d2.download_button("리포트 Excel", _report_xlsx(res), "coil_report.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       icon=":material/download:", width="stretch")
    if len(res["lineage"]) > 1 or st.session_state["d_id_type"] != "coil_no":
        with st.expander(f"계보 (슬라브 → 열연코일 → 냉연코일) · {len(res['lineage'])}개", expanded=True):
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
        _coil_block(c, style)
    if len(res["coils"]) > 5:
        with st.expander(f"나머지 {len(res['coils']) - 5}개 코일"):
            for c in res["coils"][5:]:
                _coil_block(c, style)


def src_trials() -> list[str]:
    df = get_source().coils
    return df.loc[df["trial_flag"] == "Y", "coil_no"].tolist() if "trial_flag" in df else []
