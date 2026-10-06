"""대시보드 상태: 필터·그래프 변수. 사이드바와 에이전트(update_dashboard)·오프라인 해석기가 같은 규칙으로 바꾼다.

강종·라인·기간은 현재 데이터 소스에서 읽는다 (업로드 데이터면 그 데이터 기준).
"""
from datetime import date

from tools.coil_lookup import ID_TYPES
from tools.datasource import get_source
from tools.domain import DEFECTS, FACTORS, PROPS
from tools.terms import DEFAULT_STYLE, STYLES

VIEWS = ["재질 편차", "원인 분석", "표면결함", "코일 단건 분석", "Raw Data"]
SIDES = {"auto": "자동", "low": "낮은 쪽", "high": "높은 쪽"}
PREFERRED_GRADE = "HSLA590C"


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


def defaults() -> dict:
    start, end = data_range()
    gs = grades()
    return {"grade": PREFERRED_GRADE if PREFERRED_GRADE in gs else gs[0], "line": "전체", "start": start, "end": end,
            "prop": "YS" if "YS" in props() else props()[0], "factor": "자동", "defect": "파우더링", "side": "auto",
            "view": "재질 편차", "coil_ids": "", "id_type": "coil_no", "style": DEFAULT_STYLE,
            "thk_band": "전체", "coil_pos": "전체"}


THK_BANDS = ["전체", "~0.75", "0.75~1.0", "1.0~1.4", "1.4~"]
COIL_POS = {"전체": "전체", "T": "선단(T)", "M": "중앙(M)", "B": "후단(B)"}


def _to_date(v):
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def apply_update(state: dict, changes: dict) -> tuple[dict, dict, list[str]]:
    """변경 요청을 검증해 새 상태, 실제 적용된 항목, 오류 목록을 반환한다."""
    new, applied, errors = dict(state), {}, []
    aliases = {"CGL": "CGL_GA", "all": "전체", "ALL": "전체", None: "전체"}
    start_min, end_max = data_range()
    gs, ls, ps = grades(), lines(), props()
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
            elif key == "factor":
                if value not in FACTORS and value != "자동":
                    raise ValueError("factor는 coil 컬럼명(CT, SS, SPM, P ...) 또는 '자동'")
            elif key == "defect":
                if value not in DEFECTS:
                    raise ValueError(f"결함은 {list(DEFECTS)} 중 하나")
            elif key == "side":
                if value not in SIDES:
                    raise ValueError(f"side는 {list(SIDES)} 중 하나")
            elif key == "view":
                if value not in VIEWS:
                    raise ValueError(f"view는 {VIEWS} 중 하나")
            elif key == "coil_ids":
                value = ", ".join(value) if isinstance(value, (list, tuple)) else str(value)
            elif key == "id_type":
                if value not in ID_TYPES:
                    raise ValueError(f"번호 종류는 {list(ID_TYPES)} 중 하나")
            elif key == "thk_band":
                if value not in THK_BANDS:
                    raise ValueError(f"두께 구간은 {THK_BANDS} 중 하나")
            elif key == "coil_pos":
                if value not in COIL_POS:
                    raise ValueError(f"시편 위치는 {list(COIL_POS)} 중 하나")
            elif key == "style":
                if value not in STYLES:
                    raise ValueError(f"문체는 {list(STYLES)} 중 하나")
            else:
                raise ValueError("알 수 없는 항목")
        except ValueError as e:
            errors.append(f"{key}={value!r}: {e}")
            continue
        new[key], applied[key] = value, value
    if new["start"] > new["end"]:
        errors.append("시작일이 종료일보다 늦어 기간 변경을 취소했습니다.")
        new["start"], new["end"] = state["start"], state["end"]
        applied.pop("start", None), applied.pop("end", None)
    if new["prop"] not in get_source().spec(new["grade"]) and new["prop"] == "BH":
        errors.append(f"BH는 {new['grade']}에 스펙·데이터가 없어 YS로 바꿨습니다.")
        new["prop"] = "YS"
    return new, {k: str(v) for k, v in applied.items()}, errors


def describe(state: dict) -> dict:
    """에이전트에게 보여줄 JSON 형태."""
    out = {"grade": state["grade"], "line": state["line"], "start_date": str(state["start"]),
           "end_date": str(state["end"]), "prop": state["prop"], "factor": state["factor"],
           "defect": state["defect"], "side": state["side"], "view": state["view"],
           "style": state.get("style", DEFAULT_STYLE), "thk_band": state.get("thk_band", "전체"),
           "coil_pos": state.get("coil_pos", "전체")}
    if state.get("coil_ids"):
        out.update(coil_ids=state["coil_ids"], id_type=state.get("id_type", "coil_no"))
    return out


def is_full_period(state: dict) -> bool:
    start, end = data_range()
    return state["start"] <= start and state["end"] >= end


def analysis_args(state: dict) -> dict:
    """분석 함수 공통 인자. 전체 기간이면 기간 비교 대신 문제 코일 vs 정상 코일 비교를 쓴다."""
    full = is_full_period(state)
    return {"grade": state["grade"], "line": None if state["line"] == "전체" else state["line"],
            "start": None if full else str(state["start"]), "end": None if full else str(state["end"])}


def subset_args(state: dict) -> dict:
    """두께 구간·시편 위치 필터 ("나눠서 다시 비교"용)."""
    return {"thk_band": None if state.get("thk_band", "전체") == "전체" else state["thk_band"],
            "coil_pos": None if state.get("coil_pos", "전체") == "전체" else state["coil_pos"]}
