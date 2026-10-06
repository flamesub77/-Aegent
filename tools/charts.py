"""대시보드 Plotly 차트.

색상 규칙 (화면 전체 공통): 상향=주황, 하향=파랑, 중립 그룹=슬레이트, 비교 대상(정상·나머지 기간)=연회색, 스펙선·스펙 이탈=빨강.
배경은 투명으로 두어 Streamlit 라이트/다크 테마를 그대로 따른다.
"""
import pandas as pd
import plotly.graph_objects as go

from tools.domain import PROP_SHORT, PROP_UNIT, factor_label, factor_unit

UP = "#E8833A"
DOWN = "#2F6FDE"
GROUP = "#64748B"
BASE = "#A7B1BF"
SPEC = "#D64545"
FAINT = 0.35
THK_ORDER = ["~0.75", "0.75~1.0", "1.0~1.4", "1.4~"]


def pl(prop: str) -> str:
    """재질 표시 이름 (단위 포함). 무차원 지표(r̄·n·Δr)는 단위 생략."""
    u = PROP_UNIT.get(prop, "")
    return PROP_SHORT.get(prop, prop) + ("" if u in ("", "-") else f" ({u})")


def direction_color(judgement_or_side: str | None) -> str:
    """판정(상향/하향 ...) 또는 이탈군 방향(high/low)을 색으로."""
    v = judgement_or_side or ""
    if v.startswith("상향") or v == "high":
        return UP
    if v.startswith("하향") or v == "low":
        return DOWN
    return GROUP


def _sign_color(x: float) -> str:
    return UP if x > 0 else DOWN


def _bar_range(values):
    """막대 끝 숫자가 축 라벨·가장자리에 잘리지 않도록 x축 여백을 준다."""
    lo, hi = min(min(values), 0), max(max(values), 0)
    span = (hi - lo) or 1
    return [lo - 0.4 * span if lo < 0 else -0.05 * span, hi + 0.3 * span if hi > 0 else 0.05 * span]


def _layout(fig, title, height=340, **kw):
    fig.update_layout(title=dict(text=title, font=dict(size=14), x=0, xanchor="left"), height=height,
                      margin=dict(l=8, r=8, t=52, b=8),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=1, xanchor="right",
                                  bgcolor="rgba(0,0,0,0)"),
                      font=dict(family="Pretendard, 'Malgun Gothic', sans-serif", size=12),
                      hoverlabel=dict(font_size=12), **kw)
    fig.update_xaxes(gridcolor="rgba(128,128,128,0.18)", zeroline=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.18)", zeroline=False)
    return fig


def empty(title="데이터 없음", note="조건에 맞는 데이터가 없습니다."):
    fig = go.Figure()
    fig.add_annotation(text=note, showarrow=False, font=dict(size=13, color="#888"), x=0.5, y=0.5,
                       xref="paper", yref="paper")
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _layout(fig, title, height=260)


def _spec_lines(fig, spec, axis="x"):
    lo, hi = spec
    for v, name, pos in ((lo, "하한", "top left"), (hi, "상한", "top right")):
        if v is None:
            continue
        line = dict(color=SPEC, dash="dash", width=1.5)
        if axis == "x":
            fig.add_vline(x=v, line=line, annotation_text=f"스펙 {name} {v:g}",
                          annotation_font_color=SPEC, annotation_position=pos)
        else:
            fig.add_hline(y=v, line=line, annotation_text=f"스펙 {name} {v:g}",
                          annotation_font_color=SPEC, annotation_position="top left")


def histogram(target: pd.DataFrame, baseline: pd.DataFrame, prop: str, spec, target_name="이 기간",
              color=GROUP, ref_name="나머지 기간"):
    if target.empty:
        return empty(f"{PROP_SHORT.get(prop, prop)} 분포")
    fig = go.Figure()
    if len(baseline):
        fig.add_histogram(x=baseline[prop], name=f"{ref_name} (n={len(baseline)})", marker_color=BASE,
                          opacity=0.55, histnorm="percent", nbinsx=30)
    fig.add_histogram(x=target[prop], name=f"{target_name} (n={len(target)})", marker_color=color,
                      opacity=0.8, histnorm="percent", nbinsx=30)
    _spec_lines(fig, spec)
    return _layout(fig, f"{PROP_SHORT.get(prop, prop)} 분포", barmode="overlay",
                   xaxis_title=pl(prop), yaxis_title="비율 (%)")


def monthly_box(df: pd.DataFrame, prop: str, spec, period=(None, None), color=GROUP):
    if df.empty:
        return empty(f"월별 {prop} 추이")
    fig = go.Figure()
    start, end = period
    for month, g in df.groupby("month"):
        selected = bool(start or end) and (not start or month >= start[:7]) and (not end or month <= end[:7])
        fig.add_box(y=g[prop], name=month, marker_color=color if selected else BASE,
                    boxmean=True, showlegend=False)
    _spec_lines(fig, spec, axis="y")
    note = " · 색칠 = 선택 기간" if (start or end) else ""
    return _layout(fig, f"월별 {PROP_SHORT.get(prop, prop)} 추이{note}", yaxis_title=pl(prop))


def heatmap(hm: pd.DataFrame, prop: str):
    if hm.empty:
        return empty(f"강종 × 월 {prop} 편차")
    pv = hm.pivot(index="grade", columns="month", values="z")
    mean = hm.pivot(index="grade", columns="month", values="mean")
    z = pv.values.round(1) + 0.0  # -0.0 표시 방지
    fig = go.Figure(go.Heatmap(
        z=z, x=pv.columns, y=pv.index, zmid=0, zmin=-2.5, zmax=2.5, xgap=2, ygap=2,
        colorscale=[[0, DOWN], [0.5, "rgba(160,170,185,0.12)"], [1, UP]],
        colorbar=dict(title="σ", thickness=12),
        text=[[f"{v:.1f}" for v in row] for row in mean.values], texttemplate="%{z:+.1f}σ",
        hovertemplate="%{y} · %{x}<br>편차 %{z:+.2f}σ<br>평균 %{text}<extra></extra>"))
    fig.update_xaxes(showgrid=False, type="category")
    fig.update_yaxes(showgrid=False)
    return _layout(fig, f"강종 × 월 {PROP_SHORT.get(prop, prop)} 평균 편차 (σ)", height=290)


def contribution(ranking: list[dict], top=10):
    if not ranking:
        return empty("원인 후보 기여도", "비교할 인자가 없습니다.")
    rows = ranking[:top][::-1]
    fig = go.Figure(go.Bar(
        x=[r["effect_size"] for r in rows], y=[r["label"] for r in rows], orientation="h",
        marker=dict(color=[_sign_color(r["effect_size"]) for r in rows],
                    opacity=[1 if r["mechanism"]["status"] == "일치" else FAINT for r in rows]),
        text=[f"{r['effect_size']:+.2f}" + (" ✓" if r["mechanism"]["status"] == "일치" else "") for r in rows],
        textposition="outside", cliponaxis=False,
        customdata=[[r["mechanism"]["status"], r["corr_with_prop"], r["p_value"]] for r in rows],
        hovertemplate="%{y}<br>효과크기 %{x:+.2f}<br>메커니즘 %{customdata[0]}<br>"
                      "상관 %{customdata[1]}<br>p=%{customdata[2]}<extra></extra>"))
    fig.add_vline(x=0, line=dict(color="rgba(128,128,128,0.6)", width=1))
    fig.update_xaxes(range=_bar_range([r["effect_size"] for r in rows]))
    return _layout(fig, "원인 후보 기여도 (효과크기)",
                   height=max(300, 32 * len(rows) + 90),
                   xaxis_title="차이 크기 (표준편차 몇 배)")


def scatter(group: pd.DataFrame, ref: pd.DataFrame, factor: str, prop: str, spec, group_name="문제 코일",
            color=GROUP, ref_name="정상 코일"):
    if group.empty and ref.empty:
        return empty(f"{factor_label(factor)} vs {prop}")
    fig = go.Figure()
    fig.add_scatter(x=ref[factor], y=ref[prop], mode="markers", name=f"{ref_name} (n={len(ref)})",
                    marker=dict(color=BASE, size=6, opacity=0.55))
    fig.add_scatter(x=group[factor], y=group[prop], mode="markers", name=f"{group_name} (n={len(group)})",
                    marker=dict(color=color, size=7, opacity=0.85, line=dict(width=0.5, color="white")))
    _spec_lines(fig, spec, axis="y")
    return _layout(fig, f"{factor_label(factor)} vs {PROP_SHORT.get(prop, prop)}",
                   xaxis_title=f"{factor_label(factor)} ({factor_unit(factor)})",
                   yaxis_title=pl(prop))


def factor_trend(df: pd.DataFrame, factor: str, period=(None, None), standard=None):
    daily = df.groupby("prod_date")[factor].mean().dropna().reset_index()
    if daily.empty:
        return empty(f"{factor_label(factor)} 일별 추이", "이 라인에는 해당 인자가 없습니다.")
    fig = go.Figure(go.Scatter(x=daily["prod_date"], y=daily[factor], mode="lines+markers",
                               line=dict(color=GROUP, width=1.5), marker=dict(size=3), name="일평균"))
    if standard is not None:
        fig.add_hline(y=standard, line=dict(color="rgba(128,128,128,0.8)", dash="dot"),
                      annotation_text=f"표준 {standard:g}", annotation_position="top left")
    start, end = period
    if start or end:
        fig.add_vrect(x0=start or daily["prod_date"].min(), x1=end or daily["prod_date"].max(),
                      fillcolor=UP, opacity=0.12, line_width=0, annotation_text="선택 기간",
                      annotation_position="top left")
    return _layout(fig, f"{factor_label(factor)} 일별 추이", showlegend=False,
                   yaxis_title=f"{factor_label(factor)} ({factor_unit(factor)})")


def confounders(conf: dict, color=GROUP, group_name="문제 코일", ref_name="정상 코일"):
    labels = {"thk_band": "두께", "line": "라인", "coil_pos": "시편 위치"}
    ys, xs_g, xs_r = [], [], []
    for col, v in conf.items():
        flag = " ⚠" if v["warning"] else ""
        order = THK_ORDER if col == "thk_band" else sorted(v["share_pct"])
        for k in [k for k in order if k in v["share_pct"]]:
            share = v["share_pct"][k]
            ys.append(f"{labels[col]}{flag} · {k}")
            xs_g.append(share["group"])
            xs_r.append(share["reference"])
    fig = go.Figure()
    fig.add_bar(y=ys, x=xs_r, orientation="h", name=ref_name, marker_color=BASE)
    fig.add_bar(y=ys, x=xs_g, orientation="h", name=group_name, marker_color=color)
    fig.update_yaxes(autorange="reversed")
    return _layout(fig, "비교 조건 차이: 두 그룹의 구성비 (%)", barmode="group",
                   height=max(300, 24 * len(ys) + 90), xaxis_title="비율 (%)")


def defect_monthly(df: pd.DataFrame, highlight=None):
    total = df.groupby("month").size()
    if total.empty:
        return empty("월별 표면결함 발생률")
    d = df[df["defect_type"] != "없음"]
    fig = go.Figure()
    for dt, g in d.groupby("defect_type"):
        rate = (g.groupby("month").size() / total * 100).reindex(total.index, fill_value=0)
        on = highlight in (None, dt)
        fig.add_bar(x=rate.index, y=rate.values, name=dt, marker_color=SPEC if dt == highlight else BASE,
                    opacity=1 if on else 0.55, hovertemplate=f"{dt} %{{x}}: %{{y:.2f}}%<extra></extra>")
    fig.update_xaxes(type="category")
    return _layout(fig, "월별 표면결함 발생률 (%)", barmode="stack",
                   yaxis_title="발생률 (%)")


def defect_factor_bar(rows: list[dict]):
    if not rows:
        return empty("결함 원인 후보", "결함 코일이 너무 적어 비교할 수 없습니다.")
    rows = rows[::-1]
    fig = go.Figure(go.Bar(
        x=[r["effect_size"] for r in rows], y=[r["label"] for r in rows], orientation="h",
        marker=dict(color=[_sign_color(r["effect_size"]) for r in rows],
                    opacity=[1 if r["kb_consistent"] else FAINT for r in rows]),
        text=[f"{r['effect_size']:+.2f}" + (" ✓" if r["kb_consistent"] else "") for r in rows],
        textposition="outside", cliponaxis=False))
    fig.add_vline(x=0, line=dict(color="rgba(128,128,128,0.6)", width=1))
    fig.update_xaxes(range=_bar_range([r["effect_size"] for r in rows]))
    return _layout(fig, "결함 원인 후보 (효과크기)",
                   height=max(280, 32 * len(rows) + 90), xaxis_title="효과크기 (σ)")


def rvalue_box(target: pd.DataFrame, baseline: pd.DataFrame, target_name="이 기간", ref_name="나머지 기간",
               color=GROUP):
    """방향별 r값(r0·r45·r90) 비교 (prd_v2 R1)."""
    cols = [c for c in ("r0", "r45", "r90") if c in target.columns]
    if not cols or target.empty:
        return empty("방향별 r값", "r0·r45·r90 데이터가 없습니다.")
    fig = go.Figure()
    for df, name, col in ((baseline, ref_name, BASE), (target, target_name, color)):
        if df.empty:
            continue
        long = df[cols].melt(var_name="dir", value_name="r").dropna()
        fig.add_box(x=long["dir"].map({"r0": "0°", "r45": "45°", "r90": "90°"}), y=long["r"], name=f"{name} (n={len(df)})",
                    marker_color=col, boxmean=True)
    fig.update_xaxes(title="압연 방향 기준 시편 각도")
    return _layout(fig, "방향별 r값 (r0 · r45 · r90)", boxmode="group", yaxis_title="r값")


def coil_position(base: pd.Series, value: float, prop: str, spec, title=None):
    """양산 분포 위 대상 코일 위치 (세로선)."""
    base = base.dropna()
    if base.empty or value is None:
        return empty(title or PROP_SHORT.get(prop, prop), "양산 데이터 없음")
    fig = go.Figure(go.Histogram(x=base, nbinsx=25, marker_color=BASE, opacity=0.8, name="양산"))
    lo, hi = spec
    for v in (lo, hi):
        if v is not None:
            fig.add_vline(x=v, line=dict(color=SPEC, dash="dash", width=1))
    med = base.median()
    fig.add_vline(x=value, line=dict(color=UP if value > med else DOWN, width=3),
                  annotation_text="이 코일", annotation_position="top")
    fig.update_yaxes(visible=False)
    return _layout(fig, title or pl(prop), height=190, showlegend=False, bargap=0.05)


PROCESS_ORDER = ["제강", "연주", "열연", "산세", "냉연", "소둔", "도금", "조질"]


def process_diff(factors: list[dict], top=12):
    """공정 인자별 양산 대비 차이(z). 공정 순서로 묶고, 표준조건 관리범위 이탈은 빨간 테두리."""
    rows = [f for f in factors if f.get("z") is not None][:top]
    if not rows:
        return empty("양산 대비 공정 차이", "비교할 공정 인자가 없습니다.")
    rows.sort(key=lambda f: (PROCESS_ORDER.index(f["process"]) if f["process"] in PROCESS_ORDER else 99, f["label"]),
              reverse=True)
    fig = go.Figure(go.Bar(
        x=[f["z"] for f in rows], y=[f"{f['process']} · {f['label']}" for f in rows], orientation="h",
        marker=dict(color=[_sign_color(f["z"]) for f in rows],
                    opacity=[1 if abs(f["z"]) >= 1.5 else FAINT for f in rows],
                    line=dict(color=[SPEC if f["out_of_standard"] else "rgba(0,0,0,0)" for f in rows], width=2)),
        text=[f"{f['z']:+.1f}" for f in rows], textposition="outside", cliponaxis=False,
        customdata=[[f["value"], f["mass_median"], f["unit"]] for f in rows],
        hovertemplate="%{y}<br>이 코일 %{customdata[0]} %{customdata[2]}<br>양산 중앙값 %{customdata[1]}<br>"
                      "z %{x:+.2f}<extra></extra>"))
    fig.add_vline(x=0, line=dict(color="rgba(128,128,128,0.6)", width=1))
    for x in (-1.5, 1.5):
        fig.add_vline(x=x, line=dict(color="rgba(128,128,128,0.4)", dash="dot", width=1))
    fig.update_xaxes(range=_bar_range([f["z"] for f in rows]))
    return _layout(fig, "양산 대비 공정 차이 (표준편차 몇 배, 공정 순서)", height=max(300, 30 * len(rows) + 90),
                   xaxis_title="양산 대비 차이 (z) · 점선 ±1.5 · 빨간 테두리 = 표준조건 관리범위 이탈")
