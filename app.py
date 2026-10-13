"""강종 품질 현황 대시보드 + AI 분석 도우미 (Streamlit, prd_v3·prd_v4·prd_v5).

화면 용어·도움말은 tools/terms.py. 업로드·데이터 파일·즐겨찾기·코일분석·질문 팝업·머리글·AI 보고서·테마·세션 유지·
AI 모드 설정은 ui/ 모듈. AI SDK는 agent/providers/에서 필요할 때만 불러오므로 설치되지 않은 PC에서도 오프라인으로 뜬다.
"""
import io
from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

import config
from agent import router
from tools import analysis as A
from tools import charts as C
from tools import dashboard_state as ds
from tools import edits as E
from tools import narrative as N
from tools import pds, spc
from tools import terms as T
from tools.datasource import get_source, use_source
from tools.domain import DEFECTS, FACTORS, PROP_DECIMALS, PROP_LABEL, PROP_SHORT, factor_label
from tools.ranking import HELP as MODEL_HELP
from tools.ranking import MODELS, SCORE_LABEL
from ui import ai as AI
from ui import chat, coil_view, datasets, favorites, header, report, session, upload_wizard
from ui import theme as TH
from ui.common import badge, mode_badge, source_badge

CONF_BAND = {"~0.75": (None, 0.75), "0.75~1.0": (0.75, 1.0), "1.0~1.4": (1.0, 1.4), "1.4~": (1.4, None)}
PROP_WORD = {"YS": "항복강도", "TS": "인장강도", "EL": "연신율", "BH": "소부경화", "rbar": "r값", "n_value": "n값"}  # 추천 질문용
MODE_TEXT = {"offline": "🔒 오프라인", "ai": "🤖 AI 모드"}
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
    restored, _, _ = ds.apply_update(DEFAULTS, qp)
    for k, v in restored.items():
        st.session_state[f"d_{k}"] = v
for k, v in DEFAULTS.items():
    st.session_state.setdefault(f"d_{k}", v)
st.session_state["d_view"] = ds.VIEW_ALIASES.get(st.session_state["d_view"], st.session_state["d_view"])
st.session_state.setdefault("d_period", (st.session_state["d_start"], st.session_state["d_end"]))
st.session_state.setdefault("chat", [])
st.session_state.setdefault("spc_params", dict(spc.DEFAULTS))

if pending := st.session_state.pop("pending", None):  # 에이전트·버튼이 바꾼 상태는 다음 실행 첫머리에 반영
    for k, v in pending.items():
        st.session_state[f"d_{k}"] = v
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
                 "전체": {}}


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


def on_material():
    chosen = list(st.session_state.get("d_props") or [])
    if chosen and st.session_state.get("d_prop") not in chosen:
        st.session_state["d_prop"] = chosen[0] if ds.DEFAULT_PROP not in chosen else ds.DEFAULT_PROP
    elif not chosen:
        st.session_state["d_prop"] = ds.DEFAULT_PROP if ds.DEFAULT_PROP in ds.props() else ds.props()[0]


def on_mode():
    if st.session_state.get("run_mode") is None:  # 이미 고른 것을 다시 눌러도 꺼지지 않게
        st.session_state["run_mode"] = st.session_state.get("_last_mode", "offline")
    st.session_state["_last_mode"] = st.session_state["run_mode"]
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

# 재질 (prd_v5 T2): 기본 YP·TS·EL, 강종에 없는 재질은 뺀다
grade_props = list(A.spec(st.session_state["d_grade"]))
st.session_state["d_props"] = [p for p in st.session_state["d_props"] if p in grade_props]
if st.session_state["d_prop"] not in grade_props:
    st.session_state["d_prop"] = ds.focus_prop({"props": st.session_state["d_props"], "prop": None}) \
        if st.session_state["d_props"] else (ds.DEFAULT_PROP if ds.DEFAULT_PROP in grade_props else grade_props[0])
state = state_now()
shown = [p for p in ds.shown_props(state) if p in grade_props] or [grade_props[0]]
prop = ds.focus_prop(state) if ds.focus_prop(state) in grade_props else shown[0]
state["prop"] = prop
args = ds.analysis_args(state)
sub = ds.subset_args(state)
grade = state["grade"]
sp = A.spec(grade)[prop]
SPEC = A.spec(grade)


@st.cache_data(show_spinner="분석하는 중…", max_entries=64)
def run_analysis(source_key, grade, line, start, end, prop, side, sub, model, sigma):
    diag = A.diagnose(grade, line, start, end, props=list(A.spec(grade)), **sub)
    comp = A.compare(grade, prop, line, start, end, side=side, top_n=10, model=model, sigma=sigma, **sub)
    return diag, comp, N.insights(diag, comp)


@st.cache_data(show_spinner=False, max_entries=32)
def run_spc(source_key, grade, line, start, end, prop, sub, params: tuple):
    p = dict(params)
    return spc.monitor(A.filter_coils(grade, line, **sub), prop, start, end, A.spec(grade)[prop], lam=p["lam"],
                       L=p["L"], k=p["k"], h=p["h"], base_months=int(p["base_months"]), persist=int(p["persist"]))


diag, comp, ins = run_analysis(SOURCE_KEY, args["grade"], args["line"], args["start"], args["end"], prop,
                               state["side"], sub, state["model"], state["sigma"])
coils = A.filter_coils(grade, args["line"], **sub)
target, baseline = A.split_period(coils, args["start"], args["end"])
full_period = ds.is_full_period(state)


def groups_for(q):
    """재질마다 비교 그룹 (재질현황 분포 카드용)."""
    mode_q, side_q, g, r = A.comparison_groups(coils, grade, q, args["start"], args["end"], side=state["side"],
                                               sigma=state["sigma"])
    if not full_period:
        g, r = target, baseline
    name_g, name_r = T.group_names(mode_q, side_q)
    judge_q = diag["properties"][q]["judgement"] if diag["n_baseline"] else "비교 불가"
    return mode_q, side_q, g, r, name_g, name_r, C.direction_color(side_q or judge_q)


mode, side, group, ref = A.comparison_groups(coils, grade, prop, args["start"], args["end"], side=state["side"],
                                             sigma=state["sigma"])
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
         height: int = CHART_H):
    title, lines = note
    text = f"{emoji} {title}".strip()
    with st.container(border=True, key=f"card_{key}"):
        if control:
            c1, c2 = st.columns([3.4, 1.15], vertical_alignment="top")
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
    """재질개요 구역 제목: 번호 + 이모지 + 이름 + 작은 설명 + (?) (prd_v5 T2·C3)."""
    no, emo, name, desc, helptext = T.SECTIONS[code]
    st.markdown(f"<div class='sec-title'>{no} {emo} {name}<span class='sec-desc'>{desc}</span></div>",
                unsafe_allow_html=True, help=helptext)


def kpi_strip():
    """재질 고정카드 (prd_v5 T3, 압축형): 같은 폭·높이, 최대 6장. SPEC·평균·증감·작은 히스토그램·만족률."""
    cells = []
    narrow = len(shown) >= 5
    for q in shown[:6]:
        v = diag["properties"][q]
        t, nd = v["target"], PROP_DECIMALS.get(q, 1)
        u = "" if v["unit"] == "-" else f" {v['unit']}"
        lo_, hi_ = v["spec"]["min"], v["spec"]["max"]
        spec_txt = "SPEC 없음" if lo_ is None and hi_ is None else \
            f"{'' if lo_ is None else f'{lo_:g}'}~{'' if hi_ is None else f'{hi_:g}'}"
        if not t.get("n"):
            cells.append(f"<div class='kpi'><div class='kpi-head'>{PROP_SHORT.get(q, q)}</div><div class='kpi-foot'>값 없음</div></div>")
            continue
        rate = t.get("spec_rate")
        bad = rate is not None and rate < 95
        vals = (target if not full_period else coils)[q]
        ref_vals = baseline[q] if (not full_period and diag["n_baseline"]) else None
        svg = C.mini_hist_svg(vals, (lo_, hi_), ref_vals, w=92 if narrow else 110, h=34)
        delta = ""
        if diag["n_baseline"] and v["shift"] is not None:
            cls = "up" if v["shift"] > 0 else "down"
            delta = f"<span class='kpi-delta {cls}'>{'▲' if v['shift'] > 0 else '▼'}{abs(v['shift']):.{nd}f}</span>"
        tip = f"표준편차 {t['std']} · 범위 {t['min']}~{t['max']}" + (f" · 결측 {t['missing']:,}" if t.get("missing") else "")
        rate_txt = f"{'⚠️ ' if bad else ''}만족률 <b>{rate}%</b>" if rate is not None else "SPEC 없음"
        cells.append(
            f"<div class='kpi{' bad' if bad else ''}{' focus' if q == prop else ''}' title='{escape(tip)}'>"
            f"<div class='kpi-head'>{PROP_SHORT.get(q, q)}{u}<span class='kpi-spec'>{spec_txt}</span></div>"
            f"<div class='kpi-row'><div><span class='kpi-num'>{t['mean']:.{nd}f}</span>{delta}"
            f"<div class='kpi-foot'>{rate_txt}</div></div><div class='kpi-svg'>{svg}</div></div></div>")
    st.markdown(f"<div class='kpi-strip' style='grid-template-columns: repeat({max(len(cells), 3)}, minmax(0, 1fr))'>"
                f"{''.join(cells)}</div>", unsafe_allow_html=True, help=T.CARD_HELP["kpi"])


def confounder_buttons():
    """비교 조건 차이 경고 + 그 조건만 거르는 버튼."""
    for w in [w for w in comp["warnings"] if w.get("code") == "confounder"]:
        colname = w["column"]
        share = comp["confounders"][colname]["share_pct"]
        key = max(share, key=lambda k: share[k]["group"] - share[k]["reference"])  # 문제 코일 쪽에 몰린 조건
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
# 📊 재질개요 (prd_v5 T2): ① 생산량 · ② 재질현황(+🚨 조기 감시) · ③ 두께별 재질현황
# ---------------------------------------------------------------------------
def spc_settings():
    with st.popover("⚙ 감시 조건", width="stretch", help="조기 감시 고급 설정 (추천 조건 프리셋 · EWMA λ·L · CUSUM k·h · 기준 기간)"):
        prm = st.session_state["spc_params"]
        st.caption("추천 조건")
        cols = st.columns(len(spc.PRESETS))
        for c, (name, preset) in zip(cols, spc.PRESETS.items()):
            if c.button(name, key=f"spc_pre_{name}", width="stretch",
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


def prop_pick(key: str):
    def _pick():
        if len(shown) > 1:
            st.selectbox("재질", shown, key=key, format_func=lambda q: PROP_SHORT.get(q, q), label_visibility="collapsed")
    return _pick


def material_pair(q: str):
    """재질 하나: 분포 + 월별 추이."""
    _, _, g, r, ng, nr, colr = groups_for(q)
    judge_q = diag["properties"][q]["judgement"] if diag["n_baseline"] else "비교 불가"
    c1, c2 = st.columns(2)
    with c1:
        card(N.note_distribution(diag, q, ng, nr), C.histogram(g, r, q, SPEC[q], ng, color=colr, ref_name=nr),
             f"hist_{q}", emoji="🧪", help_key="distribution")
    with c2:
        card(N.note_monthly(coils, q), C.monthly_box(coils, q, SPEC[q], (args["start"], args["end"]),
                                                     C.direction_color(judge_q)), f"box_{q}", emoji="📈",
             help_key="monthly")


def thickness_pair(q: str):
    tg = A.thickness_groups(coils, q, SPEC[q])
    worst = tg.loc[tg["spec_rate"].idxmin(), "band"] if not tg.empty and tg["spec_rate"].notna().any() else None
    c1, c2 = st.columns(2)
    with c1:
        card(N.note_thickness(tg, q), C.thickness_box(coils, q, SPEC[q], bands, [b for *_, b in A.THK_GROUPS], worst),
             f"thk_{q}", emoji="📏", help_key="thickness")
    with c2:
        with st.container(border=True, key=f"card_thktbl_{q}"):
            st.markdown(TH.card_title(f"📏 두께 구간별 {PROP_SHORT[q]} 표"), unsafe_allow_html=True,
                        help="구간마다 코일 수·평균·표준편차·만족률·Cpk예요. Cpk 1.33 이상이면 공정 능력이 충분한 편, "
                             "1.0 미만이면 SPEC을 벗어나기 쉬운 상태예요.")
            if tg.empty:
                st.caption("두께 값이 있는 코일이 없어요")
            else:
                nd = PROP_DECIMALS.get(q, 1)
                st.dataframe(pd.DataFrame({
                    "두께": [N.band_text(b) for b in tg["band"]], "코일 수": tg["n"].astype(int),
                    "평균": tg["mean"].round(nd), "표준편차": tg["std"].round(nd + 1),
                    "만족률(%)": tg["spec_rate"], "Cpk": tg["cpk"]}), hide_index=True, width="stretch",
                    height=CHART_H - 20)
            st.markdown("<div class='card-note'>&nbsp;</div>", unsafe_allow_html=True)


def view_material():
    # ① 생산량
    section("production")
    yearly, by_grade = A.production(coils)
    c1, c2 = st.columns(2)
    with c1:
        def stack_toggle():
            st.toggle("규격별", key="prod_by_grade", help="켜면 강종 필터와 상관없이 전체 냉연규격의 연도별 생산량을 쌓아 보여줘요.")
        if st.session_state.get("prod_by_grade"):
            yearly_all, by_grade = A.production(A.filter_coils(None, args["line"], **sub))
            card(N.note_production(yearly_all, "전체 강종"), C.production(yearly_all, by_grade), "prod", stack_toggle,
                 emoji="📦", help_key="production")
        else:
            card(N.note_production(yearly, grade), C.production(yearly), "prod", stack_toggle, emoji="📦",
                 help_key="production")
    with c2:
        card(N.note_production_monthly(coils), C.production_monthly(coils, (args["start"], args["end"])), "prodm",
             emoji="🗓", help_key="production_monthly")
    # ② 재질현황 (+ 🚨 조기 감시)
    section("material")
    if len(shown) > 3:  # 재질이 많으면 재질별 접기
        for q in shown:
            with st.expander(f"🧪 {PROP_LABEL[q]}", expanded=q == prop):
                material_pair(q)
    else:
        for q in shown:
            material_pair(q)
    if spc_res and "error" not in spc_res:
        def spc_controls():
            a, b = st.columns([1, 1.25])
            with a:
                prop_pick("d_prop")()
            with b:
                spc_settings()
        card(N.note_spc(spc_res), C.spc_chart(spc_res, sp), "spc", spc_controls, help_key="spc", height=SPC_H)
    elif spc_res:
        st.info(spc_res["error"], icon=":material/info:")
    c3, c4 = st.columns(2)
    with c3:
        hm = A.overview_heatmap(prop, args["line"], where=sub["where"])
        card(N.note_heatmap(hm, prop), C.heatmap(hm, prop), "heat", emoji="🗺", help_key="heatmap")
    with c4:
        if "r0" in coils and coils["r0"].notna().any():
            g, r = (group, ref) if full_period else (target, baseline)
            card(N.note_rvalue(g, r, group_name, ref_name),
                 C.rvalue_box(g, r, group_name, ref_name, group_color if full_period else C.direction_color(judge)),
                 "rval", emoji="🧭", help_key="rvalue")
    # ③ 두께별 재질현황
    section("thickness")
    if len(shown) > 3:
        for q in shown:
            with st.expander(f"📏 {PROP_LABEL[q]}", expanded=q == prop):
                thickness_pair(q)
    else:
        for q in shown:
            thickness_pair(q)


# ---------------------------------------------------------------------------
# ⚙️ 공정분석 (prd_v5 T4)
# ---------------------------------------------------------------------------
def go_spc():
    st.session_state["d_view"] = "재질개요"


def view_cause():
    st.caption(T.DESC["공정분석"])
    t1, t2, t3 = st.columns([1.1, 1, 1.6])
    if len(shown) > 1:
        t1.selectbox("분석 재질", shown, key="d_prop", format_func=lambda q: PROP_LABEL.get(q, q),
                     help="원인 분석·조기 감시 기준 재질 (위에서 고른 재질 중)")
    else:
        t1.markdown(f"<div class='tab-summary' style='text-align:left'>분석 재질 <b>{PROP_LABEL[prop]}</b></div>",
                    unsafe_allow_html=True)
    t2.selectbox("문제 코일 기준 (전체 기간일 때)", ds.SIGMAS, key="d_sigma", format_func=lambda s: f"평균 ± {s:.1f}σ",
                 disabled=not full_period, help=T.CARD_HELP["sigma"])
    t3.radio(f"{T.t('side_label')}", list(ds.SIDES), key="d_side", horizontal=True,
             format_func=lambda s: T.t(f"side_{s}"), help=T.HELP["group_outlier"], disabled=not full_period)
    info = []
    if full_period:
        info.append(f"문제 코일 **{len(group):,}개** ({100 * len(group) / max(len(coils), 1):.0f}%) vs {ref_name} {len(ref):,}개"
                    + (" · ⚠️ 10개 미만이라 결론을 믿기 어려워요" if len(group) < 10 else ""))
    b1, b2 = st.columns([3, 1.2], vertical_alignment="center")
    b1.markdown(" · ".join(info) if info else f"{mode_txt} · {group_name} {len(group):,}개 vs {ref_name} {len(ref):,}개")
    if (alarm := N.spc_badge(spc_res)):
        b2.button(alarm, on_click=go_spc, key="spc_badge", type="tertiary", help="누르면 📊 재질개요의 🚨 조기 감시 카드로 가요")
    if comp.get("model_note"):
        st.info(comp["model_note"], icon=":material/info:")

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
    known = [d for d in DEFECTS if d in set(pareto["defect"])] + [d for d in DEFECTS if d not in set(pareto["defect"])]
    if st.session_state["d_defect"] not in DEFECTS:
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
# 🗂 데이터 (prd_v5 T6): 엑셀처럼 고치기 · 행 제외 · 이상치 도우미 · 수정본
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


KEY_COLS = ["coil_no", "grade", "prod_date", "line", "plant", "thk", "YS", "TS", "EL", "defect_type"]
PAGE = 2000


def _edit_state() -> dict:
    """편집 상태 (데이터 파일마다): draft = 지금 편집, snap = 표를 그릴 때 기준, hist = 되돌리기용."""
    es = st.session_state.get("edit_draft")
    if not es or es.get("src") != SOURCE_KEY:
        es = {"src": SOURCE_KEY, "draft": E.empty(), "snap": E.empty(), "hist": [], "ver": 0}
        st.session_state["edit_draft"] = es
    return es


def _reset_editor(es: dict, draft: dict, push: bool = True):
    if push:
        es["hist"].append(E.clone(es["draft"]))
    es["draft"], es["snap"] = draft, E.clone(draft)
    es["ver"] += 1


def view_data():
    st.caption(T.DESC["데이터"])
    es = _edit_state()
    names = pds_names()
    allc = A.all_coils()
    big = len(allc) >= 50000
    d1, d2, d3 = st.columns([1.2, 2.6, 1.2], vertical_alignment="bottom")
    apply_filter = d1.toggle("대시보드 필터 적용", value=True, disabled=big,
                             help="큰 데이터(5만 행 이상)는 화면이 느려지지 않게 필터 결과만 편집해요." if big else None)
    base = (target if apply_filter or big else allc).drop(columns=["month", "thk_band", "has_defect", "passed",
                                                                   "rbar_given"], errors="ignore")
    numeric = [c for c in base.columns if pd.api.types.is_numeric_dtype(base[c]) and c not in E.LOCKED]
    default_cols = [c for c in KEY_COLS if c in base.columns] + [q for q in shown if q in base.columns and q not in KEY_COLS]
    cols = d2.multiselect("보여줄 열", list(base.columns), default=default_cols, key="data_cols",
                          format_func=lambda c: names.get(c, c), help="편집할 열만 골라 보면 빨라요. 번호 열은 고칠 수 없어요.")
    cols = ["coil_no"] + [c for c in cols if c != "coil_no"]
    # 이상치 도우미
    with st.container(border=True):
        st.markdown(TH.card_title("🔍 이상치 도우미"), unsafe_allow_html=True, help=T.CARD_HELP["data"])
        o1, o2, o3, o4 = st.columns([1.6, 0.9, 1.2, 1.3], vertical_alignment="bottom")
        cand = [q for q in grade_props if q in base] + [f for f in numeric if f not in grade_props]
        ocol = o1.selectbox("재질·인자", cand, key="out_col",
                            format_func=lambda c: PROP_SHORT.get(c) or (factor_label(c) if c in FACTORS else names.get(c, c)))
        k = o2.number_input("평균 ± kσ", 1.0, 6.0, 3.0, 0.5, key="out_k")
        shown_df = E.apply(base, es["draft"])
        mask = E.outlier_mask(shown_df, ocol, k, SPEC.get(ocol, (None, None)))
        only = o3.toggle(f"이상치만 보기 ({int(mask.sum())}행)", key="out_only")
        if o4.button(f"표시된 {int(mask.sum())}행 제외", disabled=not mask.any(), width="stretch", key="out_drop"):
            _reset_editor(es, E.exclude(es["draft"], shown_df.loc[mask, "coil_no"]))
            st.rerun()
    # 편집 표
    table = E.apply(base, es["snap"], drop_excluded=False)
    if only:
        bad_ids = set(shown_df.loc[mask, "coil_no"].astype(str))
        table = table[table["coil_no"].astype(str).isin(bad_ids)]
    table = table[["제외"] + [c for c in cols if c in table.columns]].reset_index(drop=True)
    pages = max(1, -(-len(table) // PAGE))
    page = d3.number_input(f"쪽 (1~{pages})", 1, pages, 1, key="data_page") if pages > 1 else 1
    view = table.iloc[(page - 1) * PAGE: page * PAGE].reset_index(drop=True)
    cfg = {"제외": st.column_config.CheckboxColumn("제외", help="체크하면 분석에서 빠져요", width="small")}
    for c in view.columns[1:]:
        cfg[c] = st.column_config.Column(names.get(c, c), disabled=c in E.LOCKED)
    edited = st.data_editor(view, column_config=cfg, hide_index=True, height=480, width="stretch",
                            key=f"editor_{es['ver']}_{page}_{only}")
    new = E.diff(view, edited, es["draft"], original=base)
    if new != es["draft"]:
        es["hist"].append(E.clone(es["draft"]))
        es["draft"] = new
    n_total = E.count(es["draft"])
    st.caption(f"{len(table):,}행 · 바뀐 것: **{E.summary(es['draft'])}**")
    a1, a2, a3, a4, a5 = st.columns(5)
    if a1.button("✅ 분석에 반영", type="primary", width="stretch", disabled=n_total == 0,
                 help="수정본을 새 데이터 파일로 추가하고 모든 탭을 다시 계산해요. 원본은 그대로예요."):
        src = E.edited_source(get_source(), es["draft"])
        src.edit_log = E.log_rows(es["draft"]).to_dict("records")
        datasets.register(src, src.name, keep=st.session_state.get("edit_keep", False))
        st.session_state["pending"] = state_now()  # 수정본으로 바꿔도 보던 필터·탭은 그대로
        st.session_state["toast"] = f"수정본 '{src.name}'으로 다시 계산했어요."
        st.rerun()
    if a2.button("↶ 한 단계 되돌리기", width="stretch", disabled=not es["hist"]):
        _reset_editor(es, es["hist"].pop(), push=False)
        st.rerun()
    if a3.button("⟲ 전체 되돌리기", width="stretch", disabled=n_total == 0):
        _reset_editor(es, E.empty())
        st.rerun()
    a4.toggle("이 PC에 보관", key="edit_keep", help="켜면 수정본을 사용자 폴더에 저장해 앱을 다시 켜도 남아요.")
    xkey = (SOURCE_KEY, E.summary(es["draft"]), len(es["hist"]))
    if st.session_state.get("edit_xlsx", (None,))[0] != xkey:  # 3만 행 Excel은 무거워서 누를 때만 만든다
        if a5.button("Excel 만들기", width="stretch", icon=":material/table_view:", help="지금 편집 내용을 적용한 전체 데이터"):
            out = E.apply(get_source().coils, es["draft"]).drop(columns=["month", "thk_band", "has_defect", "passed"],
                                                                 errors="ignore")
            buf = io.BytesIO()
            with st.spinner("Excel 만드는 중…"):
                out.rename(columns={c: names.get(c, c) for c in out.columns}).loc[:, lambda d: ~d.columns.duplicated()] \
                    .to_excel(buf, index=False)
            st.session_state["edit_xlsx"] = (xkey, buf.getvalue())
            st.rerun()
    else:
        a5.download_button("Excel 다운로드", st.session_state["edit_xlsx"][1], f"{grade}_수정본.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch",
                           icon=":material/download:")
    log = E.log_rows(es["draft"])
    prev = getattr(get_source(), "edit_log", None)
    with st.expander(f"📝 기록 ({len(log)}건)" + (f" · 이 수정본의 기록 {len(prev)}건" if prev else ""), expanded=False):
        if len(log):
            st.dataframe(log, hide_index=True, width="stretch")
        if prev:
            st.caption("지금 보고 있는 수정본을 만들 때의 기록")
            st.dataframe(pd.DataFrame(prev), hide_index=True, width="stretch")
        if not len(log) and not prev:
            st.caption("아직 바꾼 것이 없어요.")


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
    if view == "재질개요":
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
with st.container(key="hdr"):
    open_report = header.render(f"{grade} 품질 현황", THEME, session.query_dict(state, DEFAULTS, False))
edited_note = getattr(get_source(), "edit_note", None)
st.markdown(f"{mode_badge()} {source_badge()}" + (f" :violet-badge[✏️ 수정본 ({edited_note})]" if edited_note else ""))
st.markdown(f":gray-badge[라인 {state['line']}] :gray-badge[{period_txt}] "
            + " ".join(f":gray-badge[{x}]" for x in filter_txt)
            + f" :gray-badge[{mode_txt}]" + (f" {badge(judge)}" if diag["n_baseline"] else ""))
if expired_msg:
    st.warning(expired_msg, icon=":material/history:")

# 큰 탭 + 상단 고정바 (prd_v4 M8 → prd_v5 T1·T3·H2): 탭 · 조건 · 오프라인/AI 모드, 아래 재질 고정카드
st.session_state.setdefault("_last_mode", st.session_state["run_mode"])
with st.container(key="tabbar"):
    tb1, tb2, tb3 = st.columns([4.4, 1.25, 1.9], vertical_alignment="center")
    view = tb1.segmented_control("화면", ds.VIEWS, key="d_view", label_visibility="collapsed",
                                 format_func=lambda v: f"{ds.VIEW_ICON[v]} {v}") or "재질개요"
    tb2.markdown(f"<div class='tab-summary'>{grade} · {period_txt if full_period else period_txt.replace(' ~ ', '~')}"
                 f"{' · ' + state['line'] if state['line'] != '전체' else ''} · {PROP_SHORT[prop]}</div>",
                 unsafe_allow_html=True)
    tb3.segmented_control("모드", list(router.MODE_LABEL), key="run_mode", format_func=MODE_TEXT.get,
                          label_visibility="collapsed", on_change=on_mode, help=T.CARD_HELP["mode"])
    if view in ("재질개요", "공정분석") and not target.empty:
        m1, m2 = st.columns([1.75, 6], vertical_alignment="center")
        m1.pills("재질", grade_props, key="d_props", selection_mode="multi", format_func=lambda q: PROP_SHORT.get(q, q),
                 on_change=on_material, label_visibility="collapsed", help="여러 개 고를 수 있어요. 다 끄면 TS로 보여줘요.")
        with m2:
            kpi_strip()

if view == "코일분석":  # 필터와 별개로 번호로 조회
    st.caption(T.DESC["코일분석"])
    coil_view.render(state, SOURCE_KEY)
elif target.empty:
    st.info(f"조건에 맞는 코일이 없어요. {grade}은(는) {A.grade_info(grade).get('lines', '-')} 라인에서 생산돼요. "
            "기간·규격약호·출강목표·용도코드·두께를 바꿔 보세요.", icon=":material/search_off:")
    st.button("필터 초기화", on_click=reset_filters, key="reset_empty", icon=":material/restart_alt:")
else:
    {"재질개요": view_material, "공정분석": view_cause, "결함분석": view_defect}.get(view, view_data)()

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
