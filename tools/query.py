"""query_coils: 조건별 코일 조회 요약."""
from tools.datasource import get_source


def _round(v, n=1):
    return None if v is None or v != v else round(float(v), n)


def query_coils(grade=None, line=None, start_date=None, end_date=None,
                thk_min=None, thk_max=None, coil_pos=None, include_baseline=False) -> dict:
    """강종·라인·기간·두께·코일위치 조건으로 coil을 조회해 건수와 요약을 반환한다.

    include_baseline=True면 같은 조건에서 대상 기간 밖(기준 기간) 요약도 함께 반환한다.
    """
    src = get_source()
    if grade and grade not in src.grade_codes():
        return {"error": f"알 수 없는 강종 코드: {grade}", "available_grades": src.grade_codes()}
    if line and line not in src.lines():
        return {"error": f"알 수 없는 라인: {line}", "available_lines": src.lines()}

    def fetch(start, end):
        df = src.coils
        for col, v in (("grade", grade), ("line", line), ("coil_pos", coil_pos)):
            if v:
                df = df[df[col] == v]
        if start:
            df = df[df["prod_date"] >= start]
        if end:
            df = df[df["prod_date"] <= end]
        if thk_min is not None:
            df = df[df["thk"] >= float(thk_min)]
        if thk_max is not None:
            df = df[df["thk"] <= float(thk_max)]
        return df

    df = fetch(start_date, end_date)
    result = _summarize(df, dict(grade=grade, line=line, start_date=start_date, end_date=end_date,
                                 thk_min=thk_min, thk_max=thk_max, coil_pos=coil_pos))
    if include_baseline and (start_date or end_date):
        everything = fetch(None, None)
        outside = everything[~everything["coil_no"].isin(df["coil_no"])]
        result["baseline"] = _summarize(outside, {"기준": "대상 기간 외 나머지 기간"})
    return result


def _summarize(df, conditions) -> dict:
    conditions = {k: v for k, v in conditions.items() if v is not None}
    if df.empty:
        return {"conditions": conditions, "count": 0, "message": "조건에 맞는 코일이 없습니다."}

    summary = {col: {"mean": _round(df[col].mean(), nd), "std": _round(df[col].std(), nd + 1),
                     "min": _round(df[col].min(), nd), "max": _round(df[col].max(), nd)}
               for col, nd in (("YS", 1), ("TS", 1), ("EL", 1), ("rbar", 3), ("n_value", 3)) if col in df}
    return {
        "conditions": conditions,
        "count": int(len(df)),
        "date_range": [df["prod_date"].min(), df["prod_date"].max()],
        "by_grade": df["grade"].value_counts().to_dict(),
        "by_line": df["line"].value_counts().to_dict(),
        "judge": df["judge"].value_counts().to_dict() if "judge" in df else {},
        "defects": (df.loc[df["defect_type"].fillna("없음") != "없음", "defect_type"].value_counts().to_dict()
                    if "defect_type" in df else {}),
        "trial_coils": int((df["trial_flag"] == "Y").sum()) if "trial_flag" in df else 0,
        "material_summary": summary,
    }
