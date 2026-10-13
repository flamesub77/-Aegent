"""원인 순위 모델별 S1~S6 적중 비교 (prd_v3 F1). API 없이 오프라인 해석기로 조건을 잡고 분석 엔진만 돌린다.

재질 시나리오(S1~S4)는 모델마다 1순위·3위 안 적중과 계산 시간을, 결함 시나리오(S5~S6)는 결함 추적 결과를 남긴다.
정답은 eval/run_scenarios.py와 같은 방식으로 anomaly_scenarios.md에서 읽는다 (평가 코드만 정답을 읽는다).

실행: python -m eval.model_compare  →  eval/model_results.md
"""
import time
from pathlib import Path

from agent import offline
from eval.run_scenarios import ALSO_OK, load_scenarios
from tools import analysis as A
from tools import dashboard_state as ds
from tools.ranking import MODELS

OUT = Path(__file__).resolve().parent / "model_results.md"


def hit_rank(ranking, factor):
    ok = {factor} | ALSO_OK.get(factor, set())
    return next((r["rank"] for r in ranking if r["factor"] in ok), None)


def main():
    rows, summary = [], {m: {"top1": 0, "top3": 0, "n": 0, "sec": 0.0} for m in MODELS}
    for sc in load_scenarios():
        changes, _ = offline.parse_question(sc["question"], ds.defaults())
        state, _, _ = ds.apply_update(ds.defaults(), changes)
        args = ds.analysis_args(state)
        if sc["defect"]:
            r = A.defect_trace(sc["defect"], changes.get("grade"), args["line"], args["start"], args["end"])
            top = [f["factor"] for f in r.get("factor_ranking", [])]
            rank = top.index(sc["factor"]) + 1 if sc["factor"] in top else None
            rows.append(f"| {sc['id']} | {sc['question']} | {sc['factor']} | 결함 추적 | {rank or '-'} | - |")
            continue
        for m in MODELS:
            t = time.time()
            c = A.compare(args["grade"], state["prop"], args["line"], args["start"], args["end"],
                          side=state["side"], model=m, top_n=20)
            sec = time.time() - t
            rank = hit_rank(c["all_factors"], sc["factor"])
            s = summary[m]
            s["n"] += 1
            s["top1"] += rank == 1
            s["top3"] += bool(rank and rank <= 3)
            s["sec"] = max(s["sec"], sec)
            top3 = ", ".join(r["factor"] for r in c["all_factors"][:3])
            rows.append(f"| {sc['id']} | {sc['question']} | {sc['factor']} | {MODELS[m]} | {rank or '-'} | {top3} |")
    lines = ["# 원인 순위 모델별 시나리오 적중", "", "`python -m eval.model_compare` · 오프라인 해석기로 조건 인식, 분석 엔진만 실행", "",
             "## 요약 (재질 시나리오 S1~S4)", "", "| 모델 | 1순위 적중 | 3위 안 적중 | 최대 계산 시간(초) |", "| --- | --- | --- | --- |",
             *[f"| {MODELS[m]} | {v['top1']}/{v['n']} | {v['top3']}/{v['n']} | {v['sec']:.1f} |" for m, v in summary.items()],
             "", "## 시나리오별", "", "| ID | 질문 | 정답 인자 | 모델 | 정답 순위 | 상위 3개 |", "| --- | --- | --- | --- | --- | --- |",
             *rows, ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:12]))


if __name__ == "__main__":
    main()
