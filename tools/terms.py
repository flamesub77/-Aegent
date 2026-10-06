"""화면·인사이트·리포트·에이전트 답변에 쓰는 용어 (prd_v2 R6).

문체(style): "easy" 쉬운 말 · "expert" 금속재료공학 · "stat" 통계(기존 용어).
회사 용어에 맞추려면 이 파일만 고치면 된다.
"""

STYLES = {"easy": "쉬운 말", "expert": "전문가", "stat": "통계"}
DEFAULT_STYLE = "easy"

TERMS = {
    # key: {style: 표현}
    "group_outlier": {"stat": "이탈군", "easy": "문제 코일", "expert": "문제 코일"},
    "ref_outlier": {"stat": "기준군", "easy": "정상 코일", "expert": "정상 코일"},
    "group_period": {"stat": "대상 기간", "easy": "이 기간 코일", "expert": "대상 기간재"},
    "ref_period": {"stat": "기준 기간", "easy": "나머지 기간 코일", "expert": "비교 기간재"},
    "mode_period": {"stat": "기간 비교", "easy": "이 기간 vs 나머지 기간", "expert": "기간 비교"},
    "mode_outlier": {"stat": "이탈군 비교", "easy": "문제 코일 vs 정상 코일", "expert": "문제 코일 vs 정상 코일"},
    "mode_defect": {"stat": "결함 코일 vs 정상 코일", "easy": "결함 난 코일 vs 정상 코일",
                    "expert": "결함재 vs 정상재"},
    "side_label": {"stat": "이탈군 방향", "easy": "문제 코일 기준", "expert": "문제 코일 기준"},
    "side_low": {"stat": "낮은 쪽", "easy": "낮게 나온 코일", "expert": "하한측"},
    "side_high": {"stat": "높은 쪽", "easy": "높게 나온 코일", "expert": "상한측"},
    "side_auto": {"stat": "자동", "easy": "자동", "expert": "자동"},
    "confounder": {"stat": "교란 요인", "easy": "비교 조건 차이", "expert": "비교 조건 차이"},
    "stratify": {"stat": "층별 확인이 필요합니다", "easy": "두께·라인·시편 위치별로 나눠서 다시 비교해 보세요",
                 "expert": "두께·라인·시편 위치별로 나눠 재비교가 필요하다"},
    "effect_size": {"stat": "효과크기", "easy": "차이 크기", "expert": "효과크기"},
    "ranking": {"stat": "기여도 순위", "easy": "원인 가능성 순위", "expert": "원인 후보 순위"},
    "mech_ok": {"stat": "메커니즘 일치", "easy": "야금 원리로 설명됨", "expert": "야금학적 메커니즘 부합"},
    "mech_bad": {"stat": "메커니즘 불일치", "easy": "원리와 반대 방향", "expert": "메커니즘과 상반"},
    "mech_none": {"stat": "통계적 연관만 있음", "easy": "같이 움직이지만 원리로는 설명 안 됨",
                  "expert": "통계적 상관만 존재 (메커니즘 미확인)"},
    "mech_unknown": {"stat": "판단 불가", "easy": "판단하기 어려움", "expert": "판단 불가"},
    "sigma": {"stat": "σ", "easy": "표준편차", "expert": "σ"},
}

JUDGEMENT = {
    "상향 분포": {"stat": "상향 분포", "easy": "평소보다 높게 나옴", "expert": "상향 분포"},
    "하향 분포": {"stat": "하향 분포", "easy": "평소보다 낮게 나옴", "expert": "하향 분포"},
    "상향 경향": {"stat": "상향 경향", "easy": "약간 높은 편", "expert": "상향 경향"},
    "하향 경향": {"stat": "하향 경향", "easy": "약간 낮은 편", "expert": "하향 경향"},
    "정상": {"stat": "정상", "easy": "평소와 비슷함", "expert": "정상 범위"},
    "비교 불가": {"stat": "비교 불가", "easy": "비교할 기간 없음", "expert": "비교 불가"},
}

MECH_KEY = {"일치": "mech_ok", "불일치": "mech_bad", "판단 불가": "mech_unknown", "지식베이스 근거 없음": "mech_none"}
CONFOUNDER_COL = {"thk_band": "두께", "line": "라인", "coil_pos": "시편 위치"}

HELP = {  # 화면 도움말(?)
    "group_outlier": "스펙을 벗어났거나 평소보다 눈에 띄게(표준편차 이상) 높거나 낮은 코일",
    "ref_outlier": "비교 대상이 되는 나머지 코일",
    "confounder": "두 그룹의 두께·라인·시편 위치 비율이 달라서, 차이가 공정 때문이 아니라 구성 때문일 수 있음",
    "effect_size": "두 그룹 평균 차이가 평소 흩어짐(표준편차)의 몇 배인지. 0.5 이상이면 눈여겨볼 차이, 1 이상이면 큰 차이",
    "sigma": "표준편차 = 값이 평소에 흩어지는 정도",
    "judgement": "평균이 나머지 기간 대비 표준편차 1배 이상 움직이면 '평소보다 높게/낮게 나옴'",
}


def t(key: str, style: str = DEFAULT_STYLE) -> str:
    entry = TERMS[key]
    return entry.get(style) or entry["stat"]


def judgement(label: str, style: str = DEFAULT_STYLE) -> str:
    return JUDGEMENT.get(label, {}).get(style, label)


def mechanism(status: str, style: str = DEFAULT_STYLE) -> str:
    return t(MECH_KEY.get(status, "mech_none"), style)


def mode(code: str, style: str = DEFAULT_STYLE) -> str:
    return t(f"mode_{code}", style)


def group_names(mode_code: str, side: str | None, style: str = DEFAULT_STYLE) -> tuple[str, str]:
    """(비교할 그룹 이름, 기준 그룹 이름)."""
    if mode_code == "outlier":
        name = t("group_outlier", style)
        if side in ("low", "high"):
            name += f" ({t('side_' + side, style)})"
        return name, t("ref_outlier", style)
    return t("group_period", style), t("ref_period", style)


def warning_text(w: dict, style: str = DEFAULT_STYLE) -> str:
    """analysis 경고 코드를 문장으로."""
    code = w.get("code")
    if code == "confounder":
        col = CONFOUNDER_COL.get(w["column"], w["column"])
        if style == "stat":
            return f"{col} 구성비가 두 군에서 최대 {w['gap_pp']}%p 다릅니다. 층별 확인이 필요합니다."
        if style == "expert":
            return f"두 그룹의 {col} 구성비가 최대 {w['gap_pp']}%p 달라 {col} 영향이 섞여 있을 수 있다. {t('stratify', style)}."
        return f"두 그룹의 {col} 비율이 최대 {w['gap_pp']}%p 달라요. 차이가 {col} 때문일 수도 있으니 {t('stratify', style)}."
    if code in ("small_group", "small_target"):
        n = w["n"]
        if style == "easy":
            return f"비교한 코일이 {n}개뿐이라 결론을 믿기엔 조금 적어요."
        return f"비교 코일이 {n}개로 적어 판정 신뢰도가 낮습니다."
    if code == "widened":
        return w.get("text", "")
    return str(w)
