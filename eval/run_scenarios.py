"""이상 시나리오 S1~S6 평가.

anomaly_scenarios.md의 데모 질문을 에이전트에 넣고, 정답지(anomaly_scenarios.md, answer_key.csv)로 채점한다.
정답지는 이 스크립트에서만 읽는다. 에이전트·도구 코드는 접근하지 않는다.

실행: python -m eval.run_scenarios [S1 S3 ...]
"""
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

import config
from agent.agent import run_agent
from tools import analysis as A
from tools import dashboard_state as ds

OUT_DIR = Path(__file__).resolve().parent
SCENARIO_MD = config.DATA_DIR / "anomaly_scenarios.md"
ANSWER_CSV = config.DATA_DIR / "answer_key.csv"

# 정답지 '주입한 원인' 문구 → coil 컬럼 (앞에 있을수록 우선)
CAUSE_KEYWORDS = [("CT", "CT"), ("균열온도", "SS"), ("SPM", "SPM"), ("고속주조", "cast_speed"),
                  ("주조", "cast_speed"), ("합금화로 온도", "GA_temp"), ("P +", "P")]
ALSO_OK = {"P": {"Mn"}}  # 성분 치우침은 P·Mn을 함께 주입했다
DEFECTS = ["슬리버", "스케일", "산세얼룩", "파우더링", "드로스"]
PRD_TARGETS = {"direction": "6/6", "top1": "5/6 이상", "top3": "6/6", "recall": "80% 이상", "time": "120초 이내"}


def load_scenarios() -> list[dict]:
    rows = []
    for line in SCENARIO_MD.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 6 or not re.fullmatch(r"S\d", cells[0]):
            continue
        sid, target, period, cause, effect, question = cells
        factor = next(col for kw, col in CAUSE_KEYWORDS if kw in cause)
        directions = {p: d for p, d in re.findall(r"(YS|TS|EL)[^,]*?(상향|하향)", effect)}
        defect = next((d for d in DEFECTS if d in effect), None)
        rows.append({"id": sid, "target": target, "period": period, "cause": cause, "effect": effect,
                     "question": question.strip('"'), "factor": factor, "directions": directions,
                     "defect": defect})
    return rows


def _last(calls, name):
    for c in reversed(calls):
        if c.name == name and not c.is_error:
            return c.input, json.loads(c.output)
    return None, None


def _rank(ranking, factor):
    ok = {factor} | ALSO_OK.get(factor, set())
    return next((r["rank"] if "rank" in r else i + 1 for i, r in enumerate(ranking) if r["factor"] in ok), None)


def _group_coils(tool_input, prop=None, defect=False) -> set:
    grade, line = tool_input.get("grade"), tool_input.get("line")
    start, end = tool_input.get("start_date"), tool_input.get("end_date")
    df = A.filter_coils(grade, line)
    if defect:
        target, _ = A.split_period(df, start, end)
        return set(target["coil_no"])
    _, _, group, _ = A.comparison_groups(df, grade, prop, start, end, tool_input.get("baseline_start"),
                                         tool_input.get("baseline_end"), tool_input.get("side", "auto"))
    return set(group["coil_no"])


def grade_one(sc: dict, result, seconds: float, answer: pd.DataFrame) -> dict:
    text = result.text
    truth = set(answer.loc[answer["scenario"] == sc["id"], "coil_no"])
    row = {"id": sc["id"], "question": sc["question"], "expected_factor": sc["factor"], "seconds": round(seconds, 1),
           "tools": [c.name for c in result.tool_calls], "stop_reason": result.stop_reason}

    if sc["defect"]:
        t_in, tr = _last(result.tool_calls, "trace_defect")
        ranking = tr["factor_ranking"] if tr else []
        rate_t, rate_b = (tr or {}).get("rate_target_pct"), (tr or {}).get("rate_baseline_pct")
        row["direction_ok"] = bool(tr and tr["defect_type"] == sc["defect"] and rate_b is not None
                                   and rate_t >= 2 * max(rate_b, 0.01))
        row["direction_detail"] = f"{sc['defect']} {rate_b}% → {rate_t}%" if tr else "trace_defect 미호출"
        row["rank"] = _rank(ranking, sc["factor"]) if tr else None
        top = next((r for r in ranking if r["factor"] == sc["factor"]), None)
        row["mechanism_ok"] = bool(top and top["kb_consistent"])
        row["confounder_ok"] = None  # 결함 추적에는 교란 요인 점검이 없다
        group = _group_coils(t_in, defect=True) if tr else set()
    else:
        d_in, diag = _last(result.tool_calls, "diagnose_distribution")
        # 여러 재질을 비교했으면 시나리오에 방향이 적힌 재질의 비교를 채점한다
        compares = [(c.input, json.loads(c.output)) for c in result.tool_calls
                    if c.name == "compare_groups" and not c.is_error]
        scored = [x for x in compares if x[0].get("target_property") in sc["directions"]]
        c_in, comp = (scored or compares or [(None, None)])[-1]
        prop = (c_in or {}).get("target_property")
        expected = sc["directions"].get(prop)
        judge = diag["properties"].get(prop, {}).get("judgement") if diag and prop else None
        row["direction_ok"] = bool(expected and judge and judge.startswith(expected) and "분포" in judge)
        row["direction_detail"] = f"{prop}: 기대 {expected}, 판정 {judge}"
        ranking = comp["ranking"] if comp else []
        row["rank"] = _rank(ranking, sc["factor"]) if comp else None
        top = next((r for r in ranking if r["factor"] in {sc["factor"]} | ALSO_OK.get(sc["factor"], set())), None)
        row["mechanism_ok"] = bool(top and top["mechanism"]["status"] == "일치"
                                   and re.search(r"knowledge_base|3\.\d", text))
        warns = (comp or {}).get("warnings", [])
        row["confounder_ok"] = bool(comp) and (not warns or bool(re.search(r"교란|구성비|두께|코일\s?위치", text)))
        group = _group_coils(c_in, prop) if comp else set()

    row["top1"] = row["rank"] == 1
    row["top3"] = row["rank"] is not None and row["rank"] <= 3
    row["control_ok"] = bool(re.search(r"조치", text) and re.search(r"점검|목표|관리|복귀|하향|상한|하한", text))
    hit = len(group & truth)
    row["recall"] = round(100 * hit / len(truth), 1) if truth else None
    row["precision"] = round(100 * hit / len(group), 1) if group else None
    row["n_truth"], row["n_group"] = len(truth), len(group)
    row["answer_head"] = text[:400]
    return row


def write_markdown(rows: list[dict], path: Path):
    def mark(v):
        return "-" if v is None else ("O" if v else "X")

    n = len(rows)
    s_dir = sum(r["direction_ok"] for r in rows)
    s_top1 = sum(r["top1"] for r in rows)
    s_top3 = sum(r["top3"] for r in rows)
    recall = sum(r["recall"] or 0 for r in rows) / n
    slowest = max(r["seconds"] for r in rows)
    lines = [
        "# 시나리오 평가 결과",
        "",
        f"모델 `{config.MODEL}` · 추론 강도 `{config.REASONING_EFFORT or '기본'}` · "
        f"{time.strftime('%Y-%m-%d %H:%M')} · `python -m eval.run_scenarios`",
        "",
        "## PRD 3장 성공 지표 대비",
        "",
        "| 지표 | 결과 | 목표 | 달성 |",
        "| --- | --- | --- | --- |",
        f"| 분포 판정 정확도 | {s_dir}/{n} | {PRD_TARGETS['direction']} | {mark(s_dir == n)} |",
        f"| 원인 1순위 적중 | {s_top1}/{n} | {PRD_TARGETS['top1']} | {mark(s_top1 >= n - 1)} |",
        f"| 원인 상위 3위 적중 | {s_top3}/{n} | {PRD_TARGETS['top3']} | {mark(s_top3 == n)} |",
        f"| 코일 단위 재현율 (평균) | {recall:.1f}% | {PRD_TARGETS['recall']} | {mark(recall >= 80)} |",
        f"| 분석 소요 시간 (최대) | {slowest}초 | {PRD_TARGETS['time']} | {mark(slowest <= 120)} |",
        "",
        "## 시나리오별",
        "",
        "| ID | 질문 | 기대 원인 | 순위 | ①분포 | ②원인 3위 내 | ③교란 | ④메커니즘 | ⑤조치 | 재현율 | 정밀도 | 시간(초) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(f"| {r['id']} | {r['question']} | {r['expected_factor']} | {r['rank'] or '-'} | "
                     f"{mark(r['direction_ok'])} | {mark(r['top3'])} | {mark(r['confounder_ok'])} | "
                     f"{mark(r['mechanism_ok'])} | {mark(r['control_ok'])} | {r['recall']}% | {r['precision']}% | "
                     f"{r['seconds']} |")
    lines += ["", "①~⑤는 anomaly_scenarios.md의 평가 기준입니다. ①②와 재현율은 도구 출력으로 채점하고, "
              "③④⑤는 답변 문구를 보는 근사 채점입니다. ③은 결함 시나리오에 해당하지 않아 '-'입니다.", "",
              "재현율 = 정답 코일 중 에이전트 비교군에 포함된 비율, 정밀도 = 비교군 코일 중 정답 코일 비율.", "", "## 판정 상세", ""]
    for r in rows:
        lines += [f"### {r['id']} · {r['direction_detail']}", "",
                  f"도구 호출: {' → '.join(r['tools'])}", "", "```text", r["answer_head"], "```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(ids=None):
    answer = pd.read_csv(ANSWER_CSV, encoding="utf-8-sig")
    scenarios = [s for s in load_scenarios() if not ids or s["id"] in ids]
    rows = []
    for sc in scenarios:
        print(f"[{sc['id']}] {sc['question']}", flush=True)
        t0 = time.time()
        result = run_agent(sc["question"], ds.defaults())
        row = grade_one(sc, result, time.time() - t0, answer)
        print(f"   rank={row['rank']} dir={row['direction_ok']} recall={row['recall']}% {row['seconds']}s", flush=True)
        rows.append(row)
    (OUT_DIR / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(rows, OUT_DIR / "results.md")
    print(f"저장: {OUT_DIR / 'results.md'}")
    return rows


if __name__ == "__main__":
    main(sys.argv[1:] or None)
