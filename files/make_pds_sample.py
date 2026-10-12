"""회사 양식(coil data(pds).xlsx)에 가상 데이터를 채운다.

양식은 1행 헤더만 있는 165열(제강 → 연주 → 열연 → 냉연)이다. 같은 이름의 열(Heat번호, Slab번호 등)이
공정마다 반복되므로 pandas 대신 openpyxl로 열 위치 그대로 쓴다.
값은 샘플 데이터(coil_data.csv)의 냉연코일 1건 = 1행을 기준으로 하고, 샘플에 없는 항목만 그럴듯한 난수로 만든다.

실행: python files/make_pds_sample.py [행 수, 기본 500]
"""
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

HERE = Path(__file__).resolve().parent
XLSX = HERE / "coil data(pds).xlsx"
SEED = 20261012

# 강종별 출강목표·용도·열연재 재질 (가정값)
GRADE_INFO = {
    "IF270_IN": ("IF27", "자동차 내판", (190, 300, 45)),
    "IF340_OUT": ("IF34", "자동차 외판", (250, 370, 38)),
    "BH340_OUT": ("BH34", "자동차 외판", (260, 370, 37)),
    "LC340": ("LC34", "일반 가공용", (280, 380, 35)),
    "LC440R": ("LC44", "구조용", (340, 470, 30)),
    "HSLA590C": ("HS59", "자동차 구조용", (480, 610, 24)),
}
DEFECT_CODE = {"없음": "", "스케일": "D01", "슬리버": "D02", "파우더링": "D03", "덴트": "D04", "에지크랙": "D05"}


def build(n_rows: int = 500) -> int:
    rng = np.random.default_rng(SEED)
    coils = pd.read_csv(HERE / "coil_data.csv")
    spec = pd.read_csv(HERE / "grade_master.csv").set_index("grade")
    df = coils.sample(n=min(n_rows, len(coils)), random_state=SEED).sort_values(["prod_date", "coil_no"])

    wb = openpyxl.load_workbook(XLSX)
    ws = wb.active
    ws.delete_rows(2, ws.max_row)  # 다시 실행해도 같은 결과가 되게 기존 데이터 행을 지운다

    def u(lo, hi, nd=1):
        return round(float(rng.uniform(lo, hi)), nd)

    def nz(v, nd=4):
        return None if pd.isna(v) else round(float(v), nd)

    for _, r in df.iterrows():
        g = spec.loc[r["grade"]]
        aim, use, (hot_ys, hot_ts, hot_el) = GRADE_INFO[r["grade"]]
        cold_day = pd.Timestamp(r["prod_date"])
        hot_day = cold_day - timedelta(days=int(rng.integers(3, 8)))
        cast_day = hot_day - timedelta(days=int(rng.integers(2, 6)))
        steel_day = cast_day - timedelta(hours=int(rng.integers(1, 5)))
        heat, slab, hot, cold = r["heat_no"], r["slab_no"], r["hot_coil_no"], r["coil_no"]
        cast = "CS" + heat[1:7] + f"{int(heat[-2:]) % 10:02d}"
        order, row_no = f"OR{cold_day:%y%m}{rng.integers(1000, 9999)}", int(rng.integers(1, 20))
        tundish = round(1530 + r["superheat"], 1)
        is_if = g["family"] in ("IF", "IF_HS", "BH")

        sn, v, cr, mo, ni, cu = (u(0, 0.003, 4), u(0, 0.004, 4), u(0.01, 0.03, 3),
                                 u(0, 0.005, 4), u(0.005, 0.02, 3), u(0.005, 0.02, 3))
        ceq = r["C"] + r["Mn"] / 6 + (cr + mo + v) / 5 + (ni + cu) / 15
        hot_ys_v = round(hot_ys + rng.normal(0, 12))
        bad = r["judge"] != "합격"
        defect = r["defect_type"] if r["defect_type"] != "없음" else ""
        rbar = (r["r0"] + 2 * r["r45"] + r["r90"]) / 4

        steelmaking = [
            heat, cast, "냉연", "1제강", steel_day.to_pydatetime(), aim, r["grade"], "RH" if is_if else "LF",
            tundish, int(rng.integers(900_000, 1_400_000)),
            nz(r["C"]), nz(r["Mn"], 2), nz(r["Si"], 3), nz(r["P"]), nz(r["S"]), sn,
            nz(r["Al"]), round(r["Al"] + u(0.002, 0.006, 4), 4), nz(r["Nb"]), nz(r["Ti"]), v, cr, mo, ni, cu,
            nz(r["B"]), u(0, 0.0015, 4), nz(r["N"]), u(1.0, 2.5, 1), round(ceq, 3),
            u(1640, 1690), int(rng.integers(400, 900) if is_if else rng.integers(300, 600)), int(rng.integers(1, 3)),
            int(rng.integers(800, 1600)), int(rng.integers(150, 450)), u(3, 8), 0 if is_if else u(25, 50),
            None if is_if else nz(r["S"] + u(0.002, 0.006, 4)), 0 if is_if else int(rng.integers(3000, 9000)),
            None if is_if else u(5, 12), None if is_if else u(3, 8), u(25, 40) if is_if else 0,
            f"{u(1590, 1620, 0):.0f}/{u(1565, 1590, 0):.0f}", u(0.5, 1.5, 2) if is_if else None,
            u(10, 20) if is_if else 0, int(rng.integers(4000, 9000)), int(rng.integers(0, 3000)),
            u(5, 10), None if is_if else u(5, 10),
            round(g["aim_C"] * 0.8, 4), round(g["aim_C"] * 1.2, 4),
        ]
        casting = [
            slab, heat, cast, "냉연", "1제강", f"{rng.integers(1, 3)}CC", int(rng.integers(1, 3)),
            cast_day.to_pydatetime(), r["grade"], aim, 250, int(r["width"] + 50), 250, int(r["width"] + 50),
            round(0.25 * (r["width"] + 50) / 1000 * 10 * 7.85, 2), nz(r["cast_speed"], 2), u(0.01, 0.06, 2),
            "MP-IF" if is_if else "MP-LC", "Soft" if is_if else "Medium", f"P{rng.integers(1, 6)}", u(92, 99),
            "정상", "Bifurcated", tundish, "", "없음", "", "", "", "", "", order, row_no,
        ]
        hot_weight = round(0.25 * (r["width"] + 50) / 1000 * 10 * 7.85 * 0.985, 2)
        hot_rolling = [
            hot, slab, heat, hot_day.to_pydatetime(), "2열연", nz(r["hot_thk"], 2), int(r["width"] + 10),
            hot_weight, r["grade"], aim, aim, order, aim, use,
            row_no, g["std_SRT"], 1080, g["std_FDT"], g["std_CT"], "U" if is_if else "E",
            nz(r["SRT"], 1), u(1060, 1100), nz(r["FDT"], 1), nz(r["CT"], 1), "U" if is_if else "E", "열연-산세",
            f"T{hot[-6:]}", "T", "L", None, None, None, hot_ys_v, round(hot_ts + rng.normal(0, 12)),
            round(hot_el + rng.normal(0, 1.5), 1), "", "", "",
        ]
        cold_rolling = [
            cold, hot, hot, slab, heat, cold_day.to_pydatetime(), "냉연공장", r["line"], nz(r["thk"], 2),
            int(r["width"]), round(hot_weight * u(0.45, 0.97, 2), 2), r["grade"], aim, aim, use,
            order, row_no, nz(r["line_speed"], 1), u(700, 760), nz(r["SS"], 1), u(640, 680), u(450, 500),
            nz(r["OA"], 1) if pd.notna(r["OA"]) else u(380, 420), u(400, 450), nz(r["SPM"], 2), r["coil_pos"],
            "L", f"JIS{rng.integers(5, 6)}", "JIS 5호", f"{g['ys_min']:.0f}~{g['ys_max']:.0f}",
            f"{g['ts_min']:.0f}~{g['ts_max']:.0f}", f"{g['el_min']:.0f}↑",
            None if pd.isna(g["n_min"]) else f"{g['n_min']}↑", None if pd.isna(g["bh_min"]) else f"{g['bh_min']:.0f}↑",
            nz(r["YS"], 0), nz(r["TS"], 0), nz(r["EL"], 1), nz(r["n_value"], 3), nz(r["r0"], 2), nz(r["r45"], 2),
            nz(r["r90"], 2), round(rbar, 3), nz(r["BH"], 0),
        ]
        # 열연 블록의 부적합 여부는 냉연 판정을 따른다
        hot_rolling[-3:] = ["Y" if bad else "N", defect, DEFECT_CODE.get(r["defect_type"], "D99") if defect else ""]

        row = steelmaking + casting + hot_rolling + cold_rolling
        assert len(row) == ws.max_column, (len(row), ws.max_column)
        ws.append(row)

    for col in ("E", "BG", "CJ"):
        for cell in ws[col][1:]:
            cell.number_format = "yyyy-mm-dd hh:mm"
    for cell in ws["DX"][1:]:
        cell.number_format = "yyyy-mm-dd"
    ws.freeze_panes = "A2"
    wb.save(XLSX)
    return len(df)


if __name__ == "__main__":
    print(f"{build(int(sys.argv[1]) if len(sys.argv) > 1 else 500)}행 작성: {XLSX.name}")
