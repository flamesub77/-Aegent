"""냉연강판 재질 편차 대시보드 + 원인분석 에이전트 (Streamlit)."""
import io
import json
from datetime import datetime

import openai
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder

import config
from agent import router
from tools import analysis as A
from tools import charts as C
from tools import coil_lookup as L
from tools import dashboard_state as ds
from tools import narrative as N
from tools import terms as T
from tools import upload as U
from tools.datasource import use_source
from tools.domain import DEFECTS, FACTORS, PROP_DECIMALS, PROP_LABEL, PROP_SHORT, PROP_UNIT, factor_label

st.set_page_config(page_title="냉연강판 재질 편차 대시보드", layout="wide", page_icon="📊")

DEMO_QUESTIONS = [  # PRD 3장 S1~S6
    "5월 CAL 590C 항복강도가 낮은데 원인이 뭐야?",
    "3월 극저 외판 연신율 미달이 늘었어. 원인 분석해줘",
    "2월 440R 인장강도가 높게 나오고 연신율도 떨어졌어",
    "4월 340 항복강도가 전반적으로 올라간 것 같아",
    "1월 극저 내판 슬리버 결함 원인 찾아줘",
    "6월 GA재 파우더링이 많아졌는데 이유가 뭐야?",
]
QUICK_ASKS = ["지금 화면을 해석해줘", "산점도 x축을 균열온도로 바꿔줘", "TS로 바꿔서 보여줘"]
STEP_LABEL = {
    "get_dashboard_state": "화면 상태 확인",
    "query_coils": "① 대상 정의 · 데이터 조회",
    "diagnose_distribution": "② 분포 진단",
    "compare_groups": "③ 인자 비교 · 교란 요인 확인",
    "trace_defect": "③ 결함 원인 추적",
    "search_knowledge": "④ 메커니즘 근거 확인 (지식베이스)",
    "update_dashboard": "⑤ 대시보드 갱신",
    "analyze_coil": "③ 코일 단건 분석 (양산 대비)",
}
BADGE = {"상향": "orange", "하향": "blue"}

st.markdown("""
<style>
.block-container {padding-top: 2.2rem; padding-bottom: 2rem;}
[data-testid="stMetricValue"] {font-size: 1.55rem;}
[data-testid="stMetricLabel"] p {font-size: 0.82rem;}
h1 {font-size: 1.7rem !important; margin-bottom: 0 !important;}
</style>
""", unsafe_allow_html=True)


def badge(judgement: str) -> str:
    color = next((c for k, c in BADGE.items() if judgement.startswith(k)), "gray")
    return f":{color}-badge[{judgement}]"


# ---------------------------------------------------------------------------
# 데이터 소스 (샘플 / 업로드). 세션마다 매 실행 첫머리에 적용한다.
# ---------------------------------------------------------------------------
use_source(st.session_state.get("upload_source"))
SOURCE_KEY = st.session_state.get("source_key", "sample")
if st.session_state.get("_active_source") != SOURCE_KEY:  # 소스가 바뀌면 필터를 새 데이터 기준으로
    st.session_state["_active_source"] = SOURCE_KEY
    for k in list(st.session_state):
        if k.startswith("d_"):
            del st.session_state[k]
DEFAULTS = ds.defaults()

# ---------------------------------------------------------------------------
# 상태: 위젯 키 = "d_" + 상태 이름. 에이전트 변경은 다음 실행 첫머리에 반영한다.
# ---------------------------------------------------------------------------
for k, v in DEFAULTS.items():
    st.session_state.setdefault(f"d_{k}", v)
st.session_state.setdefault("d_period", (DEFAULTS["start"], DEFAULTS["end"]))
st.session_state.setdefault("run_mode", config.APP_MODE)
st.session_state.setdefault("chat", [])     # [{"role", "content", "tools", "report"}]

if pending := st.session_state.pop("pending", None):
    for k, v in pending.items():
        st.session_state[f"d_{k}"] = v
    if "start" in pending or "end" in pending:
        st.session_state["d_period"] = (st.session_state["d_start"], st.session_state["d_end"])


if msg := st.session_state.pop("toast", None):
    st.toast(msg, icon=":material/dashboard:")


def reset_filters():
    for k, v in DEFAULTS.items():
        st.session_state[f"d_{k}"] = v
    st.session_state["d_period"] = (DEFAULTS["start"], DEFAULTS["end"])


def ask(q: str):
    st.session_state["queued"] = q


@st.cache_data(show_spinner=False)
def data_overview(source_key):
    df = A.all_coils()
    rate = 100 * df["passed"].mean() if df["passed"].notna().any() else None
    return len(df), df["prod_date"].min(), df["prod_date"].max(), df["grade"].nunique(), rate


def load_upload():
    """사이드바 업로드 (3단계에서 단계형 화면으로 다듬는다): 자동 매핑 → 검증 → 적용."""
    f = st.session_state.get("upload_file")
    if f is None:
        return
    try:
        raw, _ = U.read_file(f.getvalue(), f.name)
        mapping = U.suggest_mapping(raw.columns)
        df = U.apply_mapping(raw, mapping)
        rep_ = U.validate(df, raw, mapping)
        if not rep_["ok"]:
            st.session_state["upload_msg"] = ("error", " / ".join(i["text"] for i in rep_["issues"] if i["level"] == "error"))
            return
        src = U.build_source(df, f.name, drop_bad=rep_["bad_mask"])
    except Exception as e:  # 파일 문제는 화면에 알리고 샘플 데이터 유지
        st.session_state["upload_msg"] = ("error", f"파일을 읽지 못했습니다: {e}")
        return
    st.session_state["upload_source"] = src
    st.session_state["source_key"] = f"upload:{f.name}:{len(src.coils)}"
    st.session_state["upload_msg"] = ("ok", f"{f.name} · {len(src.coils):,}행 적용 (제외 {rep_['bad_rows']}행)")


def use_sample():
    st.session_state.pop("upload_source", None)
    st.session_state["source_key"] = "sample"


# ---------------------------------------------------------------------------
# 사이드바
# ---------------------------------------------------------------------------
with st.sidebar:
    st.selectbox("실행 모드", list(router.MODE_LABEL), key="run_mode", format_func=router.MODE_LABEL.get,
                 help="오프라인: 외부 통신 없이 규칙 기반 해석 · 자동: 키가 있으면 에이전트, 실패하면 오프라인")
    with st.expander("데이터 소스", expanded=False):
        st.file_uploader("내 파일 (CSV / Excel)", type=["csv", "xlsx", "xls"], key="upload_file", on_change=load_upload)
        if msg := st.session_state.get("upload_msg"):
            (st.success if msg[0] == "ok" else st.error)(msg[1])
        if st.session_state.get("upload_source") is not None:
            st.button("샘플 데이터로 돌아가기", on_click=use_sample, width="stretch")
        st.download_button("업로드 양식 (Excel)", U.template_excel(), "coil_upload_template.xlsx", width="stretch")
    n_all, d_min, d_max, n_grade, pass_rate = data_overview(SOURCE_KEY)
    st.markdown(f"**데이터** · 코일 {n_all:,}건 · {n_grade}개 강종  \n{d_min} ~ {d_max}"
                + (f" · 전체 합격률 {pass_rate:.1f}%" if pass_rate is not None else ""))
    with st.expander("데모 질문 (시나리오 S1~S6)", expanded=False):
        for i, q in enumerate(DEMO_QUESTIONS):
            st.button(f"S{i + 1}. {q}", key=f"demo{i}", on_click=ask, args=(q,), width="stretch")
    st.divider()
    st.subheader("필터")
    st.selectbox("강종", ds.grades(), key="d_grade")
    st.selectbox("라인", ds.lines(), key="d_line")
    period = st.date_input("기간", min_value=DEFAULTS["start"], max_value=DEFAULTS["end"], key="d_period",
                           help="특정 기간을 고르면 나머지 기간과 비교합니다. 전체 기간이면 스펙·1σ 이탈 코일을 "
                                "나머지 코일과 비교합니다.")
    if isinstance(period, (list, tuple)) and len(period) == 2:
        st.session_state["d_start"], st.session_state["d_end"] = period
    props = list(A.spec(st.session_state["d_grade"]))
    if st.session_state["d_prop"] not in props:
        st.session_state["d_prop"] = props[0]
    st.radio("재질", props, key="d_prop", horizontal=True, format_func=lambda p: PROP_LABEL[p])
    st.segmented_control("해석 문체", list(T.STYLES), key="d_style", format_func=T.STYLES.get)
    st.subheader("그래프 변수")
    st.selectbox("원인 인자 (산점도·추이)", ["자동"] + list(FACTORS), key="d_factor",
                 format_func=lambda f: "자동 (기여도 1순위)" if f == "자동" else f"{factor_label(f)} ({f})")
    st.radio(f"{T.t('side_label')} (전체 기간일 때)", list(ds.SIDES), key="d_side", horizontal=True,
             format_func=lambda s: T.t(f"side_{s}"), help=T.HELP["group_outlier"])
    st.selectbox("표면결함", list(DEFECTS), key="d_defect")
    st.button("필터 초기화", on_click=reset_filters, width="stretch", icon=":material/restart_alt:")

state = {k: st.session_state[f"d_{k}"] for k in DEFAULTS}
state["style"] = state.get("style") or T.DEFAULT_STYLE
style = state["style"]
args = ds.analysis_args(state)
grade, prop, unit = state["grade"], state["prop"], PROP_UNIT[state["prop"]]
unit_txt = "" if unit == "-" else unit
sp = A.spec(grade)[prop]


@st.cache_data(show_spinner=False)
def run_analysis(source_key, grade, line, start, end, prop, side, style):
    diag = A.diagnose(grade, line, start, end, props=list(A.spec(grade)))
    comp = A.compare(grade, prop, line, start, end, side=side, top_n=10)
    return diag, comp, N.insights(diag, comp, style)


diag, comp, ins = run_analysis(SOURCE_KEY, args["grade"], args["line"], args["start"], args["end"], prop,
                               state["side"], style)
coils = A.filter_coils(grade, args["line"])
target, baseline = A.split_period(coils, args["start"], args["end"])
mode, side, group, ref = A.comparison_groups(coils, grade, prop, args["start"], args["end"], side=state["side"])
p = diag["properties"][prop]
judge = p["judgement"] if diag["n_baseline"] else "기간 비교 없음"
group_color = C.direction_color(side or judge)
group_name, ref_name = T.group_names(mode, side, style)
mode_txt = T.mode(mode, style)
factor = comp["ranking"][0]["factor"] if state["factor"] == "자동" and comp["ranking"] else state["factor"]
if factor == "자동":
    factor = "CT"
full_period = ds.is_full_period(state)
period_txt = "전체 기간" if full_period else f"{state['start']} ~ {state['end']}"


def insight_markdown() -> str:
    lines = [f"# 재질 편차 분석 · {grade} {state['line']} {period_txt} {prop}", "",
             f"작성 {datetime.now():%Y-%m-%d %H:%M} · 비교 방식 {mode_txt} · {group_name} {len(group)}개 / {ref_name} {len(ref)}개",
             "", "## 해석", *[f"- {s}" for s in ins["summary"]], "", "## 공정제어 제안",
             *([f"- [ ] {a}" for a in ins["actions"]] or ["- 없음"]), ""]
    if ins["warnings"]:
        lines += ["## 확인 필요", *[f"- {w}" for w in ins["warnings"]], ""]
    lines += ["## 원인 후보 순위", "", "| 순위 | 인자 | 차이 | 효과크기 | 메커니즘 |", "| --- | --- | --- | --- | --- |",
              *[f"| {r['rank']} | {r['label']} | {r['diff']} {r['unit']} | {r['effect_size']} | "
                f"{r['mechanism']['status']} |" for r in comp["ranking"]]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 헤더
# ---------------------------------------------------------------------------
st.title("냉연강판 재질 편차 대시보드")
st.markdown(f":gray-badge[{grade}] :gray-badge[라인 {state['line']}] :gray-badge[{period_txt}] "
            f":gray-badge[{PROP_LABEL[prop]}] :gray-badge[{mode_txt}] {badge(judge)}")

dash, chat_col = st.columns([7, 3], gap="large")

# ---------------------------------------------------------------------------
# 대시보드
# ---------------------------------------------------------------------------
def render_coil_view():
    """코일 단건 분석 (prd_v2 R3). 3단계에서 카드·차트로 다듬는다."""
    c1, c2, c3 = st.columns([1.2, 3, 1])
    c1.selectbox("번호 종류", list(L.ID_TYPES), key="d_id_type", format_func=L.ID_TYPES.get)
    c2.text_input("번호 (여러 개면 쉼표·줄바꿈)", key="d_coil_ids", placeholder="예: C260603643, HC260100308")
    months = c3.number_input("양산 비교 기간(개월)", 1, 12, 3, key="coil_months")
    ids = st.session_state.get("d_coil_ids", "")
    if not ids.strip():
        st.info("분석할 코일·슬라브·열연코일 번호를 입력하세요. 시생산 코일을 같은 강종·라인·두께의 양산 실적과 비교합니다.")
        return
    res = L.analyze_coil(ids, st.session_state["d_id_type"], months)
    if "error" in res:
        st.error(res["error"])
        return
    if res["missing"]:
        sug = "; ".join(f"{k} → {', '.join(v[:3])}" for k, v in res["suggestions"].items())
        st.warning(f"찾지 못한 번호: {', '.join(res['missing'])}" + (f" · 비슷한 번호: {sug}" if sug else ""))
    if res["lineage"]:
        st.markdown("**계보** (슬라브 → 열연코일 → 냉연코일)")
        st.dataframe(pd.DataFrame(res["lineage"]), hide_index=True, width="stretch")
    for c in res["coils"]:
        with st.container(border=True):
            st.markdown(f"##### {c['coil_no']} · {c['grade']} · {c['line']} · {c['prod_date']}"
                        + (" :orange-badge[시생산]" if c["trial"] else ""))
            st.caption("양산 비교 기준: " + " · ".join(f"{k} {v}" for k, v in c["baseline_conditions"].items())
                       + f" · 양산 {c['n_baseline']}개")
            for line in N.coil_story(c, style):
                st.markdown(f"- {line}")
            for w in c["warnings"]:
                st.warning(T.warning_text(w, style), icon=":material/warning:")
            m1, m2 = st.columns(2)
            m1.dataframe(pd.DataFrame([{"재질": PROP_SHORT[m["prop"]], "값": m["value"], "양산 중앙값": m["mass_median"],
                                        "z": m["z"], "백분위": m["percentile"], "스펙": m["judge"] or "-"}
                                       for m in c["materials"]]), hide_index=True, width="stretch")
            m2.dataframe(pd.DataFrame([{"공정": f["process"], "인자": f["label"], "값": f["value"],
                                        "양산 중앙값": f["mass_median"], "z": f["z"],
                                        "표준 이탈": "⚠" if f["out_of_standard"] else ""}
                                       for f in c["factors"][:10]]), hide_index=True, width="stretch")
    if res["common"]:
        st.info("여러 코일 공통으로 벗어난 인자: " + ", ".join(
            f"{x['label']} ({x['direction']}, {x['coils']}/{x['of']}개)" for x in res["common"]))


def render_dashboard():
    if target.empty:
        lines = A.grade_info(grade)["lines"]
        st.info(f"조건에 맞는 코일이 없습니다. {grade}은(는) {lines} 라인에서 생산됩니다. 라인이나 기간을 바꿔 보세요.",
                icon=":material/search_off:")
        return
    t, b = p["target"], p["baseline"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("대상 코일 수", f"{diag['n_target']:,}", border=True,
              help=f"기준 {diag['n_baseline']:,}개" if diag["n_baseline"] else "전체 기간")
    k2.metric(f"{PROP_SHORT[prop]} 평균" + (f" ({unit})" if unit_txt else ""), f"{t.get('mean')}", border=True,
              delta=f"{p['shift']:+.{PROP_DECIMALS.get(prop, 1)}f} ({p['shift_sigma']:+.2f}σ)" if p["shift"] is not None else None,
              delta_color="off", help="기준 기간 대비 평균 이동. 1σ 이상이면 상향/하향 분포로 판정")
    k3.metric("만족률 (%)", f"{t.get('spec_rate')}" if t.get("spec_rate") is not None else "스펙 없음", border=True,
              delta=(f"{t['spec_rate'] - b['spec_rate']:+.1f}%p"
                     if b.get("n") and t.get("spec_rate") is not None and b.get("spec_rate") is not None else None),
              help=f"스펙 {sp[0]}~{sp[1] or ''} {unit} · 미달 {t.get('below_spec')} / 초과 {t.get('above_spec')}")
    k4.metric("Cpk", t.get("cpk"), border=True,
              delta=f"{t['cpk'] - b['cpk']:+.2f}" if b.get("cpk") and t.get("cpk") else None,
              help="1.33 이상 양호, 1.0 미만 공정능력 부족")

    with st.container(border=True):
        head, dl = st.columns([3, 1], vertical_alignment="center")
        head.markdown("##### 해석 및 인사이트")
        dl.download_button("MD", insight_markdown(), f"insight_{grade}_{prop}.md", "text/markdown",
                           icon=":material/download:", width="stretch", key="dl_insight",
                           help="해석·제어 제안·원인 순위를 마크다운 리포트로 저장")
        for line in ins["summary"]:
            st.markdown(f"- {line}")
        if ins["actions"]:
            st.markdown("**공정제어 제안**")
            for a in ins["actions"]:
                st.checkbox(a, key=f"act_{hash(a)}")
        for w in ins["warnings"]:
            st.warning(w, icon=":material/warning:")

    view = st.segmented_control("화면", ds.VIEWS, key="d_view", label_visibility="collapsed") or "재질 편차"
    if view == "코일 단건 분석":
        render_coil_view()
        return

    if view == "재질 편차":
        st.plotly_chart(C.heatmap(A.overview_heatmap(prop, args["line"]), prop), width="stretch")
        st.caption("강종별 전체 평균 대비 월평균 편차 · 주황 = 상향, 파랑 = 하향 · 칸에 마우스를 올리면 평균값")
        c1, c2 = st.columns(2)
        c1.plotly_chart(C.histogram(target, baseline, prop, sp, "전체 기간" if full_period else "대상 기간",
                                    color=C.direction_color(judge)), width="stretch")
        c2.plotly_chart(C.monthly_box(coils, prop, sp, (args["start"], args["end"]), C.direction_color(judge)),
                        width="stretch")
        rows = [{"재질": q, "스펙": f"{v['spec']['min']}~{v['spec']['max'] or ''}", "단위": v["unit"],
                 "대상 평균": v["target"].get("mean"), "대상 σ": v["target"].get("std"),
                 "기준 평균": v["baseline"].get("mean"), "이동": v["shift"], "이동(σ)": v["shift_sigma"],
                 "만족률(%)": v["target"].get("spec_rate"), "Cpk": v["target"].get("cpk"),
                 "판정": v["judgement"] if diag["n_baseline"] else "-"} for q, v in diag["properties"].items()]
        st.dataframe(pd.DataFrame(rows).fillna("-").astype(str), hide_index=True, width="stretch")

    elif view == "원인 분석":
        st.caption(f"**{group_name} {len(group)}개** vs {ref_name} {len(ref)}개 · 산점도·추이 인자 "
                   f"**{factor_label(factor)}** ({'기여도 1순위 자동 선택' if state['factor'] == '자동' else '직접 선택'})")
        st.plotly_chart(C.contribution(comp["ranking"]), width="stretch")
        st.caption("주황 = 비교군에서 증가, 파랑 = 감소 · 진한 막대(✓) = 지식베이스 메커니즘과 방향 일치, "
                   "연한 막대 = 통계적 연관만 있음")
        c1, c2 = st.columns(2)
        c1.plotly_chart(C.scatter(group, ref, factor, prop, sp, group_name, group_color), width="stretch")
        std_val = next((r["standard"] for r in comp["all_factors"] if r["factor"] == factor), None)
        c2.plotly_chart(C.factor_trend(coils, factor, (args["start"], args["end"]), std_val), width="stretch")
        st.plotly_chart(C.confounders(comp["confounders"], group_color), width="stretch")
        st.caption("⚠ = 두 군의 구성비 차이가 15%p 이상인 교란 요인 (층별 확인 필요)")
        table = pd.DataFrame([{
            "순위": r["rank"], "인자": r["label"], "공정": r["process"], "단위": r["unit"],
            "비교군 평균": r["group_mean"], "기준 평균": r["reference_mean"], "차이": r["diff"],
            "효과크기": r["effect_size"], "상관": r["corr_with_prop"], "p값": r["p_value"], "표준": r["standard"],
            "표준 대비": r["group_vs_standard"], "메커니즘": r["mechanism"]["status"]} for r in comp["ranking"]])
        st.dataframe(table, hide_index=True, width="stretch")

    elif view == "표면결함":
        dt = state["defect"]
        only = st.toggle("선택 강종만 보기", value=False, help=f"끄면 전체 강종 ({grade} 외 포함)")
        dres = A.defect_trace(dt, grade if only else None, args["line"], args["start"], args["end"])
        m1, m2, m3 = st.columns(3)
        m1.metric(f"{dt} 발생률 (%)", dres["rate_target_pct"], border=True,
                  delta=(f"{dres['rate_target_pct'] - dres['rate_baseline_pct']:+.2f}%p 기준 대비"
                         if dres["rate_baseline_pct"] is not None else None), delta_color="inverse")
        m2.metric("기준 기간 발생률 (%)", dres["rate_baseline_pct"] if dres["rate_baseline_pct"] is not None else "-",
                  border=True)
        m3.metric("결함 코일 / 대상 코일", f"{dres['count_target']} / {dres['n_target']}", border=True)
        st.info(f"**지식베이스 원인** ({dres['kb_cause']['process']}) {dres['kb_cause']['cause']} · "
                f"{dres['kb_cause']['source']}", icon=":material/menu_book:")
        c1, c2 = st.columns(2)
        c1.plotly_chart(C.defect_monthly(A.filter_coils(grade if only else None, args["line"]), dt), width="stretch")
        c2.plotly_chart(C.defect_factor_bar(dres["factor_ranking"]), width="stretch")
        st.caption(f"빨강 = {dt} · 비교 방식: {T.mode(dres['mode'], style)} · 진한 막대(✓) = 지식베이스 원인과 방향 일치")

    else:  # Raw Data
        apply_filter = st.toggle("대시보드 필터(강종·라인·기간) 적용", value=True)
        raw = (target if apply_filter else A.all_coils()).drop(columns=["month", "thk_band", "has_defect", "passed"])
        gb = GridOptionsBuilder.from_dataframe(raw)
        gb.configure_default_column(filter=True, sortable=True, resizable=True, floatingFilter=True, minWidth=90)
        gb.configure_column("coil_no", pinned="left")
        gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=50)
        grid = AgGrid(raw, gridOptions=gb.build(), height=560, update_on=["filterChanged", "sortChanged"],
                      show_download_button=False, key="raw_grid")
        shown = pd.DataFrame(grid.data) if grid is not None and grid.data is not None else raw
        st.caption(f"필터 결과 {len(shown):,}행 / 전체 {len(raw):,}행 · 열 머리글 아래 입력칸 또는 ☰ 메뉴로 필터")
        d1, d2 = st.columns(2)
        d1.download_button("CSV 다운로드", shown.to_csv(index=False).encode("utf-8-sig"),
                           "coil_filtered.csv", "text/csv", width="stretch", icon=":material/download:")
        buf = io.BytesIO()
        shown.to_excel(buf, index=False)
        d2.download_button("Excel 다운로드", buf.getvalue(), "coil_filtered.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           width="stretch", icon=":material/download:")


with dash:
    render_dashboard()


# ---------------------------------------------------------------------------
# 에이전트
# ---------------------------------------------------------------------------
def report_card(rep: dict):
    """에이전트 결과의 판정·원인 요약 (도구 출력 기반)."""
    j = rep.get("judgement")
    if j and j.get("shift") is not None:
        st.markdown(f"{badge(j['judgement'])} {j['property']} {j['shift']:+.1f} ({j['shift_sigma']:+.2f}σ) · "
                    f"만족률 {j['spec_rate']}% · Cpk {j['cpk']}")
    if rep.get("causes"):
        st.markdown(" ".join(f":{'blue' if c['mechanism'] == '일치' else 'gray'}-badge[{c['rank']}. {c['label']} "
                             f"{c['effect_size']:+.1f}]" for c in rep["causes"]))
    if d := rep.get("defect"):
        tops = " ".join(f":blue-badge[{f['label']} {f['effect_size']:+.1f}]" for f in d["top_factors"][:2])
        st.markdown(f":red-badge[{d['type']} {d['rate_baseline_pct']}% → {d['rate_target_pct']}%] {tops}")


def message_markdown(q: str, m: dict) -> str:
    steps = "\n".join(f"- {STEP_LABEL.get(c['name'], c['name'])}: `{json.dumps(c['input'], ensure_ascii=False)}`"
                      for c in m.get("tools", []))
    return f"# 원인분석 리포트\n\n질문: {q}\n\n작성 {datetime.now():%Y-%m-%d %H:%M} · {config.MODEL}\n\n" \
           f"{m['content']}\n\n## 분석 과정\n\n{steps}\n"


def humanize_error(e: Exception) -> str:
    if isinstance(e, openai.AuthenticationError):
        return "OpenAI API 키가 올바르지 않습니다. .env의 OPENAI_API_KEY를 확인하세요."
    if isinstance(e, openai.RateLimitError):
        return "요청 한도를 초과했습니다. 잠시 후 다시 시도하세요."
    if isinstance(e, openai.APIConnectionError):
        return "OpenAI API에 연결할 수 없습니다. 네트워크를 확인하세요."
    if isinstance(e, openai.APIStatusError):
        return f"OpenAI API 오류 ({e.status_code}): {e.message}"
    return f"분석 중 오류가 발생했습니다: {type(e).__name__}: {e}"


with chat_col:
    st.markdown("##### 분석 에이전트")
    st.caption(f"{config.MODEL} · 질문하면 해석하고 그래프 조건·변수를 바꿔줍니다.")
    # 이번 실행에서 처리할 질문 (입력창 값은 위젯보다 먼저 session_state로 읽을 수 있다)
    question = st.session_state.get("chat_q") or st.session_state.pop("queued", None)
    box = st.container(height=640, border=True)
    with box:
        if not st.session_state.chat and not question:
            st.markdown("**이렇게 물어보세요**")
            st.markdown("- 원인 분석: *\"5월 CAL 590C 항복강도가 낮은데 원인이 뭐야?\"*\n"
                        "- 그래프 조작: *\"산점도 x축을 균열온도로 바꿔줘\"*\n"
                        "- 화면 해석: *\"지금 화면을 해석해줘\"*")
            st.caption("사이드바의 데모 질문(S1~S6)을 누르면 바로 분석합니다. 분석이 끝나면 대시보드가 결과에 맞게 바뀝니다.")
            for i, q in enumerate(QUICK_ASKS):
                st.button(q, key=f"quick{i}", on_click=ask, args=(q,), width="stretch")
        prev_q = None
        for i, m in enumerate(st.session_state.chat):
            with st.chat_message(m["role"]):
                if m["role"] == "user":
                    prev_q = m["content"]
                    st.markdown(m["content"])
                    continue
                if m.get("report"):
                    report_card(m["report"])
                st.markdown(m["content"])
                if m.get("error"):
                    continue
                c1, c2 = st.columns([3, 2])
                with c1.popover(f"분석 과정 {len(m.get('tools', []))}단계", width="stretch"):
                    for c in m.get("tools", []):
                        st.markdown(f"**{STEP_LABEL.get(c['name'], c['name'])}** "
                                    f"{':red-badge[오류]' if c['is_error'] else ''}")
                        st.code(json.dumps(c["input"], ensure_ascii=False), language="json")
                c2.download_button("리포트", message_markdown(prev_q or "", m), f"agent_report_{i}.md",
                                   "text/markdown", key=f"dl_msg{i}", width="stretch", icon=":material/download:")

    st.chat_input("대시보드에 대해 질문하세요", key="chat_q")
    if question:
        if True:  # 키가 없거나 오프라인 모드면 router가 오프라인 해석기로 답한다
            history = [{"role": m["role"], "content": m["content"]}
                       for m in st.session_state.chat if not m.get("error")][-8:]
            st.session_state.chat.append({"role": "user", "content": question})
            with box:
                with st.chat_message("user"):
                    st.markdown(question)
                with st.chat_message("assistant"):
                    status = st.status("분석을 시작합니다…", expanded=True)
                    try:
                        def on_tool(c):
                            label = STEP_LABEL.get(c.name, c.name)
                            status.update(label=f"{label} 중…")
                            status.write(f"{'⚠️' if c.is_error else '✓'} {label}")
                        result, used_mode, notice = router.answer(question, state, history,
                                                                  st.session_state["run_mode"], on_tool)
                    except Exception as e:  # 사용자에게 보여줄 문장으로 바꿔 대화에 남긴다
                        status.update(label="분석 실패", state="error", expanded=False)
                        st.session_state.chat.append({"role": "assistant", "content": humanize_error(e),
                                                      "error": True})
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
    if st.session_state.chat:
        st.button("대화 지우기", on_click=lambda: st.session_state.update(chat=[]), width="stretch",
                  icon=":material/delete_sweep:")
