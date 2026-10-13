"""분석 결과를 쉬운 말 문장으로 바꾼다. 수치는 결과 dict에서만 가져온다.

prd_v3 U4: 문체는 쉬운 말 하나 (v2의 전문가·통계 문체 삭제). style 인자는 예전 호출과의 호환용이며 쓰지 않는다.
prd_v3 U8 → prd_v5 C1: 그래프 카드마다 "결론 제목 + 해석 한 줄(숫자 먼저)"을 만드는 note_* 함수.
오프라인에서도 동작하도록 LLM 없이 문장 틀 + 지식베이스 메커니즘 문구로 만든다.
"""
import pandas as pd

from tools import terms as T
from tools.domain import ACTIONS, PROP_DECIMALS, PROP_LABEL, PROP_SHORT, PROP_UNIT, factor_label, factor_unit


def josa(word: str, pair: str = "은/는") -> str:
    """단어 끝 받침에 맞는 조사를 붙인다. pair: "은/는", "이/가", "을/를", "과/와"."""
    with_final, without = pair.split("/")
    w = word.rstrip(" )*")
    ch = w[-1] if w else ""
    if "가" <= ch <= "힣":
        final = (ord(ch) - 0xAC00) % 28 != 0
    else:  # 영문·숫자: 읽을 때 받침 있는 글자
        final = ch.lower() in "lmnr0136789"
    return word + (with_final if final else without)


def _num(v, nd=1, sign=False):
    if v is None:
        return "-"
    return f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"


def _fv(v, unit):
    """공정인자 값: wt%는 4자리, 나머지 1자리."""
    if v is None:
        return "-"
    return f"{v:.4f}" if unit == "wt%" else f"{v:.1f}"


def _fd(v, unit):
    if v is None:
        return "-"
    return f"{v:+.4f}" if unit == "wt%" else f"{v:+.1f}"


def _u(unit):
    return "" if unit == "-" else unit


def _mech_sentence(r: dict) -> str:
    """원인 후보의 야금 원리 한 문장 (지식베이스 문장은 인자가 올라가는 경우 기준)."""
    mech = r["mechanism"]
    if mech["status"] == "일치" and mech.get("easy"):
        if (r.get("diff") or 0) >= 0:
            return f"{mech['easy']}."
        return f"야금 원리로 설명되는 방향이에요. 참고로 {josa(r['label'], '이/가')} 올라가면 이렇게 돼요: {mech['easy']}."
    if mech["status"] == "불일치":
        return "다만 야금 원리와는 반대 방향이라 다른 원인과 겹쳤을 수 있어요."
    return "같이 움직이긴 하지만 야금 원리로는 설명이 안 돼서 우연일 수도 있어요."


def insights(diag: dict, comp: dict, style: str | None = None) -> dict:
    """{summary: [문장], actions: [조치], warnings: [문장]}. 오프라인 답변·리포트용."""
    prop = comp["property"]
    p = diag["properties"].get(prop, {})
    nd, u = PROP_DECIMALS.get(prop, 1), _u(PROP_UNIT[prop])
    t, b = p.get("target", {}), p.get("baseline", {})
    judge = p.get("judgement", "비교 불가")
    grp, ref = T.group_names(comp["mode"], comp.get("side"))
    label = PROP_LABEL[prop]
    lines, actions = [], []
    if diag["n_baseline"] and p.get("shift") is not None:
        if judge in ("상향 분포", "하향 분포", "상향 경향", "하향 경향"):
            way = "높게" if p["shift"] > 0 else "낮게"
            lines.append(f"{label} 평균이 평소보다 {_num(abs(p['shift']), nd)}{u} {way} 나왔어요 "
                         f"(평균 {_num(t.get('mean'), nd)}{u}, 나머지 기간 {_num(b.get('mean'), nd)}{u}). "
                         f"**{T.judgement(judge)}**")
        else:
            lines.append(f"{label} 평균은 평소와 비슷해요 (평균 {_num(t.get('mean'), nd)}{u}, 나머지 기간 "
                         f"{_num(b.get('mean'), nd)}{u}).")
    else:
        lines.append(f"전체 기간 {label} 평균은 {_num(t.get('mean'), nd)}{u}예요.")
    if t.get("spec_rate") is not None:
        bad = (t.get("below_spec") or 0) + (t.get("above_spec") or 0)
        lines.append(f"{t.get('n')}개 중 {bad}개가 스펙을 벗어났어요 (만족률 {t.get('spec_rate')}%)."
                     if bad else f"{t.get('n')}개 모두 스펙 안에 있어요.")
    top = [r for r in comp["ranking"] if abs(r["effect_size"]) >= 0.5][:3]
    if not top:
        lines.append(f"{grp}, {ref} 사이에 눈에 띄게 다른 공정 조건은 없어요.")
    for i, r in enumerate(top):
        ru = r["unit"]
        lead = "가장 눈에 띄는 차이는" if i == 0 else "그다음은"
        lines.append(f"{lead} **{r['label']}** 쪽이에요. {josa(grp)} {_fv(r['group_mean'], ru)}{ru}, {josa(ref)} "
                     f"{_fv(r['reference_mean'], ru)}{ru}로 {_fd(r['diff'], ru)}{ru} 차이가 나요. {_mech_sentence(r)}")
        if r["mechanism"]["status"] == "일치" and r["factor"] in ACTIONS:
            gap = (f" (지금 평균이 표준보다 {_fd(r['group_vs_standard'], ru)}{ru})"
                   if r["group_vs_standard"] is not None else "")
            actions.append(f"{r['label']}: {ACTIONS[r['factor']]}{gap}")
    if not actions and top:
        actions.append("눈에 띄는 차이가 야금 원리로는 설명되지 않아요. 설비 기록과 시험 조건을 먼저 확인해 보세요.")
    warnings = [T.warning_text(w) for w in diag.get("warnings", []) + comp.get("warnings", [])]
    return {"summary": lines, "actions": actions, "warnings": list(dict.fromkeys(warnings))}


def coil_story(res: dict, style: str | None = None) -> list[str]:
    """analyze_coil 결과(코일 1개)를 문장으로. tools/coil_lookup.py 참고."""
    lines = []
    worst = sorted([m for m in res.get("materials", []) if m.get("z") is not None], key=lambda m: -abs(m["z"]))
    factors = [f for f in res.get("factors", []) if f.get("z") is not None and abs(f["z"]) >= 1.5][:3]
    coil = res["coil_no"]
    for m in worst[:2]:
        if abs(m["z"]) < 1:
            continue
        nd, u = PROP_DECIMALS.get(m["prop"], 1), _u(PROP_UNIT[m["prop"]])
        diff = m["value"] - m["mass_median"]
        lines.append(f"{coil} 코일은 양산보다 {PROP_LABEL[m['prop']]} 값이 {_num(abs(diff), nd)}{u} "
                     f"{'높아요' if diff > 0 else '낮아요'} (양산 중 {m['percentile']:.0f}% 위치).")
    if not lines:
        lines.append(f"{coil} 코일의 재질은 양산 코일들과 비슷한 수준이에요.")
    for f in factors:
        ru = f["unit"]
        mech = f.get("mechanism") or {}
        txt = f"공정에서는 **{f['label']}** 값이 양산보다 {_fd(f['value'] - f['mass_median'], ru)}{ru} 달라요."
        if mech.get("status") == "일치" and mech.get("easy"):
            txt += f" {mech['easy']}."
        lines.append(txt)
    if not factors:
        lines.append("공정 조건은 양산과 크게 다르지 않아요. 시험 조건이나 측정 편차를 확인해 보세요.")
    return lines


# ---------------------------------------------------------------------------
# 그래프 카드 문구 (prd_v3 U8 → prd_v5 C1): (결론 제목, [해석 한 줄]). 숫자·화살표 먼저, 짧게.
# 읽는 법(색·선 뜻)은 카드 제목 옆 (?) 도움말(terms.CARD_HELP)로 옮겼다.
# ---------------------------------------------------------------------------
MECH_MARK = {"일치": "원리 ✓", "불일치": "원리 ✗"}


def mech_mark(r: dict) -> str:
    return MECH_MARK.get((r.get("mechanism") or {}).get("status"), "원리 ?")


def note_production(prod: pd.DataFrame, grade: str) -> tuple[str, list[str]]:
    """prod: year, coils, tons."""
    if prod.empty:
        return f"{grade} 생산 실적이 없어요", []
    last = prod.iloc[-1]
    title = f"{grade} {int(last['year'])}년 {int(last['coils']):,}코일 · {last['tons']:,.0f}톤"
    if len(prod) < 2:
        return title, []
    prev = prod.iloc[-2]
    months = int(last.get("months", 12))
    pace = last["coils"] * 12 / max(months, 1)
    chg = 100 * (pace - prev["coils"]) / prev["coils"] if prev["coils"] else None
    line = (f"{int(prev['year'])}년 {int(prev['coils']):,} → "
            + (f"연환산 {pace:,.0f}코일 ({months}개월 실적)" if months < 12 else f"{int(last['coils']):,}코일")
            + (f" · {chg:+.0f}%" if chg is not None else ""))
    return title, [line]


def note_production_monthly(df: pd.DataFrame) -> tuple[str, list[str]]:
    """월별 생산량 (prd_v5 T2 ①)."""
    m = df.groupby("month").size()
    if m.empty:
        return "월별 생산량", []
    return (f"월 최다 {m.idxmax()} {int(m.max()):,}코일",
            [f"월평균 {m.mean():,.0f}코일 · 최근 {m.index[-1]} {int(m.iloc[-1]):,}코일"])


def note_distribution(diag: dict, prop: str, group_name: str, ref_name: str) -> tuple[str, list[str]]:
    p = diag["properties"].get(prop, {})
    nd, u = PROP_DECIMALS.get(prop, 1), _u(PROP_UNIT[prop])
    t = p.get("target", {})
    short = PROP_SHORT[prop]
    if diag["n_baseline"] and p.get("shift") is not None and p["judgement"] != "정상":
        title = f"{short} 평소보다 {_num(abs(p['shift']), nd)}{u} {'높음 🔺' if p['shift'] > 0 else '낮음 🔻'}"
    elif diag["n_baseline"] and p.get("shift") is not None:
        title = f"{short} 평소와 비슷 ✅ ({_num(p['shift'], nd, sign=True)}{u})"
    else:
        title = f"{short} 평균 {_num(t.get('mean'), nd)}{u} · 표준편차 {_num(t.get('std'), nd + 1)}"
    if t.get("spec_rate") is not None:
        bad = (t.get("below_spec") or 0) + (t.get("above_spec") or 0)
        line = f"만족률 {t['spec_rate']}% · SPEC 밖 {bad}/{t.get('n')}코일"
    else:
        line = f"SPEC 없음 · 코일 {t.get('n') or 0}개"
    return title, [line]


def note_monthly(df: pd.DataFrame, prop: str) -> tuple[str, list[str]]:
    m = df.groupby("month")[prop].mean().dropna()
    short, nd, u = PROP_SHORT[prop], PROP_DECIMALS.get(prop, 1), _u(PROP_UNIT[prop])
    if m.empty:
        return f"월별 {short} 데이터가 없어요", []
    return (f"월별 {short}: 최고 {m.idxmax()} · 최저 {m.idxmin()}",
            [f"월평균 {_num(m.min(), nd)}~{_num(m.max(), nd)}{u} (폭 {_num(m.max() - m.min(), nd)}{u})"])


def note_heatmap(hm: pd.DataFrame, prop: str) -> tuple[str, list[str]]:
    short = PROP_SHORT[prop]
    if hm.empty or hm["z"].isna().all():
        return f"강종 × 월 {short} 편차", []
    r = hm.loc[hm["z"].abs().idxmax()]
    return (f"{r['month']} {r['grade']} {short} 편차 최대 {'🔺' if r['z'] > 0 else '🔻'}",
            [f"강종 평균 대비 {r['z']:+.1f}σ"])


def note_rvalue(group: pd.DataFrame, ref: pd.DataFrame, group_name: str, ref_name: str) -> tuple[str, list[str]]:
    cols = [c for c in ("r0", "r45", "r90") if c in group.columns]
    if not cols or group.empty:
        return "방향별 r값", []
    g, r = group[cols].mean(), ref[cols].mean() if len(ref) else None
    worst = (g - r).abs().idxmax() if r is not None else None
    title = (f"r{worst[1:]}° {group_name} {abs(g[worst] - r[worst]):.2f} {'높음 🔺' if g[worst] > r[worst] else '낮음 🔻'}"
             if worst else "방향별 r값")
    return title, [" · ".join(f"r{c[1:]} {g[c]:.2f}" for c in cols)]


def note_contribution(comp: dict, model_name: str) -> tuple[str, list[str]]:
    rows = comp["ranking"]
    if not rows:
        return "비교할 공정 인자가 없어요", []
    top = rows[0]
    title = f"원인 1순위: {top['label']} {_fd(top['diff'], top['unit'])}{top['unit']}"
    others = ", ".join(r["label"] for r in rows[1:3])
    return title, [f"{mech_mark(top)} · {model_name}" + (f" · 다음 {others}" if others else "")]


def note_scatter(comp: dict, factor: str, prop: str) -> tuple[str, list[str]]:
    row = next((r for r in comp["all_factors"] if r["factor"] == factor), None)
    label, short = factor_label(factor), PROP_SHORT[prop]
    if row is None or row.get("corr_with_prop") is None:
        return f"{label} ↔ {short}", ["값이 같이 있는 코일이 적어 관계를 계산하지 못했어요"]
    r = row["corr_with_prop"]
    strength = "뚜렷" if abs(r) >= 0.5 else "약함" if abs(r) >= 0.2 else "없음"
    title = (f"{label}↑ → {short}{'↑' if r > 0 else '↓'} ({strength})" if abs(r) >= 0.2
             else f"{label} ↔ {short} 관계 없음")
    return title, [f"상관 {r:+.2f} · {mech_mark(row)}"]


def note_trend(df: pd.DataFrame, factor: str, standard) -> tuple[str, list[str]]:
    label, unit = factor_label(factor), factor_unit(factor)
    m = df.groupby("month")[factor].mean().dropna() if factor in df else pd.Series(dtype=float)
    if m.empty:
        return f"{label} 추이", ["이 조건에는 해당 인자 값이 없어요"]
    line = f"최고 {m.idxmax()} {_fv(m.max(), unit)}{unit}"
    if standard is not None:
        off = (m - standard).abs().idxmax()
        line += f" · 표준 {standard:g}{unit}에서 가장 먼 달 {off} ({_fd(m[off] - standard, unit)})"
    return f"{label} 추이", [line]


def note_confounders(comp: dict) -> tuple[str, list[str]]:
    warn = [w for w in comp["warnings"] if w.get("code") == "confounder"]
    if not warn:
        return "두께·라인·시편 위치 구성 비슷 ✅", ["차이를 공정 차이로 봐도 돼요"]
    w = max(warn, key=lambda x: x["gap_pp"])
    col = T.CONFOUNDER_COL.get(w["column"], w["column"])
    return (f"⚠️ 두 그룹 {col} 구성 {w['gap_pp']}%p 차이", [f"{col} 영향일 수 있어요 → 아래 버튼으로 나눠 보기"])


def note_defect(dres: dict) -> tuple[str, list[str]]:
    dt, now, base = dres["defect_type"], dres["rate_target_pct"], dres["rate_baseline_pct"]
    title = f"{dt} {base}% → {now}% 🔺" if base is not None and now > base else f"{dt} 발생률 {now}%"
    top = [f for f in dres["factor_ranking"] if f["kb_consistent"]][:1] or dres["factor_ranking"][:1]
    if top:
        f = top[0]
        line = (f"{f['label']}: 결함 {_fv(f['defect_mean'], f['unit'])} vs 정상 {_fv(f['normal_mean'], f['unit'])}{f['unit']}"
                f" · 보통 원인 공정 {dres['kb_cause']['process']}")
    else:
        line = f"보통 원인: {dres['kb_cause']['cause']} ({dres['kb_cause']['process']})"
    return title, [line]


def note_thickness(tg: pd.DataFrame, prop: str) -> tuple[str, list[str]]:
    """두께 구간별 재질 (prd_v4 M1). tg: analysis.thickness_groups 결과."""
    short, nd, u = PROP_SHORT[prop], PROP_DECIMALS.get(prop, 1), _u(PROP_UNIT[prop])
    if tg.empty:
        return f"두께 구간별 {short}", ["두께 값이 있는 코일이 없어요"]
    if tg["spec_rate"].notna().any():
        w = tg.loc[tg["spec_rate"].idxmin()]
        title = f"{band_text(w['band'])} {short} 불량률 {round(100 - w['spec_rate'], 1):g}% (최고)"
        if w["spec_rate"] < 95:
            title = "⚠️ " + title
    else:
        w = tg.loc[tg["std"].idxmax()]
        title = f"{band_text(w['band'])} {short} 흩어짐 최대"
    span = tg["mean"].max() - tg["mean"].min()
    return title, [f"구간 평균 차 최대 {_num(span, nd)}{u} · 코일 {int(tg['n'].sum()):,}개"]


def band_text(band: str) -> str:
    """"~0.75" → "0.75mm 이하", "1.4~" → "1.4mm 초과", "0.75~1.0" → "0.75~1.0mm"."""
    if band.startswith("~"):
        return f"{band[1:]}mm 이하"
    if band.endswith("~"):
        return f"{band[:-1]}mm 초과"
    return f"{band}mm"


def _spc_date(res: dict) -> str:
    """경보 날짜 "5/3" (마지막 해가 아니면 "2019/9/22")."""
    d = res["first_alarm"]["date"]
    last = str(res["points"]["date"].max())[:4] if len(res.get("points", [])) else d[:4]
    md = f"{int(d[5:7])}/{int(d[8:10])}"
    return md if d[:4] == last else f"{d[:4]}/{md}"


def _spc_word(direction: str) -> str:
    return "상승" if str(direction).startswith(("높", "위", "상")) else "하락"


def note_spc(res: dict) -> tuple[str, list[str]]:
    """EWMA·CUSUM 조기 감시 (prd_v4 M3)."""
    short = PROP_SHORT[res["prop"]]
    b = res["baseline"]
    nd = PROP_DECIMALS.get(res["prop"], 1)
    base_txt = f"기준 평균 {b['mean']:.{nd}f} · σ {b['std']:.{nd + 1}f} ({str(b['start'])[:7]}~{str(b['end'])[:7]})"
    a = res.get("first_alarm")
    if not a:
        return f"{short}는 기준과 비교해 이상 신호가 없어요 ✅", [base_txt]
    title = f"🚨 {_spc_date(res)}부터 {short} {_spc_word(a['direction'])} 경보"
    lead = res.get("lead_days")
    if lead is not None and lead > 0:
        title += f" (스펙 이탈보다 {lead}일 먼저)"
    return title, [f"{a['by']} 감지 · {base_txt}"]


def spc_badge(res: dict | None) -> str | None:
    """공정분석 탭 위 한 줄 배지 (prd_v5 T4)."""
    a = (res or {}).get("first_alarm")
    if not a:
        return None
    return (f"🚨 {_spc_date(res)}부터 {PROP_SHORT[res['prop']]} "
            f"{_spc_word(a['direction'])} 경보 ({a['by']})")


def note_defect_grades(rows: pd.DataFrame, defect: str) -> tuple[str, list[str]]:
    """강종별 결함 (prd_v4 M4, AI 보고서)."""
    if rows.empty:
        return f"강종별 {defect}", ["비교할 강종이 없어요"]
    rows = rows.assign(_inc=rows["rate_target_pct"] - rows["rate_baseline_pct"].fillna(0))
    w = rows.loc[rows["_inc"].idxmax()]
    base = "" if w["rate_baseline_pct"] is None or w["rate_baseline_pct"] != w["rate_baseline_pct"] else f"{w['rate_baseline_pct']}% → "
    title = f"{defect} 최대 증가 {w['grade']} ({base}{w['rate_target_pct']}%)"
    common = rows[rows["top_factor"] != "표본 부족"]["top_factor"].value_counts()
    return title, ["1순위 원인: " + (", ".join(f"{k} {v}개 강종" for k, v in common.items()) if len(common) else "표본 부족")]


def note_pareto(p: pd.DataFrame, grade: str) -> tuple[str, list[str]]:
    """강종 안 결함 유형 순위 (prd_v5 T5 🥇)."""
    if p.empty:
        return f"{grade} 결함 없음 ✅", []
    top = p.iloc[0]
    title = f"{grade} 결함 1위 {top['defect']} {top['rate']:.2f}%"
    line = f"상위 {min(2, len(p))}종이 결함의 {p['cum_pct'].iloc[min(1, len(p) - 1)]:.0f}%"
    if p["base_rate"].notna().any():
        r = p.loc[(p["rate"] - p["base_rate"]).idxmax()]
        if r["rate"] > r["base_rate"]:
            line += f" · 가장 늘어난 결함 {r['defect']} {r['base_rate']:.2f}→{r['rate']:.2f}%"
    return title, [line]


def note_defect_compare(rows: pd.DataFrame, defect: str, grade: str) -> tuple[str, list[str]]:
    """같은 결함 강종 비교 (prd_v5 T5 🆚). rows는 발생률 내림차순."""
    if rows.empty:
        return f"강종별 {defect}", []
    avg = 100 * rows["count"].sum() / max(rows["n"].sum(), 1)
    top = rows.iloc[0]
    me = rows[rows["grade"] == grade]
    if me.empty:
        return f"{defect} 최다 {top['grade']} {top['rate']:.2f}%", [f"강종 평균 {avg:.2f}%"]
    r = me.iloc[0]
    rank = int(me.index[0]) + 1
    ratio = r["rate"] / avg if avg else 0
    title = f"{grade} {defect} {r['rate']:.2f}% · {len(rows)}개 강종 중 {rank}위" + (" 🔺" if ratio >= 1.5 else "")
    return title, [f"평균 {avg:.2f}%의 {ratio:.1f}배 · 최다 {top['grade']} {top['rate']:.2f}%"]



# ---------------------------------------------------------------------------
# prd_v6: 스펙 불량률 · 두께별/용도별 생산량
# ---------------------------------------------------------------------------
def note_defect_dist(target: pd.DataFrame, baseline: pd.DataFrame | None, prop: str, spec) -> tuple[str, list[str]]:
    """재질 분포 카드 (불량률 기준): "TS 불량률 0.4% (3/617코일)" + 평균·나머지 기간 대비 변화."""
    from tools.analysis import defect_rate
    short, nd, u = PROP_SHORT[prop], PROP_DECIMALS.get(prop, 1), _u(PROP_UNIT[prop])
    lo, hi = spec
    rate, bad, n = defect_rate(target[prop], lo, hi) if prop in target else (None, 0, 0)
    mean = target[prop].mean() if prop in target else None
    if rate is None:
        return f"{short} 평균 {_num(mean, nd)}{u} (SPEC 없음)", [f"코일 {n:,}개 · 표준편차 {_num(target[prop].std(), nd + 1)}"]
    title = f"{short} 불량률 {rate:g}% ({bad:,}/{n:,}코일)" + (" ⚠️" if rate >= 5 else "")
    line = f"평균 {_num(mean, nd)}{u}"
    if baseline is not None and len(baseline):
        b_rate, _, b_n = defect_rate(baseline[prop], lo, hi)
        if b_rate is not None and b_n:
            arrow = "🔺" if rate > b_rate else "🔻" if rate < b_rate else "→"
            line += f" · 나머지 기간 {b_rate:g}% → 이 기간 {rate:g}% {arrow}"
    return title, [line]


def note_production_by(rows: pd.DataFrame, what: str) -> tuple[str, list[str]]:
    """두께별·용도별 생산량 카드."""
    if rows.empty:
        return f"{what}별 생산량", []
    top = rows.loc[rows["coils"].idxmax()]
    label = band_text(top["label"]) if what == "두께" else top["label"]
    return (f"{what}별 생산량: {label} 최다 {top['share']:.0f}%",
            [" · ".join(f"{band_text(r['label']) if what == '두께' else r['key']} {int(r['coils']):,}" for _, r in rows.head(5).iterrows())])



def note_process_ts(df: pd.DataFrame, factor: str, aim=None, label: str | None = None) -> tuple[str, list[str]]:
    """공정 조건 시계열 카드: 제목 = 평균(지시 대비), 한 줄 = 최근 30일 vs 전체."""
    name, unit = label or factor_label(factor), factor_unit(factor)
    if factor not in df or df[factor].notna().sum() < 3:
        return f"{name} 시계열 (값 없음)", ["이 조건에는 값이 없어요"]
    v = df[factor].dropna()
    title = f"{name} 평균 {_fv(v.mean(), unit)}{unit}" + (f" (지시 {_fd(v.mean() - aim, unit)})" if aim is not None else "")
    dates = pd.to_datetime(df.loc[v.index, "prod_date"])
    recent = v[dates >= dates.max() - pd.Timedelta(days=30)]
    line = f"최근 30일 평균 {_fv(recent.mean(), unit)}{unit} (전체 대비 {_fd(recent.mean() - v.mean(), unit)}) · σ {v.std():.3g}"
    return title, [line]
