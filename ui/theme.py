"""파랑 계열 테마, 다크/라이트 전환, 글꼴, 차트 출력 (prd_v3 U2·U3·U6, prd_v4 A1·M5·M7·M8·T1).

다크/라이트 전환은 Streamlit 자체 테마 옵션을 쓴다: 주소에 embed=true&embed_options=dark_theme(light_theme)를
붙여 다시 열면 모든 위젯이 .streamlit/config.toml의 해당 테마로 그려진다. "자동"은 옵션 없이 OS 설정을 따른다.
세션 ID(sid)가 주소에 있어 다시 열어도 필터·대화·업로드는 유지된다 (ui/session.py).
글꼴은 config.toml에서 현대하모니(HDharmony) 한 묶음으로 등록했다: 굵기 400 = L(기본), 500 = M, 700 = B.
차트는 Plotly 템플릿을 직접 정해 테마와 맞추고, 카드 제목과 겹치는 그래프 안 제목은 지운다.
"""
import streamlit as st

THEMES = {"auto": "자동", "light": "☀ 라이트", "dark": "☾ 다크"}
FONT = "HDharmony, 'Malgun Gothic', sans-serif"
PALETTE = {
    "light": {"text": "#0F172A", "muted": "#475569", "grid": "rgba(100,116,139,0.18)"},
    "dark": {"text": "#E2E8F0", "muted": "#94A3B8", "grid": "rgba(148,163,184,0.18)"},
}
EMBED = {"light": "light_theme", "dark": "dark_theme"}


def choice_from_url() -> str:
    """지금 테마 선택. Streamlit은 embed 값을 st.query_params에서 숨기므로 같이 붙인 th 값으로 읽는다."""
    th = st.query_params.get("th", "")
    return th if th in EMBED else "auto"


def theme_params(choice: str) -> dict:
    """그 테마로 열 때 주소에 붙일 값 (자동이면 없음)."""
    return {"embed": "true", "embed_options": EMBED[choice], "th": choice} if choice in EMBED else {}


def effective(choice: str | None) -> str:
    """실제로 보일 테마 (light/dark)."""
    if choice in ("light", "dark"):
        return choice
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # 테마 정보를 못 읽으면 라이트
        return "light"


def inject(choice: str | None = None):
    """공통 CSS (글꼴 굵기, 카드, 고정 탭바, 떠 있는 AI 아이콘·말풍선, 팝업 위치)."""
    st.html(f"<style>{COMMON_CSS}</style>")


def plotly_template(choice: str | None) -> dict:
    p = PALETTE[effective(choice)]
    return {"template": "plotly_dark" if effective(choice) == "dark" else "plotly_white",
            "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
            "font": dict(family=FONT, color=p["text"], size=12)}


def show(fig, choice: str | None, key: str | None = None, keep_title: bool = False, height: int | None = None):
    """차트를 테마에 맞춰 출력한다. 카드 제목이 결론을 말하므로 그래프 안 제목은 지운다 (prd_v4 M7).
    height를 주면 그 높이로 고정한다 (prd_v5 L1: 같은 줄 카드 높이 맞춤)."""
    fig.update_layout(**plotly_template(choice))
    if not keep_title:
        fig.update_layout(title=None, margin=dict(t=36))
    if height:
        fig.update_layout(height=height)
    st.plotly_chart(fig, theme=None, width="stretch", key=key, config={"displaylogo": False})


def card_title(text: str, sub: str | None = None) -> str:
    """그래프 카드 제목 HTML (현대하모니 B). 두 줄 높이 고정, 길면 글자 한 단계 작게 (prd_v5 L1). sub는 옆에 작게."""
    from html import escape
    t = escape(text).replace("**", "")
    s = f"<span class='card-sub'>{escape(sub)}</span>" if sub else ""
    size = " long" if len(text) > 34 else ""
    return f"<div class='card-title{size}'>{t}{s}</div>"


COMMON_CSS = """
/* 글꼴 굵기: L 400 기본, M 500, B 700 (prd_v4 T1) */
html, body, .stApp {font-family: HDharmony, 'Malgun Gothic', sans-serif;}
.stApp button, .stApp [data-testid="stWidgetLabel"] p, .stApp [data-baseweb="tab"], .stApp [data-testid="stBadge"],
.stApp [data-testid="stExpander"] summary p {font-weight: 500;}
h1, h2, h3, .card-title, [data-testid="stMetricValue"] {font-weight: 700 !important;}
.block-container {padding-top: 1.4rem; padding-bottom: 6rem;}
h1 {font-size: 1.8rem !important; margin-bottom: 0 !important;}
[data-testid="stMetricValue"] {font-size: 1.8rem;}
/* 그래프 카드 제목 (prd_v4 M7 → prd_v5 L1): 굵게, 두 줄 높이 고정 → 같은 줄 카드 높이가 같다 */
.card-title {font-size: 1.2rem; line-height: 1.35; margin: 0.1rem 0 0.2rem 0; word-break: keep-all;
  min-height: 2.7em; display: flex; align-items: flex-start;}
.card-title.long {font-size: 1.04rem;}
/* 해석 한 줄 (prd_v5 C1): 높이 고정, 넘치면 말줄임 (전체 문장은 마우스를 올리면) */
.card-note {font-size: 0.86rem; line-height: 1.5; height: 1.5em; opacity: 0.85; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis;}
/* 강종개요 구역 제목 (prd_v5 T2) */
.sec-title {font-size: 1.45rem; font-weight: 700; margin: 1.1rem 0 0.1rem 0; padding-bottom: 4px;
  border-bottom: 2px solid rgba(29,78,216,.35);}
.sec-desc {font-size: 0.8rem; font-weight: 400; opacity: 0.65; margin-left: 0.7rem;}
/* 재질 고정카드 (prd_v5 T3·L1): 같은 폭·높이 압축형, 최대 6장 */
.kpi-strip {display: grid; gap: 8px;}
.kpi {border: 1px solid rgba(100,116,139,.35); border-radius: 10px; padding: 3px 10px; height: 82px; overflow: hidden;}
.kpi.focus {border-color: #1D4ED8; box-shadow: inset 0 0 0 1px #1D4ED8;}
.kpi.bad {border: 2px solid #DC2626;}
.kpi .kpi-row {display: flex; align-items: center; justify-content: space-between; gap: 6px; flex-wrap: nowrap;}
.kpi .kpi-num {font-size: 1.45rem;}
.kpi-svg {flex: 0 0 auto;}
@media (max-width: 1400px) {.kpi-svg {display: none;}}
.card-sub {font-size: 0.85rem; font-weight: 500; opacity: 0.7; margin-left: 0.5rem;}
.chart-note {font-size: 0.9rem; line-height: 1.5; opacity: 0.85;}
/* 재질 요약 카드 (prd_v4 M5): 이름 M, 숫자 B, 작은 히스토그램 */
.kpi-head {font-weight: 500; font-size: 0.9rem; white-space: nowrap;} .kpi-spec {font-size: 0.78rem; opacity: 0.75; margin-left: 4px;}
.kpi-row {display: flex; align-items: center; gap: 10px; flex-wrap: wrap;}
.kpi-num {font-weight: 700; font-size: 1.8rem; line-height: 1.1;}
.kpi-delta {font-size: 0.8rem; font-weight: 500;} .kpi-delta.up {color: #EA7A2C;} .kpi-delta.down {color: #1D4ED8;}
.kpi-foot {font-size: 0.76rem; opacity: 0.85; margin-top: 0; white-space: nowrap;}
[class*="st-key-card_bad_"] {border: 2px solid #DC2626 !important; border-radius: 0.6rem;}
/* 큰 탭 + 상단 고정바 (prd_v4 M8) */
/* 키를 단 컨테이너는 같은 높이의 감싸개(stLayoutWrapper) 안에 있어, 감싸개를 고정해야 스크롤 동안 붙어 있다 */
/* Streamlit 기본 머리글(» 사이드바 열기 · ⋮ 메뉴)이 상단바를 흰 바탕으로 가리지 않게: 바탕 투명, 높이 0,
   » 버튼만 남겨 상단바 왼쪽 빈자리에 둔다. ⋮ 메뉴(테마·설정)는 앱 상단바 버튼이 대신한다 (prd_v8 U2) */
header[data-testid="stHeader"] {background: transparent !important; height: 0 !important; min-height: 0 !important;
  pointer-events: none;}
header[data-testid="stHeader"] [data-testid="stExpandSidebarButton"],
header[data-testid="stHeader"] [data-testid="stSidebarCollapsedControl"] {pointer-events: auto; position: fixed; top: 14px;
  left: 10px; z-index: 999995;}
header[data-testid="stHeader"] [data-testid="stMainMenu"], header[data-testid="stHeader"] [data-testid="stAppDeployButton"],
header[data-testid="stHeader"] [data-testid="stDecoration"] {display: none !important;}
header[data-testid="stHeader"] [data-testid="stExpandSidebarButton"] button {background: var(--background-color, #fff); border-radius: 8px;}
[data-testid="stLayoutWrapper"]:has(> .st-key-tabbar) {position: sticky; top: 0; z-index: 990;}
.st-key-tabbar {padding: 6px 0 4px 0; background: #fff; box-shadow: 0 6px 10px -8px rgba(15,23,42,.35);}
.stApp .st-key-tabbar .st-key-d_view [data-testid="stButtonGroup"] button {min-height: 48px; padding: 0 22px; font-size: 1.05rem;
  font-weight: 500;}
.stApp .st-key-tabbar .st-key-d_view [data-testid="stButtonGroup"] button[aria-checked="true"] {font-weight: 700;
  box-shadow: inset 0 -3px 0 #1D4ED8;}
.tab-summary {text-align: right; font-size: 0.82rem; opacity: 0.75; white-space: nowrap;}
/* 상단바 (prd_v8 U1·U2): 탭은 밑줄형, 오른쪽 버튼은 같은 높이 36px */
.stApp .st-key-tabbar .st-key-d_view [data-testid="stButtonGroup"] button {border: none !important; background: transparent !important;
  border-radius: 0 !important;}
.stApp .st-key-tabbar .st-key-d_view [data-testid="stButtonGroup"] button[aria-checked="true"] {color: #1D4ED8 !important;}
/* 상단바 오른쪽 도구 (prd_v8 U1): 모두 높이 36px, 아이콘 버튼은 36×36, 간격 8px, 세로 가운데 */
.st-key-tabrow {flex-wrap: nowrap !important; gap: 12px !important;}
.st-key-tabrow > div {min-width: 0;}
.st-key-tools {gap: 8px !important; align-items: center !important; flex-wrap: nowrap !important;}
.st-key-tools > div {margin: 0 !important;}
.st-key-tools button {height: 36px !important; min-height: 36px !important; border-radius: 8px !important;}
.st-key-tools [data-testid="stPopover"] button {width: 36px; padding: 0 !important; justify-content: center;}
.st-key-tools [data-testid="stPopover"] button > div {justify-content: center; gap: 0; margin: 0 !important; width: 100%;}
/* 팝오버 화살표 자리(숨긴 아이콘의 감싸개)가 16px를 차지해 아이콘이 왼쪽으로 밀리던 문제: 감싸개째 숨김 */
.st-key-tools [data-testid="stPopover"] button > div > div:last-child:has([data-testid="stIconMaterial"]) {display: none;}
.st-key-tools .tab-summary {margin: 0 4px; line-height: 36px;}
/* 코일분석 조건 카드: 단계 번호 · 요약 줄 · 실행 버튼 */
.coil-step {display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 0.95rem; margin: 2px 0 6px;}
.coil-step b {display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px;
  border-radius: 50%; background: #1D4ED8; color: #fff; font-size: 0.8rem;}
.st-key-coil_run_row {border-top: 1px solid rgba(100,116,139,.25); padding-top: 12px; margin-top: 2px;}
.st-key-coil_run_row > div:first-child {flex: 1 1 auto; min-width: 0;}
.coil-sum {font-size: 0.92rem; color: inherit; opacity: .85;}
.coil-sum.stale {color: #C2410C; opacity: 1;}
.st-key-coil_run_btn button {min-width: 150px; height: 42px;}
.st-key-coil_form [data-testid="stPills"] [data-testid="stButtonGroup"] {flex-wrap: nowrap;}
/* 감시 조건 추천 프리셋: 버튼 글자가 줄바꿈되지 않게 글자 길이만큼 */
.st-key-spc_presets [data-testid="stElementContainer"] {flex: 1 1 auto !important; width: auto !important; min-width: max-content;}
.st-key-spc_presets button {white-space: nowrap; min-width: max-content;}
.st-key-spc_presets button p {white-space: nowrap;}
/* AI on/off 스위치: 다른 버튼과 같은 높이 36px 상자 */
.st-key-ai_switch {height: 36px !important; min-height: 36px; box-sizing: border-box; padding: 0 10px; border: 1px solid rgba(100,116,139,.45); border-radius: 8px;
  display: flex !important; align-items: center; justify-content: center; width: auto !important;}
.st-key-ai_switch label {margin: 0 !important; white-space: nowrap; align-items: center !important; height: 34px;}
.st-key-ai_switch label > div:not([data-testid]) {margin-top: 0 !important;}  /* 스위치 막대를 글자와 같은 높이 가운데로 */
.st-key-ai_switch label {flex-direction: row-reverse; gap: 8px;}  /* 스위치를 글자 오른쪽으로 */
.st-key-ai_switch label > div:not([data-testid]) {margin-right: 0 !important; margin-left: 0 !important;}
.st-key-ai_switch [data-testid="stElementContainer"], .st-key-ai_switch [data-testid="stCheckbox"] {height: 34px;}
.st-key-ai_switch label p {font-size: 0.9rem;}
.st-key-ai_switch:has(input:checked) {border-color: #1D4ED8; background: rgba(59,130,246,.10);}
.st-key-tools [data-testid="stMarkdownContainer"] p {margin: 0;}
.st-key-tabbar .stButton button, .st-key-tabbar [data-testid="stPopover"] button {height: 36px; min-height: 36px;
  border-radius: 8px; padding: 0 8px;}
.st-key-tabbar [data-testid="stPopover"] button [data-testid="stIconMaterial"]:last-child {display: none;}
.st-key-tabbar .st-key-run_mode button {min-height: 36px !important; padding: 0 10px !important; white-space: nowrap;}
.st-key-run_mode [data-testid="stButtonGroup"], .st-key-run_mode [data-testid="stButtonGroup"] > div,
.st-key-gk_view [data-testid="stButtonGroup"], .st-key-gk_view [data-testid="stButtonGroup"] > div {flex-wrap: nowrap !important;}
.st-key-gk_view button {flex: 0 0 auto; min-width: max-content; padding: 0 10px !important; white-space: nowrap;}
@media (max-width: 1500px) {.st-key-gk_view button {padding: 0 3px !important;} .st-key-gk_view button p {font-size: 0.74rem !important;}}
.st-key-run_mode button {flex: 0 0 auto; min-width: max-content;}
/* 조건 칩 (prd_v8 U3) */
.st-key-chips {gap: 6px !important; flex-wrap: wrap;}
.st-key-chips button {min-height: 26px !important; padding: 0 10px !important; border-radius: 999px !important;
  border: 1px solid rgba(100,116,139,.35) !important; font-size: 0.8rem;}
.chip {display: inline-block; padding: 2px 10px; border-radius: 999px; border: 1px solid rgba(100,116,139,.35);
  font-size: 0.8rem; opacity: .9;}
/* 강종개요 카드 (prd_v8 G1): 카드 전체가 버튼 (투명 버튼을 위에 겹침) */
[class*="st-key-gk_"], [class*="st-key-pc_"] {position: relative;}
[class*="st-key-pc_"] [class*="st-key-pcbtn_"] {position: absolute !important; inset: 0; z-index: 5; margin: 0 !important;
  width: 100% !important; height: 100% !important;}
[class*="st-key-pc_"] [class*="st-key-pcbtn_"] .stButton, [class*="st-key-pc_"] [class*="st-key-pcbtn_"] .stButton > div,
[class*="st-key-pc_"] [class*="st-key-pcbtn_"] [data-testid="stTooltipIcon"],
[class*="st-key-pc_"] [class*="st-key-pcbtn_"] [data-testid="stTooltipHoverTarget"] {position: static !important;
  display: block !important; width: 100% !important; height: 100% !important;}
[class*="st-key-pc_"] [class*="st-key-pcbtn_"] button {position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0;
  cursor: pointer;}
[class*="st-key-pc_"]:hover .ov-tile {border-color: #1D4ED8;}
.ov-tile.pc.on {border: 2px solid #1D4ED8;}
/* 버튼을 감싼 Streamlit 요소 상자(position: relative)째 카드 전체로 펼쳐 맨 위에 둔다 — 그림 어디를 눌러도 선택 */
[class*="st-key-gk_"] [class*="st-key-gkbtn_"] {position: absolute !important; inset: 0; z-index: 5; margin: 0 !important;
  width: 100% !important; height: 100% !important;}
[class*="st-key-gk_"] [class*="st-key-gkbtn_"] .stButton, [class*="st-key-gk_"] [class*="st-key-gkbtn_"] .stButton > div,
[class*="st-key-gk_"] [class*="st-key-gkbtn_"] [data-testid="stTooltipIcon"],
[class*="st-key-gk_"] [class*="st-key-gkbtn_"] [data-testid="stTooltipHoverTarget"] {position: static !important;
  display: block !important; width: 100% !important; height: 100% !important;}
[class*="st-key-gk_"] [class*="st-key-gkbtn_"] button {position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0;
  cursor: pointer;}
[class*="st-key-gk_"]:hover .gk {border-color: #1D4ED8;}
.gk {border: 1px solid rgba(100,116,139,.35); border-radius: 12px; padding: 8px 10px 6px 10px; height: 138px;
  overflow: hidden; display: flex; flex-direction: column;}
.gk.on {border: 2px solid #1D4ED8;} .gk.bad .gk-fail {color: #DC2626;}
.gk-head {font-size: 0.86rem; white-space: nowrap; overflow: hidden;} .gk-head span {font-size: 0.72rem; opacity: .7; margin-left: 4px;}
.gk-num {font-size: 1.5rem; font-weight: 700; line-height: 1.2;}
.gk-fail {font-size: 0.78rem; color: #EA7A2C; font-weight: 500;} .gk-fail.none {color: inherit; opacity: .55;}
.gk-help {display: inline-block; width: 15px; height: 15px; line-height: 13px; text-align: center; border-radius: 50%;
  border: 1px solid currentColor; font-size: 10px; opacity: .6; cursor: help;}
.gk-svg {margin-top: auto;}
/* 기본 정보 가로 표 + 공정 카드 (prd_v8 B1·B2) */
.ov-wrap {overflow-x: auto; border: 1px solid rgba(100,116,139,.3); border-radius: 12px;}
table.ov {border-collapse: collapse; width: 100%; font-size: 0.8rem;}
table.ov th {background: rgba(59,130,246,.08); font-weight: 500; padding: 6px 8px; text-align: left; white-space: nowrap;}
table.ov td {padding: 6px 8px; vertical-align: top; border-top: 1px solid rgba(100,116,139,.2); word-break: keep-all;}
/* 재질 카드와 같은 크기: 재질 격자 = 화면 60%(- 16px)를 4칸, 간격 16px → 카드 폭 15% - 16px, 높이 138px */
.ov-grid {display: grid; grid-template-columns: repeat(auto-fill, calc(15% - 16px)); gap: 16px; margin-bottom: 14px;}
.ov-group {font-size: 1.02rem; font-weight: 700; margin: 6px 0 6px 2px;}
.ov-group span {font-size: 0.76rem; font-weight: 400; opacity: .65; margin-left: 8px;}
.ov-stage {font-size: 0.68rem !important; font-weight: 500; padding: 1px 6px; border-radius: 999px; margin: 0 6px 0 0 !important;
  background: rgba(59,130,246,.12); color: #1D4ED8; opacity: 1 !important;}
.ov-tile.pc .gk-head {white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.ov-tile.empty {opacity: .65;}
.ov-tile {border: 1px solid rgba(100,116,139,.35); border-radius: 12px; padding: 8px 10px 6px 10px; height: 138px;
  display: flex; flex-direction: column; gap: 4px; overflow: hidden;}
.ov-t {font-size: 0.86rem; font-weight: 700;}
.ov-num {font-size: 1.5rem; font-weight: 700; line-height: 1.15;} .ov-num.sm {font-size: 1.15rem;}
.ov-num small {font-size: 0.75rem; font-weight: 400; opacity: .7; margin-left: 3px;}
.ov-sub {font-size: 0.72rem; opacity: .7; margin-top: auto;}
.ov-bar {display: flex; height: 12px; border-radius: 6px; overflow: hidden; margin-top: 4px;}
.ov-bar span {display: block; height: 100%;}
.ov-legend {display: flex; flex-wrap: wrap; gap: 2px 10px; font-size: 0.74rem;}
.ov-legend i {display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 4px;}
.ov-chips {display: flex; flex-wrap: wrap; gap: 4px;}
.ov-chip {font-size: 0.78rem; padding: 2px 8px; border-radius: 999px; background: rgba(59,130,246,.12); color: #1D4ED8;}
.ov-none {font-size: 0.78rem; opacity: .6;}
.pc-grid {display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px;}
.gk.pc {height: 118px;} .pc-sigma {font-size: 0.8rem; opacity: .85;} .pc-foot {font-size: 0.72rem; opacity: .75;}
.st-key-tabbar .stButton button p, .st-key-run_mode button p {white-space: nowrap;}
@media (max-width: 1700px) {.st-key-tools .tab-summary {display: none;}}
@media (max-width: 1500px) {.tab-summary {display: none;}
  .stApp .st-key-tabbar .st-key-d_view [data-testid="stButtonGroup"] button {padding: 0 6px !important; min-height: 36px;}
  .stApp .st-key-tabbar .st-key-d_view [data-testid="stButtonGroup"] button p {font-size: 0.84rem !important;}
  .st-key-tabbar .stButton button {padding: 0 4px;} .st-key-tabbar .stButton button p {font-size: 0.8rem;}
  .gk-num {font-size: 1.2rem;} .gk .kpi-delta {display: none;} .gk-head span {display: none;}
  .st-key-run_mode button {padding: 0 6px !important;}}
@media (max-width: 1500px) {.stApp .st-key-tabbar .st-key-d_view [data-testid="stButtonGroup"] button {min-height: 42px; padding: 0 11px;}
  .stApp .st-key-tabbar .st-key-d_view [data-testid="stButtonGroup"] button p {font-size: 0.9rem;} .tab-summary {font-size: 0.72rem;}}
/* 머리글 오른쪽 위 버튼 4개 (prd_v5 H1): 같은 높이 40px, 같은 모서리, 아이콘 18px */
.st-key-hdr [data-testid="stColumn"] button {height: 40px; min-height: 40px; border-radius: 10px; padding: 0 10px;}
.st-key-hdr [data-testid="stColumn"] button p {font-size: 18px; line-height: 1;}
.st-key-hdr [data-testid="stColumn"] button[kind="secondary"] p {font-size: 0.95rem;}
.st-key-hdr [data-testid="stPopover"] button p {font-size: 18px;}
.st-key-hdr [data-testid="stPopover"] button [data-testid="stIconMaterial"] {display: none;}
.theme-item {display: block; padding: 6px 10px; border-radius: 8px; text-decoration: none; color: inherit;}
.theme-item:hover {background: rgba(59,130,246,.12);} .theme-item.on {font-weight: 700; color: #1D4ED8;}
/* 머리글 버튼은 줄바꿈하지 않는다 (1366px에서 "자 동", "API 키"처럼 쪼개지던 문제) */
.theme-links a, .stApp [data-testid="stPopover"] button p, .stApp [data-testid="stBaseButton-secondary"] p {white-space: nowrap;}
@media (max-width: 1500px) {.theme-links a {padding: 6px 9px; font-size: 0.8rem;}}
/* 테마 전환 링크 (머리글) */
.theme-links {display: flex; gap: 0; justify-content: flex-end;}
.theme-links a {padding: 6px 14px; border: 1px solid rgba(100,116,139,.45); font-size: 0.85rem; text-decoration: none;
  color: inherit; font-weight: 500;}
.theme-links a:first-child {border-radius: 8px 0 0 8px;} .theme-links a:last-child {border-radius: 0 8px 8px 0;}
.theme-links a + a {border-left: none;}
.theme-links a.on {background: #1D4ED8; color: #fff; border-color: #1D4ED8;}
/* 사이드바 즐겨찾기 목록 (prd_v4 L4): 작게 */
.st-key-fav_list button {min-height: 26px; padding: 0 8px; font-size: 0.8rem; justify-content: flex-start;}
.st-key-fav_list [data-testid="stHorizontalBlock"] {gap: 2px;}
/* AI 에이전트 아이콘 (prd_v4 A1): 밝은색, 스크롤하면 늦게 따라옴(ui/chat.py 스크립트) */
.st-key-agent_fab {position: fixed; right: 28px; bottom: 28px; z-index: 999990; width: auto !important;
  transition: transform .45s cubic-bezier(.2,.8,.2,1);}
.st-key-agent_fab button {width: 64px; height: 64px; border-radius: 50%; font-size: 28px; padding: 0;
  background: radial-gradient(circle at 30% 30%, #FFFFFF 0%, #E0F2FE 60%, #BAE6FD 100%); color: #0369A1;
  border: 3px solid #38BDF8; box-shadow: 0 6px 18px rgba(56,189,248,.45);
  transition: transform .15s ease, box-shadow .15s ease;}
.st-key-agent_fab button:hover {transform: scale(1.12); box-shadow: 0 10px 26px rgba(56,189,248,.6); border-color: #60A5FA;}
.st-key-agent_fab button p {font-size: 28px;}
.st-key-agent_fab.busy button {animation: fabspin 1.2s linear infinite;}
@keyframes fabspin {0% {box-shadow: 0 0 0 0 rgba(56,189,248,.6);} 100% {box-shadow: 0 0 0 14px rgba(56,189,248,0);}}
.fab-badge {position: fixed; right: 26px; bottom: 82px; z-index: 999991; background: #DC2626; color: #fff;
  border-radius: 999px; padding: 1px 7px; font-size: 12px; font-weight: 700; pointer-events: none;}
.fab-tip {position: fixed; right: 100px; bottom: 46px; z-index: 999991; background: #0F172A; color: #fff;
  border-radius: 8px; padding: 4px 10px; font-size: 12px; opacity: 0; transition: opacity .15s; pointer-events: none;}
body:has(.st-key-agent_fab:hover) .fab-tip {opacity: .92;}
.fab-off {position: fixed; right: 18px; bottom: 12px; z-index: 999991; font-size: 11px; color: #64748B; pointer-events: none;}
/* 추천 질문 말풍선 (prd_v4 A2): 아이콘 위, 8초 뒤 사라짐 */
.st-key-agent_bubble {position: fixed; right: 26px; bottom: 104px; z-index: 999992; width: 300px !important;
  background: #FFFFFF; color: #0F172A; border: 1px solid #BAE6FD; border-radius: 14px; padding: 10px 12px 8px 12px;
  box-shadow: 0 10px 28px rgba(2,132,199,.25); animation: bubblein .25s ease-out, bubbleout .4s ease-in 8s forwards;}
.st-key-agent_bubble::after {content: ""; position: absolute; right: 26px; bottom: -9px; border-width: 9px 9px 0 9px;
  border-style: solid; border-color: #FFFFFF transparent transparent transparent;}
.st-key-agent_bubble p {color: #0F172A !important; font-size: 0.82rem;}
.st-key-agent_bubble button {min-height: 30px; font-size: 0.82rem; text-align: left; justify-content: flex-start;
  background: #F0F9FF; color: #0C4A6E; border-color: #BAE6FD;}
@keyframes bubblein {from {opacity: 0; transform: translateY(8px);} to {opacity: 1; transform: none;}}
@keyframes bubbleout {to {opacity: 0; visibility: hidden;}}
@media (prefers-reduced-motion: reduce) {.st-key-agent_fab, .st-key-agent_bubble, .st-key-agent_fab button {
  transition: none !important; animation: none !important;}}
/* 에이전트 팝업: 오른쪽 패널형, 화면 높이 80% (1366px 이하는 전체 화면) */
[data-testid="stDialog"] div:has(> [role="dialog"] .st-key-agent_panel) {width: min(760px, 96vw) !important;
  max-width: 96vw !important; margin: 2vh 24px 2vh auto !important;}
[role="dialog"]:has(.st-key-agent_panel) {width: 100% !important; height: 80vh !important; overflow-y: auto;}
@media (max-width: 1366px) {
  [data-testid="stDialog"] div:has(> [role="dialog"] .st-key-agent_panel) {width: 100vw !important;
    max-width: 100vw !important; margin: 0 !important;}
  [role="dialog"]:has(.st-key-agent_panel) {height: 100vh !important; border-radius: 0;}
}
/* 강종개요 통일 (글꼴 4단계 · 간격 16px): 카드 제목 0.86rem 굵게 / 큰 숫자 1.5rem / 상태 줄 0.8rem / 보조 0.75rem.
   카드 사이 가로·세로 16px, 묶음 제목 위 24px·아래 8px. */
.ov-t, .gk-head, .gk-head b {font-size: 0.86rem !important; font-weight: 700 !important;}
.ov-num, .ov-num.sm, .gk-num {font-size: 1.5rem !important; font-weight: 700; line-height: 1.2;}
.gk-fail, .pc-sigma {font-size: 0.8rem !important; font-weight: 500;}
.ov-sub, .ov-legend, .ov-chip, .ov-none, .pc-foot, .ov-num small, .gk-head span:not(.ov-stage) {font-size: 0.75rem !important; font-weight: 400 !important;}
.ov-stage {font-size: 0.7rem !important;}
.gk, .ov-tile {margin: 0 !important;}
[class*="st-key-gk_"]:not(.st-key-gk_big):not(.st-key-gk_view), [class*="st-key-pc_"]:not(.st-key-pc_big) {margin-bottom: 0 !important;}
.st-key-gkgrid, .st-key-pcgrid {gap: 16px !important;}
.st-key-gkgrid [data-testid="stMarkdownContainer"], .st-key-pcgrid [data-testid="stMarkdownContainer"] {margin-bottom: 0 !important;}
.ov-group {margin: 24px 0 8px 2px !important; line-height: 1.6;}
.ov-grid {margin-bottom: 0 !important;}
"""
