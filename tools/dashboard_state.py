"""대시보드 상태: 필터·그래프 변수. 사이드바와 에이전트(update_dashboard)·오프라인 해석기가 같은 규칙으로 바꾼다.

강종·라인·기간·코드 목록은 현재 데이터 소스에서 읽는다 (업로드 데이터면 그 데이터 기준).
v3 (prd_v3 U1): 출강목표·용도코드·공장 복수 선택, 두께 최소~최대, 원인 순위 모델.
v8 (prd_v8): 탭 이름 재질개요 → 강종개요. v5 (prd_v5): 탭 이름 재질개요·공정분석·결함분석·코일분석·데이터 (옛 이름 호환), 재질 기본 YP·TS·EL.
v4 (prd_v4): 재질 복수 선택 props(빈 목록 = TS) + 분석 재질 prop, 규격약호 압연·정정 함께(spec_cols, 값은 "roll:코드"),
불량 코일 σ 수준 sigma(기본 1.0), 표면결함 범위 defect_scope(grade/all).
"""
from datetime import date

from tools.coil_lookup import ID_TYPES
from tools.datasource import get_source
from tools.domain import DEFECTS, FACTORS, PROPS
from tools.ranking import START as DEFAULT_MODEL
from tools.ranking import MODELS

VIEWS = ["강종개요", "공정분석", "결함분석", "코일분석", "데이터"]  # prd_v5 T1
VIEW_ICON = {"강종개요": ":material/bar_chart:", "공정분석": ":material/settings:", "결함분석": ":material/extension:",
             "코일분석": ":material/biotech:", "데이터": ":material/description:"}  # 시안 아이콘 (prd_v8 U2)
# 옛 이름(v2~v4)도 받는다: 링크·즐겨찾기 호환 (prd_v5 C4)
VIEW_ALIASES = {"재질개요": "강종개요", "재질 현황": "강종개요", "재질 편차": "강종개요", "원인 분석": "공정분석", "표면결함": "결함분석",
                "단일 코일 분석": "코일분석", "코일 단건 분석": "코일분석", "Raw Data": "데이터"}
SIDES = {"auto": "자동", "low": "낮은 쪽", "high": "높은 쪽"}
PREFERRED_GRADE = "HSLA590C"
SPEC_COLS = {"spec_roll": "압연규격약호", "spec_fin": "정정규격약호"}
SPEC_TAG = {"spec_roll": "roll", "spec_fin": "fin"}  # 규격약호 값 앞에 붙여 출처 구분 ("roll:CR590HSA")
SPEC_TAG_LABEL = {"roll": "압연", "fin": "정정"}
DEFAULT_PROP = "TS"  # 재질을 아무것도 고르지 않았을 때 (prd_v4 L5)
DEFAULT_PROPS = ["YS", "TS", "EL"]  # 재질 체크박스 기본 (prd_v5 T2)
SIGMAS = [round(0.5 + 0.1 * i, 1) for i in range(26)]  # 0.5 ~ 3.0σ (prd_v4 M2)
BASES = {"sigma": "σ 기준", "spec": "스펙 불량"}  # 공정분석 불량 코일 기준 (prd_v6: 고를 수 있게, 기본 σ)
DEFECT_SCOPES = {"grade": "선택 강종", "all": "전체 강종"}
CODE_FILTERS = {"specs": "규격약호", "aims": "출강목표", "uses": "용도코드", "plants": "공장"}  # 상태 키 → 화면 이름
THK_BANDS = {"전체": (None, None), "~0.75": (None, 0.75), "0.75~1.0": (0.75, 1.0), "1.0~1.4": (1.0, 1.4),
             "1.4~": (1.4, None)}
COIL_POS = {"전체": "전체", "T": "선단(T)", "M": "중앙(M)", "B": "후단(B)"}


def grades() -> list[str]:
    return get_source().grade_codes()


def lines() -> list[str]:
    return ["전체"] + get_source().lines()


def data_range() -> tuple[date, date]:
    lo, hi = get_source().date_range()
    return date.fromisoformat(lo), date.fromisoformat(hi)


def props() -> list[str]:
    src = get_source()
    return [p for p in PROPS if src.has(p)]


def code_column(key: str, state: dict) -> str | None:
    """코드 필터 상태 키 → 데이터 컬럼 (규격약호는 spec_cols가 여러 개라 code_options/subset_args가 따로 처리)."""
    return {"specs": (state.get("spec_cols") or ["spec_roll"])[0], "aims": "aim", "uses": "use_code",
            "plants": "plant"}.get(key)


def code_options(key: str, state: dict, grade: str | None = None) -> dict:
    """필터 값 → 코일 수 (현재 데이터, 강종을 주면 그 강종 안에서). 규격약호는 "roll:코드"/"fin:코드"."""
    df = get_source().coils
    if grade:
        df = df[df["grade"] == grade]
    if key == "specs":
        out = {}
        for col in state.get("spec_cols") or ["spec_roll"]:
            if col in df.columns:
                for code, n in df[col].dropna().astype(str).value_counts().sort_index().items():
                    out[f"{SPEC_TAG[col]}:{code}"] = int(n)
        return out
    col = code_column(key, state)
    if col not in df.columns:
        return {}
    return df[col].dropna().astype(str).value_counts().sort_index().to_dict()


def spec_label(value: str) -> str:
    """"roll:CR590HSA" → "[압연] CR590HSA"."""
    tag, _, code = value.partition(":")
    return f"[{SPEC_TAG_LABEL[tag]}] {code}" if code and tag in SPEC_TAG_LABEL else value


def focus_prop(state: dict) -> str:
    """원인 분석·조기 감시 기준 재질: 고른 재질 중 prop, 없으면 첫 번째, 아무것도 없으면 TS."""
    chosen = state.get("props") or []
    if state.get("prop") in chosen or (not chosen and state.get("prop")):
        return state["prop"]
    return chosen[0] if chosen else DEFAULT_PROP


def shown_props(state: dict) -> list[str]:
    """화면에 보여줄 재질 (아무것도 안 고르면 TS 하나)."""
    ps = props()
    chosen = [p for p in state.get("props") or [] if p in ps]
    return chosen or [DEFAULT_PROP if DEFAULT_PROP in ps else ps[0]]


def thk_limits() -> tuple[float, float]:
    s = get_source().coils["thk"].dropna() if "thk" in get_source().coils else None
    return (float(s.min()), float(s.max())) if s is not None and len(s) else (0.0, 5.0)


def defaults() -> dict:
    start, end = data_range()
    gs = grades()
    lo, hi = thk_limits()
    return {"grade": PREFERRED_GRADE if PREFERRED_GRADE in gs else gs[0], "line": "전체", "start": start, "end": end,
            "prop": DEFAULT_PROP if DEFAULT_PROP in props() else props()[0],
            "props": [p for p in DEFAULT_PROPS if p in props()],
            "factor": "자동", "defect": "파우더링", "side": "auto", "sigma": 1.0, "basis": "sigma",
            "view": "강종개요", "coil_ids": "", "id_type": "coil_no", "model": DEFAULT_MODEL,
            "spec_cols": ["spec_roll"], "specs": [], "aims": [], "uses": [], "plants": [],
            "thk_min": lo, "thk_max": hi, "coil_pos": "전체", "defect_scope": "grade"}


def _to_date(v):
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _as_list(v) -> list[str]:
    if v in (None, "", "전체"):
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return [str(x) for x in v]


def apply_update(state: dict, changes: dict) -> tuple[dict, dict, list[str]]:
    """변경 요청을 검증해 새 상태, 실제 적용된 항목, 오류 목록을 반환한다."""
    new, applied, errors = dict(state), {}, []
    aliases = {"CGL": "CGL_GA", "all": "전체", "ALL": "전체", None: "전체"}
    start_min, end_max = data_range()
    gs, ls, ps = grades(), lines(), props()
    changes = dict(changes)
    if "thk_band" in changes:  # v2 두께 구간 → 최소~최대
        band = changes.pop("thk_band")
        if band in THK_BANDS:
            lo, hi = THK_BANDS[band]
            limit_lo, limit_hi = thk_limits()
            changes.setdefault("thk_min", lo if lo is not None else limit_lo)
            changes.setdefault("thk_max", hi if hi is not None else limit_hi)
        else:
            errors.append(f"thk_band={band!r}: 두께 구간은 {list(THK_BANDS)} 중 하나")
    changes.pop("style", None)  # v3에서 문체 선택 삭제 (쉬운 말 하나)
    if "spec_col" in changes:  # v3 단일 기준 → v4 목록
        changes.setdefault("spec_cols", [changes.pop("spec_col")])
    for key, value in changes.items():
        if value is None:
            continue
        try:
            if key == "grade":
                if value not in gs:
                    raise ValueError(f"강종은 {gs} 중 하나")
            elif key == "line":
                value = aliases.get(value, value)
                if value not in ls:
                    raise ValueError(f"라인은 {ls} 중 하나")
            elif key in ("start_date", "end_date", "start", "end"):
                d = _to_date(value)
                d = min(max(d, start_min), end_max)  # 데이터 기간 밖이면 가장자리로
                key, value = ("start" if key.startswith("start") else "end"), d
            elif key == "prop":
                if value not in ps:
                    raise ValueError(f"재질은 {ps} 중 하나")
                chosen = list(new.get("props") or [])
                if chosen and value not in chosen:  # 에이전트가 고른 재질은 화면 체크에도 넣는다
                    new["props"] = [value] + chosen
                    applied["props"] = new["props"]
            elif key == "props":
                value = [v for v in _as_list(value) if v in ps]
                if value and new.get("prop") not in value:
                    new["prop"] = applied["prop"] = value[0]
                elif not value:
                    new["prop"] = applied["prop"] = DEFAULT_PROP if DEFAULT_PROP in ps else ps[0]
            elif key == "sigma":
                value = round(min(max(float(value), 0.5), 3.0), 1)
            elif key == "basis":
                if value not in BASES:
                    raise ValueError(f"불량 코일 기준은 {list(BASES)} 중 하나")
            elif key == "defect_scope":
                if value not in DEFECT_SCOPES:
                    raise ValueError(f"결함 범위는 {list(DEFECT_SCOPES)} 중 하나")
            elif key == "factor":
                if value not in FACTORS and value != "자동":
                    raise ValueError("factor는 인자 코드(CT, SS, SPM, P ...) 또는 '자동'")
            elif key == "defect":
                if value not in DEFECTS:
                    raise ValueError(f"결함은 {list(DEFECTS)} 중 하나")
            elif key == "side":
                if value not in SIDES:
                    raise ValueError(f"side는 {list(SIDES)} 중 하나")
            elif key == "view":
                value = VIEW_ALIASES.get(value, value)
                if value not in VIEWS:
                    raise ValueError(f"view는 {VIEWS} 중 하나")
            elif key == "coil_ids":
                value = ", ".join(value) if isinstance(value, (list, tuple)) else str(value)
            elif key == "id_type":
                if value not in ID_TYPES:
                    raise ValueError(f"번호 종류는 {list(ID_TYPES)} 중 하나")
            elif key == "model":
                if value not in MODELS:
                    raise ValueError(f"모델은 {list(MODELS)} 중 하나")
            elif key == "spec_cols":
                value = [v for v in _as_list(value) if v in SPEC_COLS] or ["spec_roll"]
            elif key in CODE_FILTERS:
                value = _as_list(value)  # 데이터에 없는 값도 그대로 둔다 (화면에서 "해당 코일 없음" 안내)
            elif key in ("thk_min", "thk_max"):
                value = round(float(value), 2)
            elif key == "coil_pos":
                if value not in COIL_POS:
                    raise ValueError(f"시편 위치는 {list(COIL_POS)} 중 하나")
            else:
                raise ValueError("알 수 없는 항목")
        except (ValueError, TypeError) as e:
            errors.append(f"{key}={value!r}: {e}")
            continue
        new[key], applied[key] = value, value
    if new["start"] > new["end"]:
        errors.append("시작일이 종료일보다 늦어 기간 변경을 취소했습니다.")
        new["start"], new["end"] = state["start"], state["end"]
        applied.pop("start", None), applied.pop("end", None)
    if new.get("thk_min", 0) > new.get("thk_max", 99):
        new["thk_min"], new["thk_max"] = new["thk_max"], new["thk_min"]
    if new["prop"] not in get_source().spec(new["grade"]) and new["prop"] == "BH":
        errors.append(f"BH는 {new['grade']}에 스펙·데이터가 없어 YP로 바꿨습니다.")
        new["prop"] = "YS"
    return new, {k: (v if isinstance(v, list) else str(v)) for k, v in applied.items()}, errors


def describe(state: dict) -> dict:
    """에이전트에게 보여줄 JSON 형태."""
    out = {"grade": state["grade"], "line": state["line"], "start_date": str(state["start"]),
           "end_date": str(state["end"]), "prop": state["prop"], "factor": state["factor"],
           "defect": state["defect"], "side": state["side"], "view": state["view"],
           "model": state.get("model", DEFAULT_MODEL), "coil_pos": state.get("coil_pos", "전체"),
           "props": shown_props(state), "sigma": state.get("sigma", 1.0), "basis": state.get("basis", "sigma"), "defect_scope": state.get("defect_scope", "grade"),
           "thk_min": state.get("thk_min"), "thk_max": state.get("thk_max")}
    for key in CODE_FILTERS:
        if state.get(key):
            out[key] = state[key]
    if state.get("specs"):
        out["spec_cols"] = state.get("spec_cols", ["spec_roll"])
    if state.get("coil_ids"):
        out.update(coil_ids=state["coil_ids"], id_type=state.get("id_type", "coil_no"))
    return out


def is_full_period(state: dict) -> bool:
    start, end = data_range()
    return state["start"] <= start and state["end"] >= end


def analysis_args(state: dict) -> dict:
    """분석 함수 공통 인자. 전체 기간이면 기간 비교 대신 불량 코일 vs 정상 코일 비교를 쓴다."""
    full = is_full_period(state)
    return {"grade": state["grade"], "line": None if state["line"] == "전체" else state["line"],
            "start": None if full else str(state["start"]), "end": None if full else str(state["end"])}


def subset_args(state: dict) -> dict:
    """화면 필터 중 강종·라인·기간 외 나머지 (analysis 함수의 thk_min·thk_max·coil_pos·where 인자)."""
    lo, hi = thk_limits()
    where = {code_column(k, state): state.get(k) for k in CODE_FILTERS if state.get(k) and k != "specs"}
    if state.get("specs"):  # 규격약호: 압연·정정 열끼리 OR (태그 없는 값은 고른 열 모두에서 찾는다)
        cols = state.get("spec_cols") or ["spec_roll"]
        anyof = {c: [] for c in cols}
        for v in state["specs"]:
            tag, _, code = str(v).partition(":")
            col = next((c for c, t in SPEC_TAG.items() if t == tag), None) if code else None
            for c in ([col] if col else cols):
                anyof.setdefault(c, []).append(code if col else v)
        where["__any__"] = {c: v for c, v in anyof.items() if v}
    return {"thk_min": state["thk_min"] if state.get("thk_min") is not None and state["thk_min"] > lo else None,
            "thk_max": state["thk_max"] if state.get("thk_max") is not None and state["thk_max"] < hi else None,
            "coil_pos": None if state.get("coil_pos", "전체") == "전체" else state["coil_pos"],
            "where": where or None}
