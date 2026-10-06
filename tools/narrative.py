"""분석 결과를 문체별 문장으로 바꾼다 (prd_v2 R5). 수치는 결과 dict에서만 가져온다.

easy: 쉬운 말(구어체), expert: 금속재료공학 용어, stat: 통계 표현(v1).
오프라인에서도 동작하도록 LLM 없이 문장 틀 + 지식베이스 메커니즘 문구로 만든다.
"""
from tools import terms as T
from tools.domain import ACTIONS, PROP_DECIMALS, PROP_LABEL, PROP_SHORT, PROP_UNIT


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


def insights(diag: dict, comp: dict, style: str = T.DEFAULT_STYLE) -> dict:
    """{summary: [문장], actions: [조치], warnings: [문장]}."""
    prop = comp["property"]
    p = diag["properties"].get(prop, {})
    unit, nd = PROP_UNIT[prop], PROP_DECIMALS.get(prop, 1)
    u = _u(unit)
    t, b = p.get("target", {}), p.get("baseline", {})
    has_base = bool(diag["n_baseline"])
    judge = p.get("judgement", "비교 불가")
    lines, actions = [], []
    grp, ref = T.group_names(comp["mode"], comp.get("side"), style)
    short, label = PROP_SHORT[prop], PROP_LABEL[prop]
    has_spec = t.get("spec_rate") is not None

    # 1) 판정
    if style == "stat":
        if has_base:
            lines.append(f"{short} 평균 {_num(t.get('mean'), nd)}{u} (기준 {_num(b.get('mean'), nd)}{u}), "
                         f"이동 {_num(p.get('shift'), nd, True)}{u} = {p.get('shift_sigma')}σ → **{judge}**")
        else:
            lines.append(f"{short} 평균 {_num(t.get('mean'), nd)}{u}, 표준편차 {t.get('std')}{u} (전체 기간 기준, 기간 비교 없음)")
        if has_spec:
            lines.append(f"스펙 만족률 {t.get('spec_rate')}% (미달 {t.get('below_spec')}개, 초과 {t.get('above_spec')}개), "
                         f"Cpk {t.get('cpk')}")
    elif style == "easy":
        if has_base and p.get("shift") is not None:
            if judge in ("상향 분포", "하향 분포", "상향 경향", "하향 경향"):
                way = "높게" if p["shift"] > 0 else "낮게"
                lines.append(f"{label} 평균이 평소보다 {_num(abs(p['shift']), nd)}{u} {way} 나왔어요 "
                             f"(평균 {_num(t.get('mean'), nd)}{u}, 나머지 기간 {_num(b.get('mean'), nd)}{u}). "
                             f"**{T.judgement(judge, style)}**")
            else:
                lines.append(f"{label} 평균은 평소와 비슷해요 (평균 {_num(t.get('mean'), nd)}{u}, 나머지 기간 "
                             f"{_num(b.get('mean'), nd)}{u}).")
        else:
            lines.append(f"전체 기간 {label} 평균은 {_num(t.get('mean'), nd)}{u}예요.")
        if has_spec:
            bad = (t.get("below_spec") or 0) + (t.get("above_spec") or 0)
            lines.append(f"{t.get('n')}개 중 {bad}개가 스펙을 벗어났어요 (만족률 {t.get('spec_rate')}%)."
                         if bad else f"{t.get('n')}개 모두 스펙 안에 있어요.")
    else:  # expert
        if has_base and p.get("shift") is not None:
            lines.append(f"{diag['grade']} {short} 평균 {_num(t.get('mean'), nd)}{u}로 비교 기간 대비 "
                         f"{_num(p.get('shift'), nd, True)}{u}({_num(p.get('shift_sigma'), 2, True)}σ) "
                         f"**{T.judgement(judge, style)}**.")
        else:
            lines.append(f"{diag['grade']} {short} 평균 {_num(t.get('mean'), nd)}{u}, σ {t.get('std')}{u} (전 기간).")
        if has_spec:
            lines.append(f"스펙 만족률 {t.get('spec_rate')}%, Cpk {t.get('cpk')} "
                         f"(하한 미달 {t.get('below_spec')}개, 상한 초과 {t.get('above_spec')}개).")

    # 2) 원인 후보
    top = [r for r in comp["ranking"] if abs(r["effect_size"]) >= 0.5][:3]
    if not top:
        lines.append({"stat": "두 군 사이에 뚜렷하게 다른 공정 인자가 없습니다 (효과크기 0.5 미만).",
                      "easy": f"{grp}, {ref} 사이에 눈에 띄게 다른 공정 조건은 없어요.",
                      "expert": "두 그룹 간 유의한 공정인자 차이가 관찰되지 않는다 (효과크기 0.5 미만)."}[style])
    for i, r in enumerate(top):
        mech, ru = r["mechanism"], r["unit"]
        std_part = r["standard"] is not None
        if style == "stat":
            std_txt = f", 표준 {_fv(r['standard'], ru)} 대비 {_fd(r['group_vs_standard'], ru)}" if std_part else ""
            text = (f"{r['rank']}순위 {r['label']}: 비교군 {_fv(r['group_mean'], ru)}{ru} vs 기준 "
                    f"{_fv(r['reference_mean'], ru)}{ru} ({_fd(r['diff'], ru)}, 효과크기 {r['effect_size']}{std_txt})"
                    f" - {T.mechanism(mech['status'], style)}")
            if mech["text"]:
                text += f"  \n  └ {mech['text']} ({mech['source']})"
        elif style == "easy":
            lead = "가장 눈에 띄는 차이는" if i == 0 else "그다음은"
            text = (f"{lead} **{r['label']}** 쪽이에요. {josa(grp)} {_fv(r['group_mean'], ru)}{ru}, {josa(ref)} "
                    f"{_fv(r['reference_mean'], ru)}{ru}로 {_fd(r['diff'], ru)}{ru} 차이가 나요.")
            if mech["status"] == "일치" and mech["easy"]:
                text += f" {mech['easy']}."
            elif mech["status"] == "불일치":
                text += " 다만 야금 원리와는 반대 방향이라 다른 원인과 겹쳤을 수 있어요."
            else:
                text += " 같이 움직이긴 하지만 야금 원리로는 설명이 안 돼서 우연일 수도 있어요."
        else:  # expert
            std_txt = f", 표준 대비 {_fd(r['group_vs_standard'], ru)}{ru}" if std_part else ""
            text = (f"{r['rank']}순위 {r['label']} {_fd(r['diff'], ru)}{ru} (효과크기 {r['effect_size']}{std_txt}) — ")
            if mech["status"] == "일치" and mech["expert"]:
                text += f"{mech['expert']} ({mech['source']})."
            else:
                text += f"{T.mechanism(mech['status'], style)}."
        lines.append(text)
        if mech["status"] == "일치" and r["factor"] in ACTIONS:
            gap = f" (현재 평균이 표준보다 {_fd(r['group_vs_standard'], ru)}{ru})" if r["group_vs_standard"] is not None else ""
            actions.append(f"{r['label']}: {ACTIONS[r['factor']]}{gap}")
    if not actions and top:
        actions.append({"stat": "상위 인자가 지식베이스 메커니즘과 맞지 않습니다. 설비 로그와 시험 조건을 추가 확인하세요.",
                        "easy": "눈에 띄는 차이가 야금 원리로는 설명되지 않아요. 설비 기록과 시험 조건을 먼저 확인해 보세요.",
                        "expert": "상위 인자의 변화 방향이 메커니즘과 부합하지 않아 설비 이력·시험 조건 추가 확인이 필요하다."}[style])
    warnings = [T.warning_text(w, style) for w in diag.get("warnings", []) + comp.get("warnings", [])]
    return {"summary": lines, "actions": actions, "warnings": list(dict.fromkeys(warnings))}


def coil_story(res: dict, style: str = T.DEFAULT_STYLE) -> list[str]:
    """analyze_coil 결과(코일 1개)를 문장으로. tools/coil_lookup.py 참고."""
    lines = []
    worst = [m for m in res.get("materials", []) if m.get("z") is not None]
    worst.sort(key=lambda m: -abs(m["z"]))
    factors = [f for f in res.get("factors", []) if f.get("z") is not None and abs(f["z"]) >= 1.5][:3]
    coil = res["coil_no"]
    for m in worst[:2]:
        if abs(m["z"]) < 1:
            continue
        nd, u = PROP_DECIMALS.get(m["prop"], 1), _u(PROP_UNIT[m["prop"]])
        diff = m["value"] - m["mass_median"]
        if style == "easy":
            lines.append(f"{coil} 코일은 양산보다 {PROP_LABEL[m['prop']]} 값이 {_num(abs(diff), nd)}{u} "
                         f"{'높아요' if diff > 0 else '낮아요'} (양산 중 {m['percentile']:.0f}% 위치).")
        elif style == "expert":
            lines.append(f"{coil}: {PROP_SHORT[m['prop']]} {_num(m['value'], nd)}{u}, 양산 대비 "
                         f"{_num(diff, nd, True)}{u}({m['z']:+.1f}σ, 백분위 {m['percentile']:.0f}).")
        else:
            lines.append(f"{coil} {PROP_SHORT[m['prop']]} {_num(m['value'], nd)}{u} (양산 중앙값 {_num(m['mass_median'], nd)}"
                         f"±{_num(m['mass_std'], nd)}, z={m['z']:+.2f}, {m['percentile']:.0f}%ile)")
    if not lines:
        lines.append({"easy": f"{coil} 코일의 재질은 양산 코일들과 비슷한 수준이에요.",
                      "expert": f"{coil}의 재질은 양산 분포 ±1σ 이내로 정상 범위이다.",
                      "stat": f"{coil}: 모든 재질 |z| < 1"}[style])
    for f in factors:
        ru = f["unit"]
        mech = f.get("mechanism") or {}
        if style == "easy":
            txt = (f"공정에서는 **{f['label']}** 값이 양산보다 {_fd(f['value'] - f['mass_median'], ru)}{ru} 달라요.")
            if mech.get("status") == "일치" and mech.get("easy"):
                txt += f" {mech['easy']}."
        elif style == "expert":
            txt = f"{f['label']} {_fd(f['value'] - f['mass_median'], ru)}{ru}({f['z']:+.1f}σ)"
            txt += f" — {mech['expert']} ({mech['source']})." if mech.get("status") == "일치" and mech.get("expert") else "."
        else:
            txt = f"{f['label']}: {_fv(f['value'], ru)} vs 양산 {_fv(f['mass_median'], ru)} (z={f['z']:+.2f}, {T.mechanism(mech.get('status', ''), 'stat')})"
        lines.append(txt)
    if not factors:
        lines.append({"easy": "공정 조건은 양산과 크게 다르지 않아요. 시험 조건이나 측정 편차를 확인해 보세요.",
                      "expert": "공정인자는 양산 대비 ±1.5σ 이내로, 재질 차이의 공정 원인은 특정되지 않는다.",
                      "stat": "|z| ≥ 1.5 공정인자 없음"}[style])
    return lines
