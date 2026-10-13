"""화면 공통 요소: 배지, 모드·데이터 표시, 단계 이름."""
from tools import terms as T
from tools.datasource import get_source

BADGE = {"상향": "orange", "하향": "blue", "평소보다 높": "orange", "평소보다 낮": "blue", "약간 높": "orange",
         "약간 낮": "blue"}
STEP_LABEL = {
    "get_dashboard_state": "화면 상태 확인",
    "query_coils": "① 대상 정의 · 데이터 조회",
    "diagnose_distribution": "② 분포 진단",
    "compare_groups": "③ 원인 인자 비교 · 비교 조건 차이 확인",
    "trace_defect": "③ 결함 원인 추적",
    "analyze_coil": "③ 단일 코일 분석 (양산 대비)",
    "search_knowledge": "④ 야금 원리 근거 확인 (지식베이스)",
    "update_dashboard": "⑤ 대시보드 갱신",
}


def badge(label: str, style: str | None = None) -> str:
    """판정 배지 (쉬운 말로)."""
    text = T.judgement(label)
    color = next((c for k, c in BADGE.items() if label.startswith(k) or text.startswith(k)), "gray")
    return f":{color}-badge[{text}]"


def mode_badge(mode: str | None = None, api_key: str | None = None) -> str:
    from ui import ai
    if ai.effective() == "offline":
        why = "" if ai.mode() == "offline" else " (AI 키 없음)"
        return f":green-badge[:material/lock: 오프라인 · 외부 전송 없음{why}]"
    return f":blue-badge[:material/smart_toy: AI 모드 · {ai.label()}]"


def source_badge() -> str:
    src = get_source()
    lo, hi = src.date_range()
    icon = ":material/database:" if src.kind == "sample" else ":material/upload_file:"
    return f":blue-badge[{icon} {src.name} · {len(src.coils):,}코일 · {lo} ~ {hi}]"
