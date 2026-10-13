"""강종 품질 현황 대시보드 + AI 분석 도우미 (Streamlit, prd_v3·prd_v4·prd_v5).

화면 용어·도움말은 tools/terms.py. 업로드·데이터 파일·즐겨찾기·코일분석·질문 팝업·머리글·AI 보고서·테마·세션 유지·
AI 모드 설정은 ui/ 모듈. AI SDK는 agent/providers/에서 필요할 때만 불러오므로 설치되지 않은 PC에서도 오프라인으로 뜬다.
"""
import io
from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder

import config
from tools import analysis as A
from tools import charts as C
from tools import dashboard_state as ds
from tools import narrative as N
from tools import pds, spc
from tools import terms as T
from tools.datasource import get_source, use_source
from tools.domain import DEFECTS, FACTORS, PROP_DECIMALS, PROP_LABEL, PROP_SHORT, factor_label, factor_unit
from tools.ranking import HELP as MODEL_HELP
from tools.ranking import MODELS, SCORE_LABEL
from ui import ai as AI
from ui import chat, coil_view, datasets, favorites, header, report, session, upload_wizard
from ui import theme as TH
from ui.common import badge, mode_badge, source_badge

CONF_BAND = {"~0.75": (None, 0.75), "0.75~1.0": (0.75, 1.0), "1.0~1.4": (1.0, 1.4), "1.4~": (1.4, None)}
PROP_WORD = {"YS": "항복강도", "TS": "인장강도", "EL": "연신율", "BH": "소부경화", "rbar": "r값", "n_value": "n값"}  # 추천 질문용
CHART_H, SPC_H = 360, 460  # 카드 그래프 높이 고정 (prd_v5 L1)

# ---------------------------------------------------------------------------
# 세션 복원 (prd_v3 F2) → 데이터 파일 (prd_v4 L3) → AI 설정 (prd_v5 H2·H3) → 상태
# ---------------------------------------------------------------------------
expired_msg = session.restore()
st.session_state["upload_source"] = datasets.source()
use_source(st.session_state["upload_source"])
SOURCE_KEY = datasets.source_key()
st.session_state["source_key"] = SOURCE_KEY
if st.session_state.get("_active_source") != SOURCE_KEY:  # 파일이 바뀌면 필터를 새 데이터 기준으로
    st.session_state["_active_source"] = SOURCE_KEY
    for k in [k for k in st.session_state if k.startswith("d_")]:
        del st.session_state[k]
AI.init()
DEFAULTS = ds.defaults()

if (qp := st.session_state.pop("_qp_state", None)) is not None:  # 새로 고침·링크: URL의 필터를 먼저 적용
    if "defect" in qp:  # 링크에 결함이 있으면 자동 선택(발생률 1위)보다 우선
        st.session_state["defect_pinned"] = True
    restored, _, _ = ds.apply_update(DEFAULTS, qp)
    for k, v in restored.items():
        st.session_state[f"d_{k}"] = v
    if restored.get("coil_ids"):  # 링크·AI가 넣은 코일 번호는 실행 버튼 없이 바로 분석
        st.session_state["coil_autorun"] = True
for k, v in DEFAULTS.items():
    st.session_state.setdefault(f"d_{k}", v)
st.session_state["d_view"] = ds.VIEW_ALIASES.get(st.session_state["d_view"], st.session_state["d_view"])
st.session_state.setdefault("d_period", (st.session_state["d_start"], st.session_state["d_end"]))
st.session_state.setdefault("chat", [])
st.session_state.setdefault("spc_params", dict(spc.DEFAULTS))

if pending := st.session_state.pop("pending", None):  # 에이전트·버튼이 바꾼 상태는 다음 실행 첫머리에 반영
    if "defect" in pending:  # AI가 고른 결함은 자동 선택보다 우선
        st.session_state["defect_pinned"] = True
    for k, v in pending.items():
        st.session_state[f"d_{k}"] = v
    if pending.get("coil_ids"):  # 링크·AI가 넣은 코일 번호는 실행 버튼 없이 바로 분석
        st.session_state["coil_autorun"] = True
    if "start" in pending or "end" in pending:
        st.session_state["d_period"] = (st.session_state["d_start"], st.session_state["d_end"])

st.set_page_config(page_title=f"{st.session_state['d_grade']} 품질 현황", layout="wide", page_icon="📊")
THEME = TH.choice_from_url()  # 자동 / light / dark (주소의 embed_options)
st.session_state["ui_theme"] = THEME
TH.inject()
st.html(f"<style>.st-key-tabbar {{background: {'#0B1220' if TH.effective(THEME) == 'dark' else '#FFFFFF'};}}</style>")

if msg := st.session_state.pop("toast", None):
    st.toast(msg, icon=":material/dashboard:")


# ---------------------------------------------------------------------------
# 콜백
# ---------------------------------------------------------------------------
def reset_filters():
    for k, v in DEFAULTS.items():
        if k not in ("view", "coil_ids", "id_type", "model", "props", "prop"):  # 화면·조회 번호·모델·재질은 유지
            st.session_state[f"d_{k}"] = v
    st.session_state["d_period"] = (DEFAULTS["start"], DEFAULTS["end"])


def set_period(months: int | None = None, this_year: bool = False):
    lo, hi = DEFAULTS["start"], DEFAULTS["end"]
    if this_year:
        start = date(hi.year, 1, 1)
    elif months:
        start = (pd.Timestamp(hi) - pd.DateOffset(months=months) + timedelta(days=1)).date()
    else:
        start = lo
    start = max(start, lo)
    st.session_state["d_period"] = (start, hi)
    st.session_state["d_start"], st.session_state["d_end"] = start, hi


QUICK_PERIODS = {"최근 1개월": {"months": 1}, "3개월": {"months": 3}, "6개월": {"months": 6}, "올해": {"this_year": True},
                 "최근 3년": {"months": 36}, "최근 5년": {"months": 60}, "전체": {}}  # 3·5년 (prd_v6 F1)


def on_quick_period():
    choice = st.session_state.get("quick_period")
    if choice:
        set_period(**QUICK_PERIODS[choice])
    st.session_state["quick_period"] = None  # 한 번 누르는 버튼처럼


def set_filters(**kw):
    for k, v in kw.items():
        st.session_state[f"d_{k}"] = v


def on_thk_slider():
    st.session_state["d_thk_min"], st.session_state["d_thk_max"] = st.session_state["thk_rng"]


def on_dataset_pick():
    datasets.select(st.session_state["dataset_pick"])


def on_spec_cols():
    cols = [c for c, key in (("spec_roll", "sc_roll"), ("spec_fin", "sc_fin")) if st.session_state.get(key)]
    st.session_state["d_spec_cols"] = cols or ["spec_roll"]


def on_mode():
    """AI on/off 스위치 → run_mode ("ai" | "offline")."""
    st.session_state["run_mode"] = "ai" if st.session_state.get("ai_toggle") else "offline"
    if st.session_state["run_mode"] == "ai" and not AI.has_key():
        st.session_state["toast"] = "오른쪽 위 🔑에 키를 넣으면 AI 모드로 바뀌어요. 그동안은 오프라인으로 답해요."


def apply_favorite(fav: dict):
    new, _, _ = ds.apply_update(DEFAULTS, fav.get("state", {}))
    for k, v in new.items():
        st.session_state[f"d_{k}"] = v
    st.session_state["d_period"] = (new["start"], new["end"])
    st.session_state["toast"] = f"즐겨찾기 '{fav['name']}'를 적용했어요."


def save_favorite():
    favorites.add(st.session_state.get("fav_name") or favorites.default_name(state_now()), state_now())
    st.session_state["fav_on"] = False
    st.session_state["toast"] = "즐겨찾기에 저장했어요."


def state_now() -> dict:
    return {k: st.session_state[f"d_{k}"] for k in DEFAULTS}


@st.cache_data(show_spinner=False)
def use_code_names() -> dict:
    path = config.DATA_DIR / "use_codes.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str)
    return dict(zip(df["code"], df["name"]))


def code_filter(key: str, label: str, grade: str, help_text: str | None = None):
    """검색·복수 선택, 목록에 없는 값 직접 입력 가능 (prd_v3 U1). 항목 옆에 코일 수. 규격약호는 [압연]/[정정] 표시."""
    counts = ds.code_options(key, {"spec_cols": st.session_state["d_spec_cols"]}, grade)
    selected = st.session_state.get(f"d_{key}", [])
    options = sorted(set(counts) | set(selected))
    names = use_code_names() if key == "uses" else {}

    def fmt_code(code):
        shown = ds.spec_label(code) if key == "specs" else code
        name = f" {names[code]}" if code in names else ""
        return f"{shown}{name} ({counts[code]:,})" if code in counts else f"{shown} (해당 코일 없음)"

    st.multiselect(label, options, key=f"d_{key}", format_func=fmt_code, accept_new_options=True, placeholder="전체",
                   help=help_text)
    missing = [c for c in st.session_state.get(f"d_{key}", []) if c not in counts]
    if missing:
        st.caption(f"⚠️ {', '.join(missing)}: 해당 코일 없음 (필터는 유지)")


# ---------------------------------------------------------------------------
# 사이드바: 📂 데이터 파일 · ★ 즐겨찾기 · 🔎 필터 (실행 모드는 고정바로 옮김, prd_v5 H2)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("**📂 데이터 파일**")
    st.session_state["dataset_pick"] = datasets.current()
    st.selectbox("데이터 파일", datasets.options(), key="dataset_pick", format_func=datasets.label,
                 on_change=on_dataset_pick, label_visibility="collapsed",
                 help="기본 파일, 올린 파일, 데이터 탭에서 만든 수정본(✏️)을 바로 바꿔 볼 수 있어요. 💾 = 이 PC에 보관")
    f1, f2 = st.columns([3, 1])
    if f1.button("새 파일 올리기", icon=":material/upload_file:", width="stretch",
                 help="회사 양식(coil data(pds).xlsx)이면 매핑 없이 바로 읽어요. 다른 양식은 컬럼을 연결해요."):
        upload_wizard.upload_dialog()
    f2.button("🗑", width="stretch", disabled=datasets.current() == datasets.DEFAULT_ID,
              on_click=datasets.delete, args=(datasets.current(),), help="지금 고른 파일을 목록에서 지워요 (기본 파일은 못 지움)")
    if msg := st.session_state.pop("upload_msg", None):
        (st.success if msg[0] == "ok" else st.error)(msg[1])
    st.checkbox("★ 지금 필터를 즐겨찾기로", key="fav_on")
    if st.session_state.get("fav_on"):
        st.text_input("이름", key="fav_name", placeholder=favorites.default_name(state_now()), label_visibility="collapsed")
        st.button("저장", on_click=save_favorite, type="primary", width="stretch")
    favs = favorites.load()
    if favs:
        with st.container(key="fav_list"):
            for i, fav in enumerate(favs):
                a, b = st.columns([6, 1], vertical_alignment="center")
                a.button(f"★ {fav['name']}", key=f"fav_{i}", on_click=apply_favorite, args=(fav,), width="stretch",
                         type="tertiary")
                b.button("✕", key=f"favx_{i}", on_click=favorites.remove, args=(fav["name"],), type="tertiary",
                         help="즐겨찾기에서 지우기")
    st.divider()
    st.markdown("**🔎 필터**")
    period = st.date_input("기간", min_value=DEFAULTS["start"], max_value=DEFAULTS["end"], key="d_period",
                           help=f"특정 기간을 고르면 {T.t('mode_period')}, 전체 기간이면 {T.t('mode_outlier')}로 비교해요.")
    if isinstance(period, (list, tuple)) and len(period) == 2:
        st.session_state["d_start"], st.session_state["d_end"] = period
    st.pills("빠른 선택", list(QUICK_PERIODS), key="quick_period", on_change=on_quick_period,
             label_visibility="collapsed")
    st.selectbox("냉연규격 (강종)", ds.grades(), key="d_grade",
                 format_func=lambda g: f"{g} ({int((A.all_coils()['grade'] == g).sum()):,})")
    grade_now = st.session_state["d_grade"]
    st.session_state["sc_roll"] = "spec_roll" in st.session_state["d_spec_cols"]
    st.session_state["sc_fin"] = "spec_fin" in st.session_state["d_spec_cols"]
    s1, s2 = st.columns(2)
    s1.checkbox("압연규격약호", key="sc_roll", on_change=on_spec_cols)
    s2.checkbox("정정규격약호", key="sc_fin", on_change=on_spec_cols)
    code_filter("specs", "규격약호", grade_now, "압연·정정을 함께 켜면 두 기준 값을 섞어 고를 수 있어요 (어느 하나에 맞으면 포함).")
    code_filter("aims", "출강목표", grade_now)
    code_filter("uses", "용도코드", grade_now)
    l1, l2 = st.columns(2)
    l1.selectbox("라인", ds.lines(), key="d_line")
    with l2:
        code_filter("plants", "공장", grade_now)
    lo, hi = ds.thk_limits()
    st.session_state["thk_rng"] = (float(st.session_state["d_thk_min"]), float(st.session_state["d_thk_max"]))
    st.slider("두께 (mm)", lo, hi, key="thk_rng", step=0.01, on_change=on_thk_slider)
    t1, t2 = st.columns(2)
    t1.number_input("최소", lo, hi, key="d_thk_min", step=0.01, format="%.2f")
    t2.number_input("최대", lo, hi, key="d_thk_max", step=0.01, format="%.2f")
    st.selectbox("시편 위치", list(ds.COIL_POS), key="d_coil_pos", format_func=ds.COIL_POS.get)
    st.button("필터 초기화", on_click=reset_filters, width="stretch", icon=":material/restart_alt:")

# 재질 (prd_v6 K1·K3): 고르지 않는다. 데이터가 있는 재질을 고정 순서(YP·TS·EL·n·r0·r45·r90·r̄·BH)로 모두 보여준다.
# 공정분석·조기 감시 기준 재질(prop)만 그 탭의 선택 상자로 고른다 (기본 TS)
grade_props = list(A.spec(st.session_state["d_grade"]))
if st.session_state["d_prop"] not in grade_props:
    st.session_state["d_prop"] = ds.DEFAULT_PROP if ds.DEFAULT_PROP in grade_props else grade_props[0]
state = state_now()
shown = grade_props
prop = state["prop"]
state["prop"] = prop
args = ds.analysis_args(state)
sub = ds.subset_args(state)
grade = state["grade"]
sp = A.spec(grade)[prop]
SPEC = A.spec(grade)


@st.cache_data(show_spinner="분석하는 중…", max_entries=64)
def run_analysis(source_key, grade, line, start, end, prop, side, sub, model, sigma, basis="sigma"):
    diag = A.diagnose(grade, line, start, end, props=list(A.spec(grade)), **sub)
    comp = A.compare(grade, prop, line, start, end, side=side, top_n=10, model=model, sigma=sigma, basis=basis, **sub)
    return diag, comp, N.insights(diag, comp)


@st.cache_data(show_spinner=False, max_entries=32)
def run_spc(source_key, grade, line, start, end, prop, sub, params: tuple):
    p = dict(params)
    return spc.monitor(A.filter_coils(grade, line, **sub), prop, start, end, A.spec(grade)[prop], lam=p["lam"],
                       L=p["L"], k=p["k"], h=p["h"], base_months=int(p["base_months"]), persist=int(p["persist"]))


diag, comp, ins = run_analysis(SOURCE_KEY, args["grade"], args["line"], args["start"], args["end"], prop,
                               state["side"], sub, state["model"], state["sigma"], state["basis"])
coils = A.filter_coils(grade, args["line"], **sub)
target, baseline = A.split_period(coils, args["start"], args["end"])
full_period = ds.is_full_period(state)


mode, side, group, ref = A.comparison_groups(coils, grade, prop, args["start"], args["end"], side=state["side"],
                                             sigma=state["sigma"], basis=state["basis"])
p = diag["properties"][prop]
judge = p["judgement"] if diag["n_baseline"] else "비교 불가"
group_color = C.direction_color(side or judge)
group_name, ref_name = T.group_names(mode, side)
mode_txt = T.mode(mode)
factor = comp["ranking"][0]["factor"] if state["factor"] == "자동" and comp["ranking"] else state["factor"]
if factor == "자동":
    factor = A.available_factors(coils)[0] if A.available_factors(coils) else "CT"
period_txt = "전체 기간" if full_period else f"{state['start']} ~ {state['end']}"
filter_txt = [f"{label} {', '.join(ds.spec_label(v) if k == 'specs' else v for v in state[k])}"
              for k, label in ds.CODE_FILTERS.items() if state.get(k)]
if sub["thk_min"] is not None or sub["thk_max"] is not None:
    filter_txt.append(f"두께 {state['thk_min']:g}~{state['thk_max']:g}mm")
if sub["coil_pos"]:
    filter_txt.append(ds.COIL_POS[sub["coil_pos"]])
spc_res = run_spc(SOURCE_KEY, grade, args["line"], args["start"], args["end"], prop, sub,
                  tuple(sorted(st.session_state["spc_params"].items())))
bands = A.thickness_band(coils["thk"]) if "thk" in coils else pd.Series(dtype=object)


# ---------------------------------------------------------------------------
# 그래프 카드 (prd_v5 C1·C3·L1): 이모지 + 결론 제목 + (?) → 고정 높이 그래프 → 해석 한 줄
# ---------------------------------------------------------------------------
def card(note: tuple[str, list[str]], fig, key: str, control=None, extra=None, emoji: str = "", help_key: str | None = None,
         height: int = CHART_H, ctrl_w: float = 1.15):
    title, lines = note
    text = f"{emoji} {title}".strip()
    with st.container(border=True, key=f"card_{key}"):
        if control:
            c1, c2 = st.columns([3.4, ctrl_w], vertical_alignment="top")
            c1.markdown(TH.card_title(text), unsafe_allow_html=True, help=T.CARD_HELP.get(help_key or key))
            with c2:
                control()
        else:
            st.markdown(TH.card_title(text), unsafe_allow_html=True, help=T.CARD_HELP.get(help_key or key))
        TH.show(fig, THEME, key=key, height=height)
        line = lines[0].replace("**", "") if lines else ""
        st.markdown(f"<div class='card-note' title='{escape(line)}'>{escape(line) or '&nbsp;'}</div>",
                    unsafe_allow_html=True)
        if extra:
            extra()


def section(code: str):
    """강종개요 구역 제목: 번호 + 이모지 + 이름 + 작은 설명 + (?) (prd_v5 T2·C3)."""
    no, emo, name, desc, helptext = T.SECTIONS[code]
    st.markdown(f"<div class='sec-title'>{no} {emo} {name}<span class='sec-desc'>{desc}</span></div>",
                unsafe_allow_html=True, help=helptext)


DEFECT_WARN = 5.0  # 불량률 강조 기준 % (prd_v6 K1)


def pick_gk(q: str):
    st.session_state["gk_prop"] = q


def gk_card(q: str) -> bool:
    """강종개요 재질 카드 하나 (prd_v8 G1). 값이 없으면 그리지 않고 False."""
    v = diag["properties"].get(q)
    if not v or not v["target"].get("n"):
        return False
    t, nd = v["target"], PROP_DECIMALS.get(q, 1)
    u = "" if v["unit"] == "-" else f" {v['unit']}"
    lo_, hi_ = v["spec"]["min"], v["spec"]["max"]
    spec_txt = "" if lo_ is None and hi_ is None else f"{'' if lo_ is None else f'{lo_:g}'}~{'' if hi_ is None else f'{hi_:g}'}"
    rate = t.get("spec_rate")
    fail = None if rate is None else round(100 - rate, 1)
    bad = fail is not None and fail >= DEFECT_WARN
    vals = (target if not full_period else coils)[q]
    svg = C.mini_hist_svg(vals, (lo_, hi_), None, w=200, h=34).replace("<svg width='200' height='34'",
                                                                         "<svg width='100%' height='34' preserveAspectRatio='none'")
    delta = ""
    if diag["n_baseline"] and v["shift"] is not None:
        cls = "up" if v["shift"] > 0 else "down"
        delta = f"<span class='kpi-delta {cls}'>{'▲' if v['shift'] > 0 else '▼'}{abs(v['shift']):.{nd}f}</span>"
    fail_txt = f"불량 {fail:g}%" if fail is not None else "불량 -"
    tip = (f"불량률 = SPEC 밖 코일 비율 ({t['n']:,}코일 중)" if fail is not None else "SPEC 없음") + \
        f" · 표준편차 {t['std']} · 범위 {t['min']}~{t['max']}"
    chosen = st.session_state.get("gk_prop", prop) == q
    with st.container(key=f"gk_{q}"):
        st.markdown(
            f"<div class='gk{' on' if chosen else ''}{' bad' if bad else ''}'>"
            f"<div class='gk-head'><b>{PROP_SHORT.get(q, q)}</b><span>{u} {spec_txt}</span></div>"
            f"<div class='gk-num'>{t['mean']:.{nd}f}{delta}</div>"
            f"<div class='gk-fail{' none' if fail is None else ''}'>{fail_txt} <span class='gk-help' title='{escape(tip)}'>?</span></div>"
            f"<div class='gk-svg'>{svg}</div></div>", unsafe_allow_html=True)
        st.button(" ", key=f"gkbtn_{q}", on_click=pick_gk, args=(q,),
                  help=f"누르면 {PROP_LABEL.get(q, q)} 분포를 오른쪽에 크게 보여줘요. {tip}")  # 카드 전체가 이 버튼
    return True


def gk_section():
    """재질 카드 4열 격자 + 오른쪽 큰 분포(합격/불량) (prd_v8 G1·G2). v8 후속: 별도 구역 제목 없이 기본 정보 안
    🧪 재질 묶음으로 (공정 조건 위)."""
    st.markdown("<div class='ov-group'>🧪 재질<span>평균 · 스펙 불량률 · 분포 — 카드를 누르면 오른쪽에 크게</span></div>",
                unsafe_allow_html=True)
    have = [q for q in shown if diag["properties"].get(q, {}).get("target", {}).get("n")]
    if st.session_state.get("gk_prop") not in have:
        st.session_state["gk_prop"] = prop if prop in have else (have[0] if have else prop)
    left, right = st.columns([1.5, 1], gap="medium")
    with left.container(key="gkgrid"):  # 카드 줄 사이 간격 16px (theme)
        for i in range(0, len(have), 4):
            cols = st.columns(4, gap="small")
            for col, q in zip(cols, have[i:i + 4]):
                with col:
                    gk_card(q)
    with right:
        q = st.session_state["gk_prop"]
        g = target if not full_period else coils
        rows = -(-len(have) // 4)

        def view_switch():  # 분포(히스토그램, 기본) ↔ 두께 그룹별 막대
            st.segmented_control("보기", ["분포", "두께별"], key="gk_view", default="분포", label_visibility="collapsed",
                                 help="분포 = 합격/불량 히스토그램 · 두께별 = 두께 구간마다 평균(±σ)·코일 수·불량률 막대")

        if (st.session_state.get("gk_view") or "분포") == "두께별":
            tg = A.thickness_groups(g, q, SPEC[q])
            card(N.note_thickness(tg, q), C.thickness_bars(tg, q, SPEC[q]), "gk_big", view_switch, emoji="📏",
                 help_key="thickness", height=max(150 * rows - 40, 260), ctrl_w=1.9)
        else:
            card(N.note_defect_dist(g, None, q, SPEC[q]), C.density_overview(g, q, SPEC[q]), "gk_big", view_switch,
                 emoji="📊", help_key="distribution", height=max(150 * rows - 40, 260), ctrl_w=1.9)


def confounder_buttons():
    """비교 조건 차이 경고 + 그 조건만 거르는 버튼."""
    for w in [w for w in comp["warnings"] if w.get("code") == "confounder"]:
        colname = w["column"]
        share = comp["confounders"][colname]["share_pct"]
        key = max(share, key=lambda k: share[k]["group"] - share[k]["reference"])  # 불량 코일 쪽에 몰린 조건
        label = ds.COIL_POS.get(key, key) if colname == "coil_pos" else key
        if colname == "thk_band":
            lo_b, hi_b = CONF_BAND.get(key, (None, None))
            kw = {"thk_min": lo_b if lo_b is not None else ds.thk_limits()[0],
                  "thk_max": hi_b if hi_b is not None else ds.thk_limits()[1]}
        else:
            kw = {colname: key}
        st.button(f"{T.CONFOUNDER_COL[colname]} {label}만 보기", key=f"conf_{colname}", on_click=set_filters,
                  kwargs=kw, help=f"{group_name} {share[key]['group']}% vs {ref_name} {share[key]['reference']}%. "
                                  f"{T.HELP['confounder']}")


# ---------------------------------------------------------------------------
# 📊 강종개요 (prd_v5 T2): ① 생산량 · ② 재질현황(+🚨 조기 감시) · ③ 두께별 재질현황
# ---------------------------------------------------------------------------
def spc_settings():
    with st.popover("⚙ 감시 조건", width="stretch", help="조기 감시 고급 설정 (추천 조건 프리셋 · EWMA λ·L · CUSUM k·h · 기준 기간)"):
        prm = st.session_state["spc_params"]
        st.caption("추천 조건")
        row = st.container(horizontal=True, key="spc_presets")  # 글자 길이만큼 넓게 (줄바꿈 없음)
        for name, preset in spc.PRESETS.items():
            if row.button(name, key=f"spc_pre_{name}", width="stretch",
                        type="primary" if all(prm.get(k) == v for k, v in preset.items()) else "secondary"):
                prm.update(preset)
                for k in ("lam", "L", "k", "h", "base_months", "persist"):
                    st.session_state.pop(f"spc_{k}", None)
                st.rerun()
        a, b = st.columns(2)
        prm["lam"] = a.number_input("EWMA λ", 0.05, 0.5, float(prm["lam"]), 0.05, key="spc_lam")
        prm["L"] = b.number_input("EWMA L", 2.0, 4.0, float(prm["L"]), 0.1, key="spc_L")
        prm["k"] = a.number_input("CUSUM k (σ)", 0.25, 1.5, float(prm["k"]), 0.05, key="spc_k")
        prm["h"] = b.number_input("CUSUM h (σ)", 2.0, 10.0, float(prm["h"]), 0.5, key="spc_h")
        prm["base_months"] = a.number_input("기준 기간 (개월)", 1, 24, int(prm["base_months"]), 1, key="spc_base_months")
        prm["persist"] = b.number_input("EWMA 연속 점", 1, 10, int(prm["persist"]), 1, key="spc_persist")
        st.caption("기준 = 보는 기간 직전 N개월 (기간을 안 고르면 데이터 처음 N개월).")


PROC_LABEL = {"OA": "과시효 온도 OAS", "RCS": "급냉대 온도 RCS"}  # 엑셀 열 이름(OAS) 그대로 보이게


def pick_pc(f: str):
    st.session_state["pc_factor"] = f


def pc_card(r: dict, df: pd.DataFrame):
    """공정 조건 카드 하나 (재질 카드처럼 카드 전체가 버튼): 공정 단계·이름·단위, σ, 작은 히스토그램, "강종 : 평균"."""
    f, unit = r["factor"], factor_unit(r["factor"])
    name = PROC_LABEL.get(f, factor_label(f))
    chosen = st.session_state.get("pc_factor") == f
    head = (f"<div class='gk-head'><span class='ov-stage'>{r['stage']}</span><b>{escape(name)}</b>"
            f"<span>{unit}</span></div>")
    with st.container(key=f"pc_{f}"):
        if not r["n"]:
            st.markdown(f"<div class='ov-tile pc empty{' on' if chosen else ''}'>{head}<div class='ov-none'>이 조건에는 값이 없어요</div>"
                        f"<div class='pc-foot'>{grade} : -</div></div>", unsafe_allow_html=True)
            tip = "값이 없어요"
        else:
            nd = 2 if unit in ("%",) and r["mean"] < 10 else 1 if abs(r["mean"]) < 1000 else 0
            svg = C.mini_hist_svg(df[f], (None, None), None, w=200, h=34, mark=r["aim"]).replace(
                "<svg width='200' height='34'", "<svg width='100%' height='34' preserveAspectRatio='none'")
            aim = f" · 지시 {r['aim']:.{nd}f}" if r["aim"] is not None else ""
            tip = f"{name} · 범위 {r['min']:.{nd}f}~{r['max']:.{nd}f}{unit} · 코일 {r['n']:,}{aim}"
            st.markdown(f"<div class='ov-tile pc{' on' if chosen else ''}'>{head}"
                        f"<div class='pc-sigma'>σ {r['std']:.{nd + 1}f} <span class='gk-help'>?</span></div>"
                        f"<div class='gk-svg'>{svg}</div><div class='pc-foot'>{grade} : {r['mean']:.{nd}f}</div></div>",
                        unsafe_allow_html=True)
        st.button(" ", key=f"pcbtn_{f}", on_click=pick_pc, args=(f,),
                  help=f"누르면 {name} 시계열을 오른쪽에 크게 보여줘요. {tip}")


def pc_section(df: pd.DataFrame):
    """🔥 공정 조건: 카드 4열 격자(공정 순서) + 오른쪽 큰 시계열 (카드를 누르면 바뀜)."""
    rows = A.process_overview(df)
    if not rows:
        return
    st.markdown("<div class='ov-group'>🔥 공정 조건<span>열연 → 냉연 → 소둔 → 조질·도금 · 카드를 누르면 오른쪽에 시계열</span></div>",
                unsafe_allow_html=True)
    have = [r["factor"] for r in rows if r["n"]]
    if st.session_state.get("pc_factor") not in [r["factor"] for r in rows]:  # 값 없는 카드(OAS)도 고를 수 있다
        st.session_state["pc_factor"] = "CT" if "CT" in have else (have[0] if have else rows[0]["factor"])
    left, right = st.columns([1.5, 1], gap="medium")
    with left.container(key="pcgrid"):  # 카드 줄 사이 간격 16px (theme)
        for i in range(0, len(rows), 4):
            cols = st.columns(4, gap="small")
            for col, r in zip(cols, rows[i:i + 4]):
                with col:
                    pc_card(r, df)
    with right:
        f = st.session_state["pc_factor"]
        r = next((x for x in rows if x["factor"] == f), {})
        name = PROC_LABEL.get(f, factor_label(f))
        n_rows = -(-len(rows) // 4)
        card(N.note_process_ts(coils, f, r.get("aim"), name),
             C.process_timeseries(coils, f, (args["start"], args["end"]), r.get("aim"), name), "pc_big", emoji="📈",
             help_key="trend", height=max(158 * n_rows - 40, 260))


SHARE_COLORS = ["#1D4ED8", "#3B82F6", "#60A5FA", "#93C5FD", "#BFDBFE", "#CBD5E1"]


def share_bar(s: pd.Series, top: int = 4) -> str:
    """값 비율 가로 막대 + 범례 (기본 정보 그림, prd_v8 B1)."""
    vc = s.dropna().astype(str).value_counts()
    if vc.empty:
        return "<div class='ov-none'>값 없음</div>"
    if len(vc) > top:
        vc = pd.concat([vc.iloc[:top], pd.Series({"기타": vc.iloc[top:].sum()})])
    pct = 100 * vc / vc.sum()
    segs = "".join(f"<span style='width:{p_:.1f}%;background:{SHARE_COLORS[i % len(SHARE_COLORS)]}' "
                   f"title='{escape(str(k))} {n:,} ({p_:.0f}%)'></span>" for i, (k, n, p_) in enumerate(zip(vc.index, vc.values, pct)))
    legend = "".join(f"<span><i style='background:{SHARE_COLORS[i % len(SHARE_COLORS)]}'></i>{escape(str(k))} {p_:.0f}%</span>"
                     for i, (k, p_) in enumerate(zip(vc.index, pct)))
    return f"<div class='ov-bar'>{segs}</div><div class='ov-legend'>{legend}</div>"


def month_bars(df: pd.DataFrame, n: int = 24) -> str:
    """최근 n개월 코일 수 작은 막대."""
    m = df.groupby("month").size().iloc[-n:]
    if m.empty:
        return ""
    top, w = max(int(m.max()), 1), 100 / len(m)
    bars = "".join(f"<rect x='{i * w:.2f}' y='{30 - 28 * v / top:.1f}' width='{w * 0.8:.2f}' height='{28 * v / top:.1f}' "
                   f"fill='#60A5FA'><title>{k} {v:,}코일</title></rect>" for i, (k, v) in enumerate(m.items()))
    return f"<svg viewBox='0 0 100 30' preserveAspectRatio='none' width='100%' height='30'>{bars}</svg>"


def overview_groups(df: pd.DataFrame) -> list[tuple[str, str, list[str]]]:
    """🏷 기본 정보 묶음 (그림 타일, 엑셀 값만): [(제목, 작은 설명, [타일 HTML])]."""
    if df.empty:
        return []

    def tile(title, body, sub=""):
        return (f"<div class='ov-tile'><div class='ov-t'>{escape(title)}</div>{body}"
                + (f"<div class='ov-sub'>{sub}</div>" if sub else "") + "</div>")

    prod = []
    tons = df["weight"].sum() if "weight" in df else None
    prod.append(tile("생산", f"<div class='ov-num'>{len(df):,}<small>코일</small></div>{month_bars(df)}",
                     escape(f"{df['prod_date'].min()} ~ {df['prod_date'].max()}" + (f" · {tons:,.0f}톤" if tons else ""))))
    sp = A.excel_spec(df)
    chips = "".join(f"<span class='ov-chip'>{PROP_SHORT.get(q, q)} {'' if lo is None else f'{lo:g}'}~{'' if hi is None else f'{hi:g}'}</span>"
                    for q, (lo, hi) in sp.items())
    prod.append(tile("SPEC", f"<div class='ov-chips'>{chips or '<span class=ov-none>엑셀에 SPEC 값 없음</span>'}</div>"))
    for col, name, unit in (("thk", "두께", "mm"), ("width", "폭", "mm")):
        if col in df and df[col].notna().sum() >= 3:
            v = df[col].dropna()
            svg = C.mini_hist_svg(v, (None, None), None, w=200, h=34).replace(
                "<svg width='200' height='34'", "<svg width='100%' height='34' preserveAspectRatio='none'")
            main = f"주력 {df['thk_band'].value_counts().idxmax()}" if col == "thk" and "thk_band" in df else ""
            prod.append(tile(name, f"<div class='ov-num sm'>{v.min():g}~{v.max():g}<small>{unit}</small></div>{svg}", escape(main)))
    lines = [tile(name, share_bar(df[col])) for col, name in
             (("line", "라인"), ("plant", "공장"), ("spec_roll", "압연규격약호"), ("spec_fin", "정정규격약호"),
              ("aim", "출강목표"), ("use_code", "용도코드")) if col in df and df[col].notna().any()]
    return [("📦 생산 · 제품", "코일 수 · SPEC · 두께 · 폭", prod),
            ("🏭 라인 · 규격 · 용도", "코일 수 비율 (상위 4 + 기타)", lines)]  # 🔥 공정 조건은 pc_section (카드 클릭 → 오른쪽 시계열)


def overview_card():
    """🏷 기본 정보 (prd_v8 B1·B2): 엑셀 값을 묶음별 그림 타일로. 모든 카드 같은 크기(4열 격자)."""
    df = coils if full_period else target
    st.markdown("<div class='sec-title'>🏷 기본 정보<span class='sec-desc'>엑셀(회사 양식) 값 · 재질 · 공정 조건 분포</span></div>",
                unsafe_allow_html=True,
                help=f"{T.CARD_HELP['overview']}\n\n{T.CARD_HELP['kpi']}\n\n{T.CARD_HELP['process_mini']}")
    groups = overview_groups(df)
    if not groups:
        st.caption("조건에 맞는 코일이 없어요")
    for title, desc, cells in groups:
        if not cells:
            continue
        st.markdown(f"<div class='ov-group'>{title}<span>{desc}</span></div><div class='ov-grid'>{''.join(cells)}</div>",
                    unsafe_allow_html=True)  # (?)는 기본 정보 제목 하나로 (격자 폭이 묶음마다 같게)
    if groups:
        gk_section()  # 🧪 재질: 카드 클릭 → 오른쪽 큰 분포
        pc_section(df)  # 🔥 공정 조건: 카드 클릭 → 오른쪽 시계열


def view_material():
    overview_card()  # 재질 카드(🧪)는 기본 정보 안 공정 조건 위


# ---------------------------------------------------------------------------
# ⚙️ 공정분석 (prd_v5 T4)
# ---------------------------------------------------------------------------
def view_cause():
    st.caption(T.DESC["공정분석"])
    t1, t0, t2, t3 = st.columns([1.1, 1.0, 1, 1.5])
    t1.selectbox("분석 재질", shown, key="d_prop", format_func=lambda q: PROP_LABEL.get(q, q),
                 help="원인 분석·조기 감시 기준 재질 (데이터가 있는 재질, 기본 TS)")
    t0.radio("불량 코일 기준", list(ds.BASES), key="d_basis", horizontal=True, format_func=ds.BASES.get,
             disabled=not full_period, help=T.CARD_HELP["basis"])
    t2.selectbox("σ 수준 (전체 기간일 때)", ds.SIGMAS, key="d_sigma", format_func=lambda s: f"평균 ± {s:.1f}σ",
                 disabled=not full_period or state["basis"] == "spec", help=T.CARD_HELP["sigma"])
    t3.radio(f"{T.t('side_label')}", list(ds.SIDES), key="d_side", horizontal=True,
             format_func=lambda s: T.t(f"side_{s}"), help=T.HELP["group_outlier"], disabled=not full_period)
    info = []
    if full_period:
        sigma_tag = " (σ 기준)" if state["basis"] == "sigma" or A.basis_fallback(coils, grade, prop, state["basis"]) else ""
        info.append(f"불량 코일{sigma_tag} **{len(group):,}개** ({100 * len(group) / max(len(coils), 1):.0f}%) vs {ref_name} {len(ref):,}개"
                    + (" · ⚠️ 10개 미만이라 결론을 믿기 어려워요" if len(group) < 10 else ""))
    b1, b2 = st.columns([3, 1.2], vertical_alignment="center")
    b1.markdown(" · ".join(info) if info else f"{mode_txt} · {group_name} {len(group):,}개 vs {ref_name} {len(ref):,}개")
    if (alarm := N.spc_badge(spc_res)):
        b2.markdown(f"<div class='tab-summary' style='opacity:1'>{escape(alarm)} ↓</div>", unsafe_allow_html=True,
                    help="아래 🚨 조기 감시 카드(체크리스트 위)에서 자세히 봐요")
    if comp.get("model_note"):
        st.info(comp["model_note"], icon=":material/info:")
    if full_period and (note := A.basis_fallback(coils, grade, prop, state["basis"])):
        st.caption(f"⚠️ {note}")

    def model_pick():
        st.selectbox("순위 계산 방법", list(MODELS), key="d_model", format_func=MODELS.get, label_visibility="collapsed",
                     help=" · ".join(f"{v}: {MODEL_HELP[k]}" for k, v in MODELS.items()))

    factors = A.available_factors(coils)
    if st.session_state["d_factor"] not in ["자동"] + factors:
        st.session_state["d_factor"] = "자동"

    def factor_pick():
        st.selectbox("원인 인자", ["자동"] + factors, key="d_factor", label_visibility="collapsed",
                     format_func=lambda f: "자동 (1순위)" if f == "자동" else f"{factor_label(f)}")

    c1, c2 = st.columns(2)
    with c1:
        card(N.note_contribution(comp, MODELS[comp["model"]]),
             C.contribution(comp["ranking"], score_key="score", score_label=SCORE_LABEL[comp["model"]]), "contrib",
             model_pick, emoji="🏆", help_key="ranking")
    with c2:
        card(N.note_scatter(comp, factor, prop),
             C.scatter(group, ref, factor, prop, sp, group_name, group_color, ref_name=ref_name), "scatter", factor_pick,
             emoji="🔗", help_key="scatter")
    c3, c4 = st.columns(2)
    with c3:
        std_val = next((r["standard"] for r in comp["all_factors"] if r["factor"] == factor), None)
        card(N.note_trend(coils, factor, std_val),
             C.factor_trend(coils, factor, (args["start"], args["end"]), std_val), "trend", emoji="📈", help_key="trend")
    with c4:
        card(N.note_confounders(comp), C.confounders(comp["confounders"], group_color, group_name, ref_name), "conf",
             extra=confounder_buttons, emoji="⚖️", help_key="confounder")
    if spc_res and "error" not in spc_res:  # 🚨 조기 감시 (강종개요 → 공정분석, 체크리스트 위)
        card(N.note_spc(spc_res), C.spc_chart(spc_res, sp), "spc", spc_settings, help_key="spc", height=SPC_H)
    elif spc_res:
        st.info(spc_res["error"], icon=":material/info:")
    with st.container(border=True):
        st.markdown(TH.card_title("✅ 공정제어 체크리스트"), unsafe_allow_html=True, help=T.CARD_HELP["checklist"])
        for a in ins["actions"] or ["눈에 띄는 원인 후보가 없어요. 시험 조건부터 확인해 보세요."]:
            st.checkbox(a, key=f"act_{hash(a)}")
        for w in [w for w in ins["warnings"] if "비율이" not in w]:
            st.caption(f"⚠️ {w}")
    if comp.get("insufficient"):
        st.caption("데이터 부족으로 순위에서 뺀 인자 (값이 있는 코일 10개 미만): "
                   + ", ".join(factor_label(f) for f in comp["insufficient"][:12]))
    with st.expander(f"🏆 {T.t('ranking')} 표 · 해석 리포트"):
        st.dataframe(pd.DataFrame([{
            "순위": r["rank"], "인자": r["label"], "공정": r["process"], "단위": r["unit"],
            f"{group_name} 평균": fmt(r["group_mean"]), f"{ref_name} 평균": fmt(r["reference_mean"]),
            "차이": fmt(r["diff"], sign=True), "점수": r["score"], T.t("effect_size"): r["effect_size"],
            "상관": r["corr_with_prop"], "표준": fmt(r["standard"]), "표준 대비": fmt(r["group_vs_standard"], sign=True),
            "야금 원리": N.mech_mark(r)} for r in comp["ranking"]]),
            hide_index=True, width="stretch")
        for r in comp["ranking"][:3]:
            if r["mechanism"].get("text"):
                st.caption(f"**{r['label']}** · {r['mechanism']['text']} ({r['mechanism'].get('source') or '지식베이스'})")
        st.download_button("해석 리포트 (MD)", insight_markdown(), f"insight_{grade}_{prop}.md", "text/markdown",
                           icon=":material/download:")


# ---------------------------------------------------------------------------
# 🧩 결함분석 (prd_v5 T5): 🥇 강종 안 결함 순위 · 🆚 타 강종 비교 · 🗓 월별 · 🏆 원인 순위
# ---------------------------------------------------------------------------
def view_defect():
    st.caption(T.DESC["결함분석"])
    pareto = A.defect_pareto(grade, args["line"], args["start"], args["end"], **sub)
    known = list(pareto["defect"]) + [d for d in DEFECTS if d not in set(pareto["defect"])]  # 발생률 순
    # 처음 열 때·강종/기간/필터가 바뀔 때는 발생률 1위 결함을 고른다. 직접 고른 결함(같은 조건 동안)·링크·AI가 고른 결함은 유지
    sig = f"{grade}|{args['line']}|{args['start']}|{args['end']}|{sub}"
    if st.session_state.pop("defect_pinned", False):
        st.session_state["defect_sig"] = sig
    if st.session_state.get("defect_sig") != sig:
        st.session_state["defect_sig"] = sig
        if not pareto.empty:
            st.session_state["d_defect"] = pareto["defect"].iloc[0]
    if st.session_state["d_defect"] not in known:
        st.session_state["d_defect"] = known[0]
    dt = st.session_state["d_defect"]

    def defect_pick():
        st.selectbox("결함", known, key="d_defect", label_visibility="collapsed",
                     format_func=lambda d: f"{d} ({int(pareto.loc[pareto['defect'] == d, 'count'].sum())})")

    def compare_toggle():
        st.toggle("강종×월", key="defect_heat", help="강종 × 월 결함률 히트맵으로 바꿔 봐요.")

    c1, c2 = st.columns(2)
    with c1:
        card(N.note_pareto(pareto, grade), C.defect_pareto(pareto, grade, dt), "pareto", defect_pick, emoji="🥇")
    with c2:
        rows = A.defect_compare(dt, args["line"], args["start"], args["end"], **sub)
        if st.session_state.get("defect_heat"):
            gm = A.defect_grade_month(dt, args["line"], **sub)
            card((f"강종 × 월 {dt} 결함률", ["한 달에 여러 강종이 같이 진하면 설비 공통 원인 의심"]),
                 C.defect_grade_heatmap(gm, dt), "dheat", compare_toggle, emoji="🆚", help_key="compare")
        else:
            card(N.note_defect_compare(rows, dt, grade), C.defect_compare(rows, dt, grade), "dcompare", compare_toggle,
                 emoji="🆚", help_key="compare")
    dres = A.defect_trace(dt, grade, args["line"], args["start"], args["end"], **sub)
    c3, c4 = st.columns(2)
    with c3:
        title = N.note_defect(dres) if "error" not in dres else (f"{grade} 월별 결함률", [])
        card(title, C.defect_monthly(coils, dt), "dmonth", emoji="🗓", help_key="defect_monthly")
    with c4:
        if "error" in dres:
            card((f"{grade} {dt} 원인 후보", [dres["error"]]), C.empty("결함 원인 후보", dres["error"]), "dfactor",
                 emoji="🏆", help_key="defect_factor")
        else:
            card((f"{grade} {dt} 원인 후보 순위", [f"{T.mode(dres['mode'])} · 결함 {dres['count_target']} / {dres['n_target']}코일"]),
                 C.defect_factor_bar(dres["factor_ranking"]), "dfactor", emoji="🏆", help_key="defect_factor")


# ---------------------------------------------------------------------------
# 🗂 데이터 (prd_v7 D1): v4 Raw Data 복원 — 회사 양식 열 이름, 열마다 필터·정렬, CSV/Excel
# ---------------------------------------------------------------------------
def pds_names() -> dict:
    """표준 컬럼 → 회사 양식 원래 열 이름 (같은 이름이 여러 공정에 있으면 공정명을 앞에)."""
    first, count = {}, {}
    for block, m in pds.BLOCK_MAP.items():
        for base, std in m.items():
            count[base] = count.get(base, 0) + 1
            first.setdefault(std, (block, base))
    return {std: (base if count[base] == 1 or block == "냉연" else f"{block} {base}")
            for std, (block, base) in first.items()}


def view_data():
    st.caption(T.DESC["데이터"])
    apply_filter = st.toggle("대시보드 필터 적용", value=True)
    raw = (target if apply_filter else A.all_coils()).drop(
        columns=["month", "thk_band", "has_defect", "passed", "rbar_given"], errors="ignore")
    names = pds_names()
    raw = raw.rename(columns={c: names.get(c, c) for c in raw.columns})
    raw = raw.loc[:, ~raw.columns.duplicated()]
    gb = GridOptionsBuilder.from_dataframe(raw)
    gb.configure_default_column(filter=True, sortable=True, resizable=True, floatingFilter=True, minWidth=90)
    gb.configure_column(names.get("coil_no", "coil_no"), pinned="left")
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=50)
    grid = AgGrid(raw, gridOptions=gb.build(), height=560, update_on=["filterChanged", "sortChanged"],
                  show_download_button=False, key="raw_grid")
    shown_rows = pd.DataFrame(grid.data) if grid is not None and grid.data is not None else raw
    st.caption(f"필터 결과 {len(shown_rows):,}행 / 전체 {len(raw):,}행")
    d1, d2 = st.columns(2)
    d1.download_button("CSV 다운로드", shown_rows.to_csv(index=False).encode("utf-8-sig"),
                       "coil_filtered.csv", "text/csv", width="stretch", icon=":material/download:")
    if st.session_state.get("raw_xlsx_key") != (SOURCE_KEY, len(shown_rows)):  # Excel은 무거워서 누를 때 만든다
        if d2.button("Excel 만들기", width="stretch", icon=":material/table_view:"):
            buf = io.BytesIO()
            with st.spinner("Excel 만드는 중…"):
                shown_rows.to_excel(buf, index=False)
            st.session_state["raw_xlsx"], st.session_state["raw_xlsx_key"] = buf.getvalue(), (SOURCE_KEY, len(shown_rows))
            st.rerun()
    else:
        d2.download_button("Excel 다운로드", st.session_state["raw_xlsx"], "coil_filtered.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           width="stretch", icon=":material/download:")


def fmt(v, sign=False) -> str:
    """표 숫자: 큰 값은 소수 1자리, 성분처럼 작은 값은 유효숫자 3자리."""
    if v is None or v != v:
        return "-"
    txt = f"{v:.1f}" if abs(v) >= 10 else f"{v:.3g}"
    return f"+{txt}" if sign and v > 0 else txt


def insight_markdown() -> str:
    lines = [f"# {grade} 품질 현황 · {PROP_SHORT[prop]} 공정분석", "",
             f"조건: 라인 {state['line']} · {period_txt}" + (f" · {' · '.join(filter_txt)}" if filter_txt else ""),
             f"비교 방식 {mode_txt} · {group_name} {len(group)}개 / {ref_name} {len(ref)}개 · 계산 방법 {MODELS[comp['model']]}",
             "", "## 해석", *[f"- {s}" for s in ins["summary"]], "", "## 공정제어 제안",
             *([f"- [ ] {a}" for a in ins["actions"]] or ["- 없음"]), ""]
    if ins["warnings"]:
        lines += ["## 확인 필요", *[f"- {w}" for w in ins["warnings"]], ""]
    lines += [f"## {T.t('ranking')}", "", "| 순위 | 인자 | 차이 | 점수 | 야금 원리 |", "| --- | --- | --- | --- | --- |",
              *[f"| {r['rank']} | {r['label']} | {r['diff']} {r['unit']} | {r['score']} | "
                f"{T.mechanism(r['mechanism']['status'])} |" for r in comp["ranking"]]]
    return "\n".join(lines)


def report_context() -> dict:
    """AI 보고서 재료 (prd_v4 P1 → prd_v5 R1): 화면과 같은 분석 결과 + KPI 타일."""
    summary, kpis = {}, []
    for q in grade_props:  # 보고서 요약 표는 강종의 재질 전부
        v = diag["properties"][q]
        t, nd = v["target"], PROP_DECIMALS.get(q, 1)
        lo_, hi_ = v["spec"]["min"], v["spec"]["max"]
        summary[q] = {"spec": "-" if lo_ is None and hi_ is None else
                      f"{'' if lo_ is None else f'{lo_:g}'}~{'' if hi_ is None else f'{hi_:g}'}",
                      "mean": "-" if t.get("mean") is None else f"{t['mean']:.{nd}f}",
                      "std": "-" if t.get("std") is None else f"{t['std']}",
                      "rate": "-" if t.get("spec_rate") is None else f"{t['spec_rate']}%"}
        if q in shown and t.get("mean") is not None:
            rate = t.get("spec_rate")
            j = v["judgement"] if diag["n_baseline"] else ""
            st_ = "bad" if rate is not None and rate < 95 else "up" if j.startswith("상향") else \
                "down" if j.startswith("하향") else "ok"
            kpis.append({"name": PROP_SHORT[q], "mean": summary[q]["mean"], "state": st_,
                         "sub": f"만족률 {summary[q]['rate']} · σ {summary[q]['std']}"})
    lines = [x.replace("**", "") for x in ins["summary"][:3]]
    g, r = (group, ref) if full_period else (target, baseline)
    notes = {"production": N.note_production(A.production(coils)[0], grade),
             "distribution": N.note_distribution(diag, prop, group_name, ref_name),
             "monthly": N.note_monthly(coils, prop), "thickness": N.note_thickness(A.thickness_groups(coils, prop, sp), prop),
             "ranking": N.note_contribution(comp, MODELS[comp["model"]]), "scatter": N.note_scatter(comp, factor, prop)}
    if spc_res and "error" not in spc_res:
        notes["spc"] = N.note_spc(spc_res)
    dt = state["defect"]
    ctx_defect = {"defect": dt, "defect_grades": None, "defect_monthly": None}
    dres = A.defect_trace(dt, grade, args["line"], args["start"], args["end"], **sub)
    if "error" not in dres and "defect_type" in coils:
        d = coils.assign(hit=coils["defect_type"].fillna("없음") == dt)
        ctx_defect["defect_monthly"] = d.groupby("month")["hit"].mean().mul(100)
        notes["defect"] = N.note_defect(dres)
    data_name = datasets.label(datasets.current())
    edited = getattr(get_source(), "edit_note", None)
    return {"grade": grade, "focus_prop": prop, "summary": summary, "summary_lines": lines, "kpis": kpis,
            "headline": f"{grade} 재질 요약", "yearly": A.production(coils)[0], "dist_group": g, "dist_ref": r,
            "group": group, "ref": ref, "group_name": group_name, "ref_name": ref_name, "group_color": group_color,
            "spec": SPEC, "coils": coils, "bands": bands, "thickness": {prop: A.thickness_groups(coils, prop, sp)},
            "spc": spc_res, "comp": comp, "score_label": SCORE_LABEL[comp["model"]], "model_name": MODELS[comp["model"]],
            "factor": factor, "actions": ins["actions"], "notes": notes, **ctx_defect,
            "cover_title": f"{grade} 품질 분석 · {period_txt}",
            "footer": f"조건: 라인 {state['line']} · {period_txt}" + (f" · {' · '.join(filter_txt)}" if filter_txt else "")
                      + f" · 데이터 {data_name}" + (f" (✏️ 수정본: {edited})" if edited else "")
                      + f" · 작성 {date.today():%Y-%m-%d}",
            "signature": f"{SOURCE_KEY}|{state}|{st.session_state['spc_params']}"}


def suggestions(view: str) -> list[str]:
    """추천 질문 (prd_v4 A2): 오프라인 해석기도 이해하는 문장으로, 지금 화면 분석 결과에서."""
    hi = DEFAULTS["end"]
    month = (f"{state['start'].month}월 " if (state["start"].year, state["start"].month) == (state["end"].year, state["end"].month)
             and state["start"].year == hi.year and not full_period else "")
    word = PROP_WORD.get(prop, PROP_SHORT[prop])
    month += {"CAL": "CAL ", "CGL_GA": "CGL "}.get(state["line"], "")  # 보고 있는 라인도 질문에 (오프라인 해석기가 알아듣는 말)
    out = []
    if view == "강종개요":
        a = spc_res.get("first_alarm") if spc_res else None
        if a and int(a["date"][:4]) == hi.year:
            out.append(f"{int(a['date'][5:7])}월 {grade} {word} 원인이 뭐야?")
        out.append(f"{month}{grade} {word} 원인 분석해줘")
        if judge.startswith(("상향", "하향")):
            out.append(f"{month}{grade} {word}가 왜 {'높게' if judge.startswith('상향') else '낮게'} 나왔어?")
    elif view == "공정분석":
        out.append(f"{month}{grade} {word} 원인이 뭐야?")
        if state["model"] == "effect":
            out.append("랜덤포레스트로 원인 순위 봐줘")
    elif view == "결함분석":
        out.append(f"{month}{grade} {state['defect']} 원인 찾아줘")
    elif view == "코일분석":
        ids = [x for x in str(state.get("coil_ids") or "").replace(",", " ").split() if x]
        if ids:
            out.append(f"{ids[0]} 코일 양산이랑 비교해줘")
    return list(dict.fromkeys(out))[:2]


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------
# 상단바 (prd_v8 U1·U2): 한 줄을 맨 위에 고정 — 탭 / 🤖 AI 보고서 · 코일 수 | 강종 · ◐ · 🔑 · 모드 · 🔗


def mode_switch():  # AI on/off 스위치 하나 (끄면 오프라인 · 외부 통신 없음)
    st.session_state["ai_toggle"] = st.session_state.get("run_mode") == "ai"
    with st.container(key="ai_switch"):
        st.toggle(":material/smart_toy: AI", key="ai_toggle", on_change=on_mode, help=T.CARD_HELP["mode"])


with st.container(key="tabbar"):
    with st.container(key="tabrow", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        view = st.segmented_control("화면", ds.VIEWS, key="d_view", label_visibility="collapsed", width="content",
                                    format_func=lambda v: f"{ds.VIEW_ICON[v]} {v}") or "강종개요"
        tools = st.container(key="tools", horizontal=True, horizontal_alignment="right", vertical_alignment="center",
                             gap="small", width="content")
    with tools:
        open_report = st.button(":material/smart_toy: AI 보고서", type="primary", width="content", key="ai_report_btn",
                                help="회사 PPT 양식으로 그래프 위주 보고서 (항목 선택·미리보기·다운로드, 장수 제한 없음). AI 모드면 문장을 AI가 써요.")
        st.markdown(f"<div class='tab-summary'>{len(coils):,}코일 | {grade}</div>", unsafe_allow_html=True, width="content")
        header.toolbar(THEME, session.query_dict(state, DEFAULTS, False), mode_switch)


# 제목 + 조건 칩 (prd_v8 U3): ✕를 누르면 그 필터만 기본값으로 (사이드바 값도 바뀜)
def clear_filter(keys: tuple):
    for k in keys:
        st.session_state[f"d_{k}"] = DEFAULTS[k]
    if "start" in keys:
        st.session_state["d_period"] = (DEFAULTS["start"], DEFAULTS["end"])


def filter_chips() -> list[tuple[str, tuple]]:
    chips = []
    if not full_period:
        chips.append((period_txt, ("start", "end")))
    if state["line"] != "전체":
        chips.append((f"라인 {state['line']}", ("line",)))
    for k, label in ds.CODE_FILTERS.items():
        if state.get(k):
            chips.append((f"{label} {', '.join(ds.spec_label(v) if k == 'specs' else v for v in state[k])}", (k,)))
    if sub["thk_min"] is not None or sub["thk_max"] is not None:
        chips.append((f"두께 {state['thk_min']:g}~{state['thk_max']:g}mm", ("thk_min", "thk_max")))
    if sub["coil_pos"]:
        chips.append((ds.COIL_POS[sub["coil_pos"]], ("coil_pos",)))
    return chips


with st.container(key="hdr"):
    st.title(f"{grade} 품질 현황")
    with st.container(key="chips", horizontal=True, vertical_alignment="center"):
        st.markdown(f"<span class='chip fixed'>냉연규격 {grade}</span>", unsafe_allow_html=True)
        for i, (label, keys) in enumerate(filter_chips()):
            st.button(f"{label}  ✕", key=f"chip_{i}", on_click=clear_filter, args=(keys,), type="tertiary",
                      help="이 조건 지우기")
        edited_note = getattr(get_source(), "edit_note", None)
        st.markdown(f"{mode_badge()} {source_badge()}" + (f" :violet-badge[✏️ 수정본 ({edited_note})]" if edited_note else "")
                    + (f" {badge(judge)}" if diag["n_baseline"] else ""))
if expired_msg:
    st.warning(expired_msg, icon=":material/history:")

if view == "코일분석":  # 필터와 별개로 번호로 조회
    st.caption(T.DESC["코일분석"])
    coil_view.render(state, SOURCE_KEY)
elif target.empty:
    st.info(f"조건에 맞는 코일이 없어요. {grade}은(는) {A.grade_info(grade).get('lines', '-')} 라인에서 생산돼요. "
            "기간·규격약호·출강목표·용도코드·두께를 바꿔 보세요.", icon=":material/search_off:")
    st.button("필터 초기화", on_click=reset_filters, key="reset_empty", icon=":material/restart_alt:")
else:
    {"강종개요": view_material, "공정분석": view_cause, "결함분석": view_defect}.get(view, view_data)()

if open_report:
    if target.empty:
        st.toast("조건에 맞는 코일이 없어 보고서를 만들 수 없어요.")
    else:
        report.dialog(report_context())

# 떠 있는 AI 아이콘 → 팝업 (기본은 숨김), 화면이 바뀌면 추천 질문 말풍선 (prd_v4 A1·A2)
chat.fab(AI.mode(), AI.user_key())
if st.session_state.get("agent_open"):
    chat.popup(state, AI.mode(), AI.user_key())
elif not target.empty or view == "코일분석":
    chat.bubble(suggestions(view), f"{view}|{grade}|{state['start']}|{state['end']}|{shown}|{SOURCE_KEY}|{state['line']}")

session.to_query(state, DEFAULTS, False)
session.save()
