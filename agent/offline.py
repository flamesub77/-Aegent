"""오프라인 질문 해석기 (prd_v2 R4): API 없이 키워드로 조건을 뽑아 대시보드를 바꾸고 규칙 기반으로 답한다.

LLM을 쓰지 않으므로 외부 통신이 없다. 수치와 문장은 분석 엔진·narrative에서만 만든다.
"""
import calendar
import json
import re

from tools import analysis as A
from tools import coil_lookup as L
from tools import dashboard_state as ds
from tools import narrative as N
from tools import terms as T
from tools.datasource import get_source
from tools.domain import DEFECTS, PROP_LABEL

# 순서가 중요하다: 긴 표현·구체적인 표현을 먼저 본다
GRADE_ALIASES = [
    (r"극저\s*외판|고강도\s*극저|if\s*340", "IF340_OUT"), (r"극저\s*내판|if\s*270|270e?", "IF270_IN"),
    (r"\bbh\b|bh\s*340|bh\s*외판|소부경화강", "BH340_OUT"), (r"590\s*c?|hsla", "HSLA590C"),
    (r"440\s*r?", "LC440R"), (r"(?<!\d)340(?!\d)|저탄\s*340", "LC340"),
]
LINE_ALIASES = [(r"\bcal\b|연속소둔", "CAL"), (r"\bcgl\b|ga\s*재|\bga\b|도금재|용융아연", "CGL_GA")]
PROP_ALIASES = [
    (r"평면\s*이방성|δ\s*r|델타\s*r|이어링|delta\s*r|\bdr\b", "dr"),
    (r"r\s*바|r̄|rbar|r\s*bar|평균\s*r|소성\s*이방성|r값|딥\s*드로", "rbar"),
    (r"n\s*값|가공\s*경화|n_value|\bn\s*value", "n_value"),
    (r"항복|\bys\b|\byp\b", "YS"), (r"인장|\bts\b", "TS"), (r"연신|\bel\b", "EL"), (r"소부|\bbh\b", "BH"),
]
FACTOR_ALIASES = [
    (r"균열\s*온도|소둔\s*온도|\bss\b", "SS"), (r"권취|\bct\b", "CT"), (r"재가열|\bsrt\b", "SRT"),
    (r"마무리|사상\s*온도|\bfdt\b", "FDT"), (r"압하율|\bred\b", "RED"), (r"과시효|\boa\b", "OA"),
    (r"합금화", "GA_temp"), (r"도금욕|포트\s*온도", "pot_temp"), (r"주조\s*속도|고속\s*주조", "cast_speed"),
    (r"\bspm\b|조질", "SPM"), (r"라인\s*속도|통판\s*속도", "line_speed"), (r"디스케일", "descale_press"),
    (r"산세\s*속도", "pickle_speed"), (r"염산|hcl", "hcl_conc"), (r"과열도", "superheat"),
]
VIEW_ALIASES = [(r"raw|원본|원천|데이터\s*표|엑셀", "Raw Data"), (r"원인|왜|이유|때문", "원인 분석"),
                (r"분포|편차|히스토그램|추이", "재질 편차")]
STYLE_ALIASES = [(r"쉽게|쉬운\s*말|구어체", "easy"), (r"전문가|전공|야금|금속재료", "expert"), (r"통계", "stat")]
ID_WORDS = [(r"열연\s*코일|열연", "hot_coil_no"), (r"슬라브|slab", "slab_no"), (r"히트|heat|차지", "heat_no")]

EXAMPLES = ["5월 CAL 590C 항복강도 원인", "3월 극저 외판 r값", "6월 GA재 파우더링", "C260500123 코일 양산이랑 비교",
            "산점도를 균열온도로", "전문가 문체로"]


def _find(patterns, text):
    for pat, val in patterns:
        if re.search(pat, text, re.I):
            return val
    return None


def _ids(text: str):
    """데이터에 실제로 있는 번호만 인식한다. (id_type, [번호])."""
    df = get_source().coils
    tokens = re.findall(r"[A-Za-z]{0,3}\d{5,}", text)
    if not tokens:
        return None, []
    hinted = _find(ID_WORDS, text)
    order = [hinted] if hinted else []
    order += [c for c in ("coil_no", "hot_coil_no", "slab_no", "heat_no") if c not in order]
    for col in order:
        if col and col in df.columns:
            have = set(df[col].astype(str))
            hit = [t for t in tokens if t in have]
            if hit:
                return col, hit
    return hinted or "coil_no", tokens  # 없는 번호도 넘겨서 후보를 보여준다


def parse_question(text: str, state: dict) -> tuple[dict, list[str]]:
    """질문 → (대시보드 변경 dict, 인식한 조건 설명 목록)."""
    q = text.strip()
    ch, seen = {}, []
    codes = get_source().grade_codes()
    grade = next((c for c in codes if c.lower() in q.lower()), None) or _find(GRADE_ALIASES, q)
    if grade and grade in codes:
        ch["grade"] = grade
        seen.append(f"강종 {grade}")
    line = _find(LINE_ALIASES, q)
    if line and line in ds.lines():
        ch["line"] = line
        seen.append(f"라인 {line}")
    m = re.search(r"(?<!\d)(1[0-2]|[1-9])\s*월", q)
    if m:
        year = ds.data_range()[1].year
        mon = int(m.group(1))
        ch["start_date"] = f"{year}-{mon:02d}-01"
        ch["end_date"] = f"{year}-{mon:02d}-{calendar.monthrange(year, mon)[1]:02d}"
        seen.append(f"기간 {year}년 {mon}월")
    elif re.search(r"전체\s*기간|전\s*기간|상반기|전체로", q):
        lo, hi = ds.data_range()
        ch["start_date"], ch["end_date"] = str(lo), str(hi)
        seen.append("전체 기간")
    prop = _find(PROP_ALIASES, q)
    if prop and prop in ds.props():
        ch["prop"] = prop
        seen.append(PROP_LABEL[prop])
    factor = _find(FACTOR_ALIASES, q)
    if factor:
        ch["factor"] = factor
        seen.append(f"원인 인자 {factor}")
    defect = next((d for d in DEFECTS if d in q), None)
    if defect:
        ch["defect"], ch["view"] = defect, "표면결함"
        seen.append(f"결함 {defect}")
    id_type, ids = _ids(q)
    if ids:
        ch.update(coil_ids=", ".join(ids), id_type=id_type, view="코일 단건 분석")
        seen.append(f"{L.ID_TYPES[id_type]} {', '.join(ids[:3])}{' 외' if len(ids) > 3 else ''}")
    style = _find(STYLE_ALIASES, q)
    if style:
        ch["style"] = style
        seen.append(f"문체 {T.STYLES[style]}")
    if "view" not in ch and factor and re.search(r"산점도|x\s*축|추이|인자", q):
        ch["view"] = "원인 분석"
    if "view" not in ch:
        view = _find(VIEW_ALIASES, q)
        if view:
            ch["view"] = view
    if re.search(r"낮|떨어|하락|미달|저하", q):
        ch["side"] = "low"
    elif re.search(r"높|올라|상승|초과", q):
        ch["side"] = "high"
    return ch, seen


def answer(question: str, state: dict, on_tool=None):
    """AgentResult와 같은 모양으로 돌려준다 (app·report 재사용)."""
    from agent.agent import AgentResult, ToolCall

    changes, seen = parse_question(question, state)
    new_state, applied, errors = ds.apply_update(state, changes)
    style = new_state.get("style", T.DEFAULT_STYLE)
    calls: list[ToolCall] = []

    def record(name, args, result):
        calls.append(ToolCall(name, args, json.dumps(result, ensure_ascii=False, default=str), "error" in result))
        if on_tool:
            on_tool(calls[-1])
        return result

    if changes:
        record("update_dashboard", changes, {"applied": applied, "errors": errors})
    lines = [f"**인식한 조건**: {', '.join(seen)}" if seen else ""]
    args = ds.analysis_args(new_state)

    if new_state.get("view") == "코일 단건 분석" and "coil_ids" in changes:
        res = record("analyze_coil", {"ids": new_state["coil_ids"], "id_type": new_state["id_type"]},
                     L.compact(L.analyze_coil(new_state["coil_ids"], new_state["id_type"])))
        full = L.analyze_coil(new_state["coil_ids"], new_state["id_type"])
        if full.get("missing"):
            sug = "; ".join(f"{k} → {', '.join(v[:3])}" for k, v in full.get("suggestions", {}).items())
            lines.append(f"찾지 못한 번호: {', '.join(full['missing'])}" + (f" (비슷한 번호: {sug})" if sug else ""))
        for c in full.get("coils", [])[:3]:
            lines += [f"- {x}" for x in N.coil_story(c, style)]
            lines += [f"- ⚠ {T.warning_text(w, style)}" for w in c["warnings"]]
        if full.get("common"):
            lines.append("여러 코일에서 공통으로 벗어난 인자: " + ", ".join(
                f"{x['label']}({x['direction']}, {x['coils']}/{x['of']})" for x in full["common"]))
        if not full.get("coils") and not full.get("missing"):
            lines.append(res.get("error", "분석할 코일이 없습니다."))
    elif new_state.get("view") == "표면결함" and "defect" in changes:
        grade = changes.get("grade")  # 결함은 강종을 말했을 때만 좁힌다
        r = record("trace_defect", {"defect_type": new_state["defect"], "grade": grade, **{k: args[k] for k in ("line", "start", "end")}},
                   A.defect_trace(new_state["defect"], grade, args["line"], args["start"], args["end"]))
        if "error" in r:
            lines.append(r["error"])
        else:
            lines.append(_defect_text(r, style))
    elif changes.keys() - {"style", "factor", "side", "view"} or re.search(r"원인|왜|이유|해석|분석", question):
        diag = A.diagnose(**args)
        comp = A.compare(args["grade"], new_state["prop"], args["line"], args["start"], args["end"],
                         side=new_state["side"])
        record("diagnose_distribution", args, {k: v for k, v in diag.items() if k != "properties"})
        record("compare_groups", {**args, "target_property": new_state["prop"]},
               {k: v for k, v in comp.items() if k not in ("all_factors", "confounders")})
        ins = N.insights(diag, comp, style)
        lines += ins["summary"]
        if ins["actions"]:
            lines.append("**조치**\n" + "\n".join(f"- {a}" for a in ins["actions"]))
        lines += [f"⚠ {w}" for w in ins["warnings"]]
    elif changes:
        lines.append(f"화면을 바꿨어요: {', '.join(f'{k}={v}' for k, v in applied.items())}"
                     if style == "easy" else f"대시보드 변경: {', '.join(f'{k}={v}' for k, v in applied.items())}")
    else:
        lines = ["질문에서 강종·기간·재질·결함·코일번호를 찾지 못했어요. 오프라인 모드에서는 이렇게 물어보세요:",
                 *[f"- {e}" for e in EXAMPLES]]
    if errors:
        lines.append("적용하지 못한 조건: " + "; ".join(errors))
    text = "\n\n".join(x for x in lines if x)
    result = AgentResult(text, calls, new_state, applied, "offline")
    result.report["recognized"] = seen          # 화면에 칩으로 보여준다
    result.report["understood"] = bool(changes)  # False면 예시 질문 버튼을 보여준다
    return result


def _defect_text(r: dict, style: str) -> str:
    top = [f for f in r["factor_ranking"] if f["kb_consistent"]][:1] or r["factor_ranking"][:1]
    base, now = r["rate_baseline_pct"], r["rate_target_pct"]
    cause = r["kb_cause"]
    if style == "easy":
        head = (f"{r['defect_type']} 발생률이 {base}%에서 {now}%로 늘었어요." if base is not None and now > base
                else f"{r['defect_type']} 발생률은 {now}%예요.")
        if top:
            f = top[0]
            head += (f" 가장 차이가 큰 조건은 **{f['label']}** 쪽이고(결함 난 쪽 {N._fv(f['defect_mean'], f['unit'])}{f['unit']}"
                     f" vs 정상 {N._fv(f['normal_mean'], f['unit'])}{f['unit']})")
            head += ", 지식베이스에서도 이 결함의 원인으로 꼽는 조건이에요." if f["kb_consistent"] else "예요."
        return head + f" 보통 원인은 {cause['process']} 공정의 {N.josa(cause['cause'], '이에요/예요')}."
    tops = ", ".join(f"{f['label']}(효과크기 {f['effect_size']:+.2f})" for f in r["factor_ranking"][:3])
    return (f"{r['defect_type']} 발생률 {base}% → {now}% · 원인 후보: {tops} · 지식베이스 원인({cause['process']}): "
            f"{cause['cause']} ({cause['source']})")
