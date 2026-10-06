"""도구 이름 → 함수 매핑과 OpenAI Responses API function 스키마.

강종·라인·재질 목록은 현재 데이터 소스에서 읽으므로 스키마는 tool_schemas()로 매번 만든다.
"""
import json

from tools import coil_lookup
from tools import dashboard_state as ds
from tools.compare import compare_groups
from tools.defect import trace_defect
from tools.distribution import diagnose_distribution
from tools.domain import DEFECTS, FACTORS
from tools.knowledge import search_knowledge
from tools.query import query_coils
from tools.terms import STYLES

FACTOR_GUIDE = ", ".join(f"{k}={v[0]}" for k, v in FACTORS.items())


def _fn(name, description, properties, required=()):
    return {"type": "function", "name": name, "description": description, "strict": False,
            "parameters": {"type": "object", "properties": properties, "required": list(required),
                           "additionalProperties": False}}


def analyze_coil(ids, id_type="coil_no", months=3):
    """코일 단건 분석 (에이전트용 요약)."""
    return coil_lookup.compact(coil_lookup.analyze_coil(ids, id_type, months))


def tool_schemas() -> list[dict]:
    lo, hi = ds.data_range()
    grade = {"type": "string", "enum": ds.grades(), "description": "강종 코드"}
    line = {"type": "string", "enum": ds.lines()[1:], "description": "소둔 라인. 전체면 생략"}
    props = {"type": "string", "enum": ds.props(),
             "description": "재질. rbar=평균 r값(r̄), n_value=n값, dr=평면이방성 Δr"}
    date = {"type": "string", "description": f"YYYY-MM-DD (데이터 기간 {lo}~{hi})"}
    ids = {"type": "string", "enum": list(coil_lookup.ID_TYPES),
           "description": "coil_no=냉연코일, hot_coil_no=열연코일, slab_no=슬라브, heat_no=히트"}
    return [
        _fn("get_dashboard_state", "사용자가 지금 보고 있는 대시보드의 필터와 그래프 변수를 반환한다.", {}),
        _fn("update_dashboard",
            "대시보드 필터·그래프 변수를 바꿔 사용자가 보는 화면을 갱신한다. 사용자가 그래프나 조건 변경을 요청하거나, "
            "분석 결과를 보여주기 좋은 화면(예: 원인 인자 산점도, 코일 단건 분석)으로 전환할 때 사용. 바꿀 항목만 넣는다.",
            {"grade": grade, "line": {"type": "string", "enum": ds.lines()},
             "start_date": date, "end_date": date, "prop": props,
             "factor": {"type": "string", "enum": ["자동"] + list(FACTORS),
                        "description": f"원인 분석 산점도·추이에 쓸 인자 코드. 자동 = 1순위. {FACTOR_GUIDE}"},
             "defect": {"type": "string", "enum": list(DEFECTS)},
             "side": {"type": "string", "enum": list(ds.SIDES),
                      "description": "문제 코일 기준: low=낮게 나온 코일, high=높게 나온 코일"},
             "view": {"type": "string", "enum": ds.VIEWS, "description": "보여줄 화면"},
             "coil_ids": {"type": "string", "description": "코일 단건 분석 대상 번호 (여러 개면 쉼표)"},
             "id_type": ids,
             "style": {"type": "string", "enum": list(STYLES), "description": "해석 문체"},
             "thk_band": {"type": "string", "enum": ds.THK_BANDS,
                          "description": "두께 구간 필터 (비교 조건 차이가 있을 때 나눠서 다시 비교)"},
             "coil_pos": {"type": "string", "enum": list(ds.COIL_POS), "description": "시편 위치 필터"}}),
        _fn("query_coils", "조건별 코일 건수, 판정·결함 분포, 재질 요약을 조회한다.",
            {"grade": grade, "line": line, "start_date": date, "end_date": date,
             "thk_min": {"type": "number"}, "thk_max": {"type": "number"},
             "coil_pos": {"type": "string", "enum": ["T", "M", "B"]},
             "include_baseline": {"type": "boolean", "description": "대상 기간 밖 나머지 기간 요약도 함께"}}),
        _fn("diagnose_distribution",
            "대상 기간 재질 분포를 나머지 기간과 비교해 평균·표준편차·스펙 만족률·Cpk와 1σ 기준 판정을 반환한다.",
            {"grade": grade, "line": line, "start_date": date, "end_date": date,
             "baseline_start": date, "baseline_end": date,
             "properties": {"type": "array", "items": props}}, ["grade"]),
        _fn("compare_groups",
            "두 그룹(기간이 있으면 이 기간 vs 나머지 기간, 없으면 문제 코일 vs 정상 코일)의 성분·공정인자를 비교해 "
            "차이 크기(효과크기) 순위, 표준조건 대비, 지식베이스 메커니즘 일치 여부, 비교 조건 차이(두께·라인·시편 위치)를 반환한다.",
            {"grade": grade, "target_property": props, "line": line,
             "start_date": date, "end_date": date, "baseline_start": date, "baseline_end": date,
             "side": {"type": "string", "enum": list(ds.SIDES)}}, ["grade", "target_property"]),
        _fn("trace_defect", "표면결함 발생률을 기간별로 비교하고 원인 인자를 순위화한다.",
            {"defect_type": {"type": "string", "enum": list(DEFECTS)}, "grade": grade, "line": line,
             "start_date": date, "end_date": date}, ["defect_type"]),
        _fn("analyze_coil",
            "특정 코일(시생산·클레임)을 같은 강종·라인·두께의 양산 실적과 비교한다. 슬라브·열연코일·히트번호면 딸린 "
            "냉연코일을 모두 분석. 재질별 양산 대비 z·백분위, 공정인자별 차이(z, 표준조건 대비, 메커니즘), 공통 원인을 반환한다.",
            {"ids": {"type": "string", "description": "번호 (여러 개면 쉼표)"}, "id_type": ids,
             "months": {"type": "integer", "minimum": 1, "maximum": 12, "description": "양산 비교 기간(개월)"}},
            ["ids"]),
        _fn("search_knowledge",
            "냉연강판 지식베이스(공정, 용어, 강종별 강화기구, r값·n값, 결함 원인, 분석 절차)를 검색한다. "
            "grade를 주면 그 강종의 강화기구 절과 공통 인자 절을 항상 포함한다. 결과의 source를 출처로 인용.",
            {"query": {"type": "string"}, "grade": grade,
             "top_k": {"type": "integer", "minimum": 1, "maximum": 5}}, ["query"]),
    ]


TOOL_FUNCTIONS = {
    "query_coils": query_coils,
    "diagnose_distribution": diagnose_distribution,
    "compare_groups": compare_groups,
    "trace_defect": trace_defect,
    "analyze_coil": analyze_coil,
    "search_knowledge": search_knowledge,
}
DASHBOARD_TOOLS = {"get_dashboard_state", "update_dashboard"}


class DashboardContext:
    """에이전트 실행 중 대시보드 상태를 들고 다닌다."""

    def __init__(self, state: dict):
        self.state = dict(state)
        self.changed: dict = {}


def run_tool(name: str, tool_input: dict, ctx: DashboardContext | None = None) -> tuple[str, bool]:
    """도구를 실행하고 (JSON 문자열, is_error)를 반환한다. 예외는 에러 결과로 바꿔 에이전트에 돌려준다."""
    tool_input = tool_input or {}
    try:
        if name == "get_dashboard_state":
            result = ds.describe(ctx.state) if ctx else {"error": "대시보드 없음"}
        elif name == "update_dashboard":
            if ctx is None:
                result = {"error": "대시보드 없음"}
            else:
                ctx.state, applied, errors = ds.apply_update(ctx.state, tool_input)
                ctx.changed.update(applied)
                result = {"applied": applied, "errors": errors, "state": ds.describe(ctx.state)}
        elif name in TOOL_FUNCTIONS:
            result = TOOL_FUNCTIONS[name](**tool_input)
        else:
            result = {"error": f"알 수 없는 도구: {name}"}
    except TypeError as e:
        result = {"error": f"잘못된 입력: {e}"}
    except Exception as e:  # 도구 실패는 대화를 끊지 않고 에이전트에게 알린다
        result = {"error": f"{type(e).__name__}: {e}"}
    return json.dumps(result, ensure_ascii=False, default=str), "error" in result
