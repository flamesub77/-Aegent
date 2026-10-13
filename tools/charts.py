"""대시보드 Plotly 차트.

색상 규칙 (prd_v3 U2, 파랑 계열): 기본·중립 그룹=파랑, 평소보다 낮게=진한 파랑, 평소보다 높게=주황(유일한 강조색),
비교 대상(정상·나머지 기간)=연회색, 스펙선·결함=빨강.
배경은 투명으로 두어 Streamlit 라이트/다크 테마를 그대로 따른다.
"""
import pandas as pd
import plotly.graph_objects as go

from tools import terms as T
from tools.domain import PROP_SHORT, PROP_UNIT, factor_label, factor_unit

UP = "#EA7A2C"
DOWN = "#1E3A8A"
GROUP = "#3B82F6"
BASE = "#B6C2D2"
SPEC = "#DC2626"
BLUES = ["#1E3A8A", "#1D4ED8", "#3B82F6", "#60A5FA", "#93C5FD", "#BFDBFE", "#DBEAFE"]  # 범주 색 (강종 등)
FAINT = 0.35
THK_ORDER = ["~0.75", "0.75~1.0", "1.0~1.4", "1.4~"]


def pl(prop: str) -> str:
    """재질 표시 이름 (단위 포함). 무차원 지표(r̄·n)는 단위 생략."""
    u = PROP_UNIT.get(prop, "")
    return PROP_SHORT.get(prop, prop) + ("" if u in ("", "-") else f" ({u})")


def direction_color(judgement_or_side: str | None) -> str:
    """판정(상향/하향 ...) 또는 불량 코일 방향(high/low)을 색으로."""
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
                      font=dict(family="HDharmony, 'Malgun Gothic', sans-serif", size=12),
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


def monthly_box(df: pd.DataFrame, prop: str, spec, period=(None, None), color=GROUP, defect_line: bool = False):
    """월별 상자그림. defect_line이면 월별 스펙 불량률(%) 선을 오른쪽 축에 겹친다 (prd_v6 M4)."""
    if df.empty:
        return empty(f"월별 {prop} 추이")
    fig = go.Figure()
    start, end = period
    for month, g in df.groupby("month"):
        selected = bool(start or end) and (not start or month >= start[:7]) and (not end or month <= end[:7])
        fig.add_box(y=g[prop], name=month, marker_color=color if selected else BASE,
                    boxmean=True, showlegend=False)
    _spec_lines(fig, spec, axis="y")
    lo, hi = spec
    extra = {}
    if defect_line and (lo is not None or hi is not None):
        v = df[prop]
        bad = ((v < lo) if lo is not None else False) | ((v > hi) if hi is not None else False)
        rate = df.assign(_bad=bad, _has=v.notna()).groupby("month").apply(
            lambda g: 100 * g["_bad"].sum() / max(g["_has"].sum(), 1), include_groups=False)
        fig.add_scatter(x=rate.index, y=rate.values, yaxis="y2", mode="lines+markers", name="불량률(%)",
                        line=dict(color=SPEC, width=1.6), marker=dict(size=4),
                        hovertemplate="%{x} 불량률 %{y:.1f}%<extra></extra>")
        extra = dict(yaxis2=dict(title="불량률 (%)", overlaying="y", side="right", showgrid=False, rangemode="tozero"))
    note = " · 색칠 = 선택 기간" if (start or end) else ""
    return _layout(fig, f"월별 {PROP_SHORT.get(prop, prop)} 추이{note}", yaxis_title=pl(prop), **extra)


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
        text=[[f"{v:.1f}" for v in row] for row in mean.values],
        texttemplate="%{z:+.1f}σ" if len(pv.columns) <= 12 else None,  # 달이 많으면 칸 글씨 생략 (마우스로 확인)
        hovertemplate="%{y} · %{x}<br>편차 %{z:+.2f}σ<br>평균 %{text}<extra></extra>"))
    fig.update_xaxes(showgrid=False, type="category")
    fig.update_yaxes(showgrid=False)
    return _layout(fig, f"강종 × 월 {PROP_SHORT.get(prop, prop)} 평균 편차 (σ)", height=290)


def contribution(ranking: list[dict], top=10, style=None, score_key="effect_size", score_label=None):
    """원인 가능성 순위 막대. score_key: 점수 키 (모델 점수 "score" 또는 v2 "effect_size")."""
    label = score_label or "차이 크기 (표준편차 몇 배)"
    title = f"{T.t('ranking')} ({label.split(' (')[0]})"
    if not ranking:
        return empty(title, "비교할 인자가 없습니다.")
    rows = ranking[:top][::-1]
    vals = [float(r.get(score_key) or 0) for r in rows]
    small = max(abs(v) for v in vals) < 0.1
    fig = go.Figure(go.Bar(
        x=vals, y=[r["label"] for r in rows], orientation="h",
        marker=dict(color=[_sign_color(r["diff"] if r.get("diff") is not None else v) for r, v in zip(rows, vals)],
                    opacity=[1 if r["mechanism"]["status"] == "일치" else FAINT for r in rows]),
        text=[(f"{v:+.3f}" if small else f"{v:+.2f}") + (" ✓" if r["mechanism"]["status"] == "일치" else "")
              for r, v in zip(rows, vals)],
        textposition="outside", cliponaxis=False,
        customdata=[[T.mechanism(r["mechanism"]["status"]), r["corr_with_prop"], r["effect_size"]] for r in rows],
        hovertemplate="%{y}<br>점수 %{x:+.3f}<br>%{customdata[0]}<br>상관 %{customdata[1]}<br>"
                      "차이 크기 %{customdata[2]}<extra></extra>"))
    fig.add_vline(x=0, line=dict(color="rgba(128,128,128,0.6)", width=1))
    fig.update_xaxes(range=_bar_range(vals))
    return _layout(fig, title, height=max(300, 32 * len(rows) + 90), xaxis_title=label)


def scatter(group: pd.DataFrame, ref: pd.DataFrame, factor: str, prop: str, spec, group_name="불량 코일",
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


def confounders(conf: dict, color=GROUP, group_name="불량 코일", ref_name="정상 코일"):
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


def defect_factor_bar(rows: list[dict], style=None):
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
    return _layout(fig, f"결함 {T.t('ranking')} ({T.t('effect_size')})",
                   height=max(280, 32 * len(rows) + 90), xaxis_title="차이 크기 (표준편차 몇 배)")


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


def coil_position(base: pd.Series, value: float, prop: str, spec, title=None, xlabel=None, standard=None):
    """양산 분포 위 대상 코일 위치 (세로선). 공정 인자면 xlabel(이름·단위)과 표준조건(standard, 초록 점선)."""
    base = base.dropna()
    if base.empty or value is None:
        return empty(title or PROP_SHORT.get(prop, prop), "양산 데이터 없음")
    fig = go.Figure(go.Histogram(x=base, nbinsx=25, marker_color=BASE, opacity=0.8, name="양산"))
    lo, hi = spec
    for v in (lo, hi):
        if v is not None:
            fig.add_vline(x=v, line=dict(color=SPEC, dash="dash", width=1))
    if standard is not None:
        fig.add_vline(x=standard, line=dict(color="#16A34A", dash="dash", width=1.2), annotation_text="표준",
                      annotation_position="top left", annotation_font_size=10)
    med = base.median()
    fig.add_vline(x=med, line=dict(color="#64748B", dash="dot", width=1.2), annotation_text="양산 중앙값",
                  annotation_position="bottom right", annotation_font_size=10)
    fig.add_vline(x=value, line=dict(color=UP if value > med else DOWN, width=3),
                  annotation_text="이 코일", annotation_position="top")
    fig.update_yaxes(title_text="코일 수", title_font_size=10)
    return _layout(fig, title or pl(prop), height=220, showlegend=False, bargap=0.05, xaxis_title=xlabel or pl(prop))


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


def production(yearly: pd.DataFrame, by_grade: pd.DataFrame | None = None):
    """연도별 생산량 (prd_v3 U8): 막대 = 코일 수, 선 = 중량(톤). by_grade를 주면 냉연규격별 누적 막대."""
    if yearly.empty:
        return empty("연도별 생산량")
    fig = go.Figure()
    x = yearly["year"].astype(str)
    if by_grade is not None and not by_grade.empty:
        for i, (g, d) in enumerate(by_grade.groupby("grade")):
            fig.add_bar(x=d["year"].astype(str), y=d["coils"], name=g, marker_color=BLUES[i % len(BLUES)],
                        hovertemplate=f"{g} %{{x}}: %{{y:,}}코일<extra></extra>")
    else:
        labels = [f"{int(c):,}" + (f"<br>({int(m)}개월)" if m < 12 else "") for c, m in zip(yearly["coils"], yearly["months"])]
        fig.add_bar(x=x, y=yearly["coils"], name="코일 수", marker_color=GROUP, text=labels, textposition="outside",
                    cliponaxis=False, hovertemplate="%{x}: %{y:,}코일<extra></extra>")
    fig.add_scatter(x=x, y=yearly["tons"], name="중량(톤)", yaxis="y2", mode="lines+markers",
                    line=dict(color=DOWN, width=2), hovertemplate="%{x}: %{y:,.0f}톤<extra></extra>")
    fig.update_xaxes(type="category")
    return _layout(fig, "연도별 생산량", barmode="stack", yaxis_title="코일 수",
                   yaxis2=dict(title="중량(톤)", overlaying="y", side="right", showgrid=False))


# ---------------------------------------------------------------------------
# prd_v4
# ---------------------------------------------------------------------------
def thickness_box(df: pd.DataFrame, prop: str, spec, bands: pd.Series, order: list[str], worst: str | None = None):
    """두께 구간별 재질 상자그림 (M1). 만족률이 가장 낮은 구간은 주황."""
    d = df.assign(_band=bands).dropna(subset=["_band", prop])
    if d.empty:
        return empty(f"두께 구간별 {PROP_SHORT.get(prop, prop)}")
    fig = go.Figure()
    for b in [x for x in order if x in set(d["_band"])]:
        g = d[d["_band"] == b]
        name = f"{b[1:]}mm 이하" if b.startswith("~") else f"{b[:-1]}mm 초과" if b.endswith("~") else f"{b}mm"
        fig.add_box(y=g[prop], name=f"{name}<br>(n={len(g)})", marker_color=UP if b == worst else GROUP,
                    boxmean=True, showlegend=False)
    _spec_lines(fig, spec, axis="y")
    return _layout(fig, f"두께 구간별 {PROP_SHORT.get(prop, prop)}", yaxis_title=pl(prop), xaxis_title="두께 구간")


def spc_chart(res: dict, spec):
    """EWMA·CUSUM 조기 감시 (M3): 위 = 값·EWMA·관리한계·SPEC, 아래 = CUSUM C⁺·C⁻·h. 경보 구간은 주황 배경."""
    from plotly.subplots import make_subplots
    pts, prop, h = res["points"], res["prop"], res["params"]["h"]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.64, 0.36], vertical_spacing=0.06)
    fig.add_scatter(x=pts["date"], y=pts[prop], mode="markers", name="일평균" if res["daily"] else "코일 값",
                    marker=dict(color=BASE, size=4), row=1, col=1)
    fig.add_scatter(x=pts["date"], y=pts["ewma"], mode="lines", name="EWMA", line=dict(color=DOWN, width=2), row=1, col=1)
    for c in ("ucl", "lcl"):
        fig.add_scatter(x=pts["date"], y=pts[c], mode="lines", name="관리한계" if c == "ucl" else None,
                        showlegend=c == "ucl", line=dict(color=GROUP, width=1, dash="dot"), row=1, col=1)
    lo, hi = spec
    for v in (lo, hi):
        if v is not None:
            fig.add_hline(y=v, line=dict(color=SPEC, dash="dash", width=1), row=1, col=1)
    fig.add_scatter(x=pts["date"], y=pts["cusum_hi"], mode="lines", name="CUSUM 높은 쪽", line=dict(color=UP, width=1.5),
                    row=2, col=1)
    fig.add_scatter(x=pts["date"], y=pts["cusum_lo"], mode="lines", name="CUSUM 낮은 쪽", line=dict(color=DOWN, width=1.5),
                    row=2, col=1)
    fig.add_hline(y=h, line=dict(color=SPEC, dash="dot", width=1), row=2, col=1, annotation_text=f"h = {h:g}",
                  annotation_position="top left")
    alarm = (pts["ewma_alarm"] | pts["cusum_alarm"]).to_numpy()
    dates = pts["date"].to_numpy()
    i = 0
    while i < len(alarm):  # 경보가 이어지는 구간마다 주황 배경
        if alarm[i]:
            j = i
            while j + 1 < len(alarm) and alarm[j + 1]:
                j += 1
            fig.add_vrect(x0=dates[i], x1=dates[j], fillcolor=UP, opacity=0.12, line_width=0)
            i = j + 1
        else:
            i += 1
    if res.get("first_alarm"):
        fig.add_vline(x=pd.Timestamp(res["first_alarm"]["date"]), line=dict(color=UP, width=2))
    fig.update_yaxes(title_text=pl(prop), row=1, col=1)
    fig.update_yaxes(title_text="CUSUM (σ)", row=2, col=1)
    return _layout(fig, f"{PROP_SHORT.get(prop, prop)} 조기 감시 (EWMA · CUSUM)", height=460)


def defect_grade_heatmap(gm: pd.DataFrame, defect: str):
    """강종 × 월 결함률 (M4)."""
    if gm.empty:
        return empty(f"강종별 {defect} 결함률")
    pv = gm.pivot(index="grade", columns="month", values="rate").fillna(0)
    fig = go.Figure(go.Heatmap(z=pv.values, x=pv.columns, y=pv.index, colorscale=[[0, "rgba(160,170,185,0.10)"], [1, SPEC]],
                               xgap=2, ygap=2, colorbar=dict(title="%", thickness=12),
                               hovertemplate="%{y} · %{x}<br>결함률 %{z:.2f}%<extra></extra>"))
    fig.update_xaxes(type="category", showgrid=False)
    fig.update_yaxes(showgrid=False)
    return _layout(fig, f"강종 × 월 {defect} 결함률 (%)", height=320)


def defect_grade_bar(rows: pd.DataFrame, defect: str, target_name="이 기간", ref_name="나머지 기간"):
    """강종별 결함률: 대상 기간 vs 나머지 기간 (M4)."""
    if rows.empty:
        return empty(f"강종별 {defect} 결함률")
    rows = rows.sort_values("rate_target_pct")
    fig = go.Figure()
    if rows["rate_baseline_pct"].notna().any():
        fig.add_bar(y=rows["grade"], x=rows["rate_baseline_pct"], orientation="h", name=ref_name, marker_color=BASE)
    fig.add_bar(y=rows["grade"], x=rows["rate_target_pct"], orientation="h", name=target_name, marker_color=SPEC,
                text=[f"{v:.1f}%" for v in rows["rate_target_pct"]], textposition="outside", cliponaxis=False)
    return _layout(fig, f"강종별 {defect} 결함률", barmode="group", xaxis_title="결함률 (%)",
                   height=max(280, 46 * len(rows) + 90))


def mini_hist_svg(values: pd.Series, spec=(None, None), ref: pd.Series | None = None, w=124, h=44, bins=18,
                  mark=None) -> str:
    """재질 요약 카드용 작은 히스토그램 SVG (M5). SPEC 밖 막대 빨강, SPEC 점선, 평균 진한 선. 축·글자 없음."""
    import numpy as np
    v = pd.Series(values).dropna().to_numpy(float)
    if len(v) < 3:
        return ""
    lo, hi = spec
    edges_lo = min(v.min(), lo if lo is not None else v.min(), mark if mark is not None else v.min())
    edges_hi = max(v.max(), hi if hi is not None else v.max(), mark if mark is not None else v.max())
    pad = (edges_hi - edges_lo) * 0.04 or 1
    edges = np.linspace(edges_lo - pad, edges_hi + pad, bins + 1)
    cnt, _ = np.histogram(v, edges)
    sx = lambda x: (x - edges[0]) / (edges[-1] - edges[0]) * w  # noqa: E731
    top = max(cnt.max(), 1)
    parts = []
    if ref is not None and len(pd.Series(ref).dropna()) > 3:
        rc, _ = np.histogram(pd.Series(ref).dropna().to_numpy(float), edges)
        rtop = max(rc.max(), 1)
        for i, c in enumerate(rc):
            bh = c / rtop * (h - 4)
            parts.append(f"<rect x='{sx(edges[i]):.1f}' y='{h - bh:.1f}' width='{max(sx(edges[i + 1]) - sx(edges[i]) - 1, 1):.1f}' "
                         f"height='{bh:.1f}' fill='#CBD5E1' opacity='0.6'/>")
    for i, c in enumerate(cnt):
        mid = (edges[i] + edges[i + 1]) / 2
        out = (lo is not None and mid < lo) or (hi is not None and mid > hi)
        bh = c / top * (h - 4)
        parts.append(f"<rect x='{sx(edges[i]):.1f}' y='{h - bh:.1f}' width='{max(sx(edges[i + 1]) - sx(edges[i]) - 1, 1):.1f}' "
                     f"height='{bh:.1f}' fill='{SPEC if out else '#60A5FA'}'/>")
    for s in (lo, hi):
        if s is not None:
            parts.append(f"<line x1='{sx(s):.1f}' x2='{sx(s):.1f}' y1='0' y2='{h}' stroke='{SPEC}' stroke-dasharray='3,2' "
                         f"stroke-width='1.2'/>")
    parts.append(f"<line x1='{sx(v.mean()):.1f}' x2='{sx(v.mean()):.1f}' y1='0' y2='{h}' stroke='{DOWN}' stroke-width='1.6'/>")
    if mark is not None:  # 지시(목표)값: 회색 점선 (prd_v7 B1)
        parts.append(f"<line x1='{sx(mark):.1f}' x2='{sx(mark):.1f}' y1='0' y2='{h}' stroke='#64748B' "
                     f"stroke-dasharray='2,2' stroke-width='1.2'/>")
    n_out = int((v < lo).sum() if lo is not None else 0) + int((v > hi).sum() if hi is not None else 0)
    tip = f"코일 {len(v):,}개 · 평균 {v.mean():.4g}" + (f" · SPEC 밖 {n_out}개" if lo is not None or hi is not None else "")
    return (f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}' role='img' aria-label='{tip}'>"
            f"<title>{tip}</title>{''.join(parts)}</svg>")


# ---------------------------------------------------------------------------
# prd_v5 T5: 결함분석
# ---------------------------------------------------------------------------
def defect_pareto(p: pd.DataFrame, grade: str, highlight: str | None = None):
    """강종 안 결함 유형 순위: 막대 = 발생률(%), 회색 막대 = 나머지 기간, 선 = 누적 %."""
    if p.empty:
        return empty(f"{grade} 결함 유형 순위", "결함 코일이 없어요.")
    fig = go.Figure()
    if p["base_rate"].notna().any():
        fig.add_bar(x=p["defect"], y=p["base_rate"], name="나머지 기간", marker_color=BASE,
                    hovertemplate="%{x} 나머지 기간: %{y:.2f}%<extra></extra>")
    fig.add_bar(x=p["defect"], y=p["rate"], name="이 기간" if p["base_rate"].notna().any() else "발생률",
                marker_color=[SPEC if d == highlight else GROUP for d in p["defect"]],
                text=[f"{v:.2f}%" for v in p["rate"]], textposition="outside", cliponaxis=False,
                hovertemplate="%{x}: %{y:.2f}% (%{customdata}코일)<extra></extra>", customdata=p["count"])
    fig.add_scatter(x=p["defect"], y=p["cum_pct"], name="누적 %", yaxis="y2", mode="lines+markers",
                    line=dict(color=DOWN, width=2), hovertemplate="누적 %{y:.0f}%<extra></extra>")
    fig.update_xaxes(type="category")
    return _layout(fig, f"{grade} 결함 유형 순위", barmode="group", yaxis_title="발생률 (%)",
                   yaxis2=dict(title="누적 (%)", overlaying="y", side="right", range=[0, 105], showgrid=False))


def defect_compare(rows: pd.DataFrame, defect: str, grade: str):
    """같은 결함의 강종별 발생률. 선택 강종 = 빨강, 나머지 = 연회색, 점선 = 전체 평균."""
    if rows.empty:
        return empty(f"강종별 {defect} 발생률")
    rows = rows.sort_values("rate")
    fig = go.Figure(go.Bar(
        y=rows["grade"], x=rows["rate"], orientation="h",
        marker_color=[SPEC if g == grade else BASE for g in rows["grade"]],
        text=[f"{v:.2f}% ({c}/{n})" for v, c, n in zip(rows["rate"], rows["count"], rows["n"])],
        textposition="outside", cliponaxis=False, hovertemplate="%{y}: %{x:.2f}%<extra></extra>"))
    avg = 100 * rows["count"].sum() / max(rows["n"].sum(), 1)
    fig.add_vline(x=avg, line=dict(color=DOWN, dash="dot", width=1.5), annotation_text=f"평균 {avg:.2f}%",
                  annotation_position="bottom right")
    fig.update_xaxes(range=[0, max(rows["rate"].max() * 1.35, avg * 1.3, 0.5)])
    return _layout(fig, f"강종별 {defect} 발생률", xaxis_title="발생률 (%)", showlegend=False)


def production_monthly(df: pd.DataFrame, period=(None, None)):
    """월별 생산량 (prd_v5 T2 ①): 코일 수 막대, 보는 기간은 진하게."""
    m = df.groupby("month").size()
    if m.empty:
        return empty("월별 생산량")
    lo, hi = (str(p)[:7] if p else None for p in period)
    on = [(lo is None or k >= lo) and (hi is None or k <= hi) for k in m.index]
    fig = go.Figure(go.Bar(x=m.index, y=m.values, marker_color=[GROUP if o else BASE for o in on],
                           hovertemplate="%{x}: %{y:,}코일<extra></extra>"))
    fig.update_xaxes(type="category", nticks=12)
    return _layout(fig, "월별 생산량", yaxis_title="코일 수", showlegend=False)


# ---------------------------------------------------------------------------
# prd_v6: 합격/불량 분포 · 두께별/용도별 생산량
# ---------------------------------------------------------------------------
PASS = "#3B82F6"


def defect_histogram(df: pd.DataFrame, prop: str, spec):
    """분포를 합격(파랑) / 불량(빨강, SPEC 밖)으로 나눠 쌓는다. SPEC이 없으면 분포 하나."""
    v = df[prop].dropna() if prop in df else pd.Series(dtype=float)
    if v.empty:
        return empty(f"{PROP_SHORT.get(prop, prop)} 분포")
    lo, hi = spec
    bad = ((v < lo) if lo is not None else False) | ((v > hi) if hi is not None else False)
    if not isinstance(bad, pd.Series):
        bad = pd.Series(False, index=v.index)
    lo_x, hi_x = v.min(), v.max()
    size = (hi_x - lo_x) / 30 or 1
    xbins = dict(start=lo_x, end=hi_x + size, size=size)
    fig = go.Figure()
    fig.add_histogram(x=v[~bad], name=f"합격 ({int((~bad).sum()):,})", marker_color=PASS, xbins=xbins,
                      hovertemplate="%{x}: %{y}코일<extra>합격</extra>")
    if bad.any():
        fig.add_histogram(x=v[bad], name=f"불량 ({int(bad.sum()):,})", marker_color=SPEC, xbins=xbins,
                          hovertemplate="%{x}: %{y}코일<extra>불량</extra>")
    _spec_lines(fig, spec)
    return _layout(fig, f"{PROP_SHORT.get(prop, prop)} 분포", barmode="stack", xaxis_title=pl(prop), yaxis_title="코일 수")


def production_bars(rows: pd.DataFrame, title: str, horizontal: bool = False):
    """두께별·용도별 생산량: 막대 = 코일 수 (글자 = 코일 수 · 비율)."""
    if rows.empty:
        return empty(title)
    text = [f"{int(c):,} ({s:.0f}%)" for c, s in zip(rows["coils"], rows["share"])]
    if horizontal:
        r = rows.iloc[::-1]
        fig = go.Figure(go.Bar(y=r["label"], x=r["coils"], orientation="h", marker_color=GROUP, text=text[::-1],
                               textposition="outside", cliponaxis=False,
                               hovertemplate="%{y}: %{x:,}코일<extra></extra>"))
        fig.update_xaxes(range=[0, rows["coils"].max() * 1.3])
        return _layout(fig, title, xaxis_title="코일 수", showlegend=False)
    fig = go.Figure(go.Bar(x=rows["label"], y=rows["coils"], marker_color=GROUP, text=text, textposition="outside",
                           cliponaxis=False, hovertemplate="%{x}: %{y:,}코일<extra></extra>"))
    fig.update_xaxes(type="category")
    fig.update_yaxes(range=[0, rows["coils"].max() * 1.2])
    return _layout(fig, title, yaxis_title="코일 수", showlegend=False)


def density_overview(df: pd.DataFrame, prop: str, spec):
    """강종개요 큰 분포 (prd_v8 G2): 합격(파랑)/불량(빨강) 막대 + 밀도 곡선, 평균선, SPEC 점선."""
    import numpy as np
    v = df[prop].dropna() if prop in df else pd.Series(dtype=float)
    if len(v) < 3:
        return empty(f"{PROP_SHORT.get(prop, prop)} 분포")
    fig = defect_histogram(df, prop, spec)
    lo_x, hi_x = float(v.min()), float(v.max())
    std = float(v.std()) or 1.0
    bw = 1.06 * std * len(v) ** (-1 / 5)  # 실버만 대역폭
    xs = np.linspace(lo_x - 2 * bw, hi_x + 2 * bw, 160)
    dens = np.exp(-0.5 * ((xs[:, None] - v.to_numpy()[None, :]) / bw) ** 2).sum(axis=1) / (len(v) * bw * np.sqrt(2 * np.pi))
    size = (hi_x - lo_x) / 30 or 1
    fig.add_scatter(x=xs, y=dens * len(v) * size, mode="lines", name="밀도", line=dict(color=DOWN, width=2),
                    hoverinfo="skip")
    fig.add_vline(x=float(v.mean()), line=dict(color=DOWN, width=2), annotation_text=f"평균 {v.mean():.4g}",
                  annotation_position="top")
    return fig


def process_timeseries(df: pd.DataFrame, factor: str, period=(None, None), aim=None, label: str | None = None):
    """공정 조건 시계열 (기본 정보 공정 카드를 누르면 오른쪽에 크게): 일평균 점 + 30일 이동평균 선,
    전체 평균 ± 1σ 띠, 지시값(엑셀) 점선, 선택 기간 음영."""
    name = label or factor_label(factor)
    unit = factor_unit(factor)
    if factor not in df or df[factor].notna().sum() < 3:
        return empty(f"{name} 시계열", "이 조건에는 값이 없어요.")
    daily = df.groupby("prod_date")[factor].mean().dropna()
    daily.index = pd.to_datetime(daily.index)
    roll = daily.rolling("30D", min_periods=3).mean()
    mean, sd = float(df[factor].mean()), float(df[factor].std() or 0)
    fig = go.Figure()
    fig.add_hrect(y0=mean - sd, y1=mean + sd, fillcolor=GROUP, opacity=0.08, line_width=0)
    fig.add_scatter(x=daily.index, y=daily.values, mode="markers", name="일평균", marker=dict(color=BASE, size=4),
                    hovertemplate="%{x|%Y-%m-%d} %{y:.4g}" + unit + "<extra>일평균</extra>")
    fig.add_scatter(x=roll.index, y=roll.values, mode="lines", name="30일 이동평균", line=dict(color=DOWN, width=2),
                    hovertemplate="%{x|%Y-%m-%d} %{y:.4g}" + unit + "<extra>30일 이동평균</extra>")
    fig.add_hline(y=mean, line=dict(color=GROUP, width=1), annotation_text=f"평균 {mean:.4g}",
                  annotation_position="bottom right")
    if aim is not None:
        fig.add_hline(y=aim, line=dict(color="#64748B", dash="dash", width=1.5), annotation_text=f"지시 {aim:.4g}",
                      annotation_position="top right")
    start, end = period
    if start or end:
        fig.add_vrect(x0=start or daily.index.min(), x1=end or daily.index.max(), fillcolor=UP, opacity=0.12,
                      line_width=0, annotation_text="선택 기간", annotation_position="top left")
    return _layout(fig, f"{name} 시계열", yaxis_title=f"{name} ({unit})" if unit else name)


def thickness_bars(tg: pd.DataFrame, prop: str, spec):
    """두께 그룹별 막대 (재질 큰 그래프 전환): 막대 = 평균, 오차 막대 = ±1σ, 막대 위 = 코일 수 · 불량률,
    SPEC 점선. 불량률이 가장 높은 구간은 주황."""
    if tg.empty:
        return empty(f"두께 그룹별 {PROP_SHORT.get(prop, prop)}", "두께 값이 있는 코일이 없어요.")
    names = [f"{b[1:]}mm 이하" if b.startswith("~") else f"{b[:-1]}mm 초과" if b.endswith("~") else f"{b}mm"
             for b in tg["band"]]
    fail = [None if r != r or r is None else round(100 - r, 1) for r in tg["spec_rate"]]
    worst = max(range(len(fail)), key=lambda i: -1 if fail[i] is None else fail[i]) if any(f is not None for f in fail) else None
    colors = [UP if i == worst and fail[i] else GROUP for i in range(len(tg))]
    # 코일 수·불량률은 x축 글자에 (막대가 좁아도 잘리지 않게)
    # 세 줄로 가로 표시 (기울어져 아래가 잘리지 않게): 구간 / 코일 수 / 불량률
    names = [f"<b>{nm}</b><br>{int(n):,}코일<br>불량 {'-' if f is None else f'{f:g}%'}" for nm, n, f in zip(names, tg["n"], fail)]
    fig = go.Figure(go.Bar(x=names, y=tg["mean"], marker_color=colors,
                           error_y=dict(type="data", array=tg["std"].fillna(0), color=DOWN, thickness=1.2),
                           hovertemplate="%{x}<br>평균 %{y:.4g}<extra></extra>"))
    lo, hi = spec
    for v, label, pos in ((lo, "스펙 하한", "bottom right"), (hi, "스펙 상한", "top right")):  # 글자는 선 바깥쪽에
        if v is not None:
            fig.add_hline(y=v, line=dict(color=SPEC, dash="dash", width=1), annotation_text=f"{label} {v:g}",
                          annotation_position=pos, annotation_font=dict(size=11, color=SPEC))
    vals = list(tg["mean"] + tg["std"].fillna(0)) + list(tg["mean"] - tg["std"].fillna(0)) + [v for v in (lo, hi) if v is not None]
    pad = (max(vals) - min(vals)) * 0.25 or 1
    fig.update_yaxes(range=[min(vals) - pad * 0.6, max(vals) + pad])  # 아래 여백: 스펙 하한 글자 자리
    fig.update_xaxes(type="category", tickangle=0, tickfont=dict(size=11), automargin=True)
    return _layout(fig, f"두께 그룹별 {PROP_SHORT.get(prop, prop)}", yaxis_title=pl(prop), showlegend=False)
