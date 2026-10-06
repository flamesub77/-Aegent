"""
자동차 냉연강판 가상 코일 데이터 생성기
- 강종 마스터(스펙/성분/표준 공정조건)와 코일 단위 공정·재질·표면결함 데이터를 생성
- 야금학적 경향(권취온도, 소둔온도, 압하율, 성분, SPM 등)을 선형/비선형 민감도로 반영
- 원인분석 에이전트 검증용 이상 시나리오(S1~S6)를 특정 기간에 주입
- v2: 계보(slab_no, hot_coil_no), 시생산 구분(trial_flag), 성형성(r0·r45·r90·n) 컬럼을 별도 난수로 추가

※ 모든 스펙·표준조건은 '이상적 가정값'이며 실제 사내 기준으로 추후 수정 필요
"""
import sqlite3
import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
N_COILS = 4000
START, END = "2026-01-01", "2026-06-30"

# ---------------------------------------------------------------------------
# 1. 강종 마스터 (가정값)
# ---------------------------------------------------------------------------
GRADES = {
    # code: 설명, 스펙, 목표 성분, 표준 공정, 라인 비중
    "IF270_IN": dict(
        name="극저탄 내판 (Ti 단독 IF, 270E급)", family="IF",
        ys=(120, 190), ts=(270, 350), el_min=44, bh_min=None,
        chem=dict(C=0.0020, Mn=0.10, Si=0.010, P=0.010, S=0.006, N=0.0025, Al=0.035, Ti=0.060, Nb=0.000, B=0.0000),
        std=dict(SRT=1200, FDT=920, CT=700, RED=80, SS=830, OA=None, GA=520, SPM=0.8),
        base=dict(YS=152, TS=298, EL=48.5), lines={"CAL": 0.4, "CGL_GA": 0.6}, share=0.25),
    "IF340_OUT": dict(
        name="고강도 극저탄 외판 (Ti-Nb 복합 P첨가 IF, 340급)", family="IF_HS",
        ys=(175, 245), ts=(340, 420), el_min=36, bh_min=None,
        chem=dict(C=0.0025, Mn=0.45, Si=0.020, P=0.045, S=0.006, N=0.0025, Al=0.035, Ti=0.020, Nb=0.012, B=0.0006),
        std=dict(SRT=1200, FDT=910, CT=680, RED=78, SS=840, OA=None, GA=520, SPM=0.8),
        base=dict(YS=205, TS=372, EL=39.5), lines={"CGL_GA": 1.0}, share=0.18),
    "BH340_OUT": dict(
        name="BH 외판 (극저탄 Nb 부분안정화 BH, 340급)", family="BH",
        ys=(185, 265), ts=(340, 420), el_min=34, bh_min=30,
        chem=dict(C=0.0025, Mn=0.40, Si=0.020, P=0.040, S=0.006, N=0.0025, Al=0.035, Ti=0.000, Nb=0.008, B=0.0005),
        std=dict(SRT=1200, FDT=910, CT=650, RED=76, SS=840, OA=None, GA=520, SPM=1.0),
        base=dict(YS=222, TS=365, EL=37.5), lines={"CAL": 0.3, "CGL_GA": 0.7}, share=0.15),
    "LC340": dict(
        name="저탄 고용강화강 340급 (Ti/Nb 미첨가)", family="LC",
        ys=(175, 275), ts=(340, 440), el_min=34, bh_min=None,
        chem=dict(C=0.040, Mn=0.35, Si=0.020, P=0.030, S=0.008, N=0.0035, Al=0.040, Ti=0.000, Nb=0.000, B=0.0000),
        std=dict(SRT=1200, FDT=890, CT=680, RED=70, SS=780, OA=400, GA=520, SPM=1.2),
        base=dict(YS=222, TS=368, EL=38.0), lines={"CAL": 1.0}, share=0.15),
    "LC440R": dict(
        name="저탄 고용강화강 440급 (Ti/Nb 미첨가)", family="LC",
        ys=(245, 365), ts=(440, 540), el_min=29, bh_min=None,
        chem=dict(C=0.070, Mn=1.20, Si=0.250, P=0.060, S=0.006, N=0.0035, Al=0.040, Ti=0.000, Nb=0.000, B=0.0000),
        std=dict(SRT=1200, FDT=880, CT=660, RED=65, SS=800, OA=400, GA=520, SPM=1.0),
        base=dict(YS=305, TS=490, EL=32.5), lines={"CAL": 0.6, "CGL_GA": 0.4}, share=0.12),
    "HSLA590C": dict(
        name="석출경화강 590급 (Nb 단독계 HSLA)", family="HSLA",
        ys=(440, 600), ts=(590, 710), el_min=20, bh_min=None,
        chem=dict(C=0.080, Mn=1.50, Si=0.300, P=0.015, S=0.004, N=0.0040, Al=0.040, Ti=0.000, Nb=0.035, B=0.0000),
        std=dict(SRT=1230, FDT=880, CT=580, RED=60, SS=800, OA=400, GA=520, SPM=1.0),
        base=dict(YS=492, TS=640, EL=23.5), lines={"CAL": 0.6, "CGL_GA": 0.4}, share=0.15),
}

CHEM_SD = dict(C=0.0004, Mn=0.02, Si=0.008, P=0.003, S=0.001, N=0.0004, Al=0.005, Ti=0.003, Nb=0.002, B=0.0001)
CHEM_SD_LC = dict(C=0.004, Mn=0.03, Si=0.015, P=0.004)  # 저탄·HSLA는 C/Mn 편차 더 큼


def pick_grade(n):
    codes = list(GRADES)
    p = np.array([GRADES[c]["share"] for c in codes]); p /= p.sum()
    return RNG.choice(codes, size=n, p=p)


# ---------------------------------------------------------------------------
# 2. 공정 데이터 생성
# ---------------------------------------------------------------------------
def make_coils():
    dates = pd.to_datetime(RNG.uniform(pd.Timestamp(START).value, pd.Timestamp(END).value, N_COILS)).normalize()
    df = pd.DataFrame({"prod_date": dates, "grade": pick_grade(N_COILS)}).sort_values("prod_date").reset_index(drop=True)
    df["coil_no"] = [f"C{d:%y%m}{i:05d}" for i, d in enumerate(df["prod_date"])]
    df["heat_no"] = [f"H{d:%y%m}{i // 4:04d}" for i, d in enumerate(df["prod_date"])]  # 4코일/히트 가정

    rows = []
    for _, r in df.iterrows():
        g = GRADES[r.grade]; s = g["std"]
        line = RNG.choice(list(g["lines"]), p=list(g["lines"].values()))
        d = {}
        # 성분
        for el, tgt in g["chem"].items():
            sd = CHEM_SD_LC.get(el, CHEM_SD[el]) if g["family"] in ("LC", "HSLA") else CHEM_SD[el]
            d[el] = max(0.0, RNG.normal(tgt, sd)) if tgt > 0 else 0.0
        # 연주
        d["cast_speed"] = RNG.normal(1.40, 0.08)           # m/min
        d["superheat"] = RNG.normal(28, 4)                  # ℃
        # 열연
        d["SRT"] = RNG.normal(s["SRT"], 10)
        d["FDT"] = RNG.normal(s["FDT"], 8)
        d["CT"] = RNG.normal(s["CT"], 10)
        d["descale_press"] = RNG.normal(180, 8)             # bar
        # 치수
        d["thk"] = round(float(RNG.choice([0.65, 0.7, 0.8, 1.0, 1.2, 1.4, 1.6, 2.0],
                                          p=[.08, .17, .25, .2, .12, .08, .06, .04])), 2)
        d["width"] = round(RNG.uniform(1000, 1850) / 10) * 10
        d["RED"] = RNG.normal(s["RED"], 2.0)                # 냉간압하율 %
        d["hot_thk"] = d["thk"] / (1 - d["RED"] / 100)
        # 산세
        d["pickle_speed"] = RNG.normal(180, 12)             # mpm
        d["hcl_conc"] = RNG.normal(12, 1.0)                  # %
        # 소둔
        d["SS"] = RNG.normal(s["SS"] - (10 if line == "CGL_GA" else 0), 6)
        d["line_speed"] = RNG.normal(250 if line == "CAL" else 150, 15) * (1.0 / max(d["thk"], 0.6)) ** 0.3
        d["OA"] = RNG.normal(s["OA"], 8) if (line == "CAL" and s["OA"]) else np.nan
        d["pot_temp"] = RNG.normal(460, 3) if line == "CGL_GA" else np.nan
        d["GA_temp"] = RNG.normal(s["GA"], 6) if line == "CGL_GA" else np.nan
        d["SPM"] = RNG.normal(s["SPM"], 0.08)
        d["line"] = line
        d["coil_pos"] = RNG.choice(["T", "M", "B"], p=[.2, .6, .2])   # 시험 위치
        rows.append(d)
    return pd.concat([df, pd.DataFrame(rows)], axis=1)


# ---------------------------------------------------------------------------
# 3. 이상 시나리오 주입 (정답지는 anomaly_scenarios.md 참조)
# ---------------------------------------------------------------------------
def inject(df):
    df["scenario"] = ""
    m = lambda g, s, e, line=None: (df.grade == g) & df.prod_date.between(s, e) & ((df.line == line) if line else True)

    # S1: 590C CAL, 5월 ROT 냉각 이상 → CT 상향 +45℃ → YS/TS 하향
    k = m("HSLA590C", "2026-05-01", "2026-05-31", "CAL")
    df.loc[k, "CT"] += RNG.normal(45, 6, k.sum()); df.loc[k, "scenario"] = "S1"
    # S2: IF340 외판 CGL, 3월 중순 소둔로 버너 이상 → 균열온도 -45℃ (일부 미재결정) → YS 상향, EL 하향
    k = m("IF340_OUT", "2026-03-10", "2026-03-31")
    df.loc[k, "SS"] -= RNG.normal(45, 6, k.sum()); df.loc[k, "scenario"] = "S2"
    # S3: 440R, 2월 제강 성분 상한 치우침 (P +0.04%, Mn +0.15%) → TS 상향, 상한 초과
    k = m("LC440R", "2026-02-01", "2026-02-28")
    df.loc[k, "Mn"] += RNG.normal(0.15, 0.02, k.sum()); df.loc[k, "P"] += RNG.normal(0.04, 0.005, k.sum()); df.loc[k, "scenario"] = "S3"
    # S4: LC340 CAL, 4월 SPM 설정 변경 → 조질 연신율 과다(+0.8%) → YS 상향
    k = m("LC340", "2026-04-01", "2026-04-30")
    df.loc[k, "SPM"] += RNG.normal(0.8, 0.1, k.sum()); df.loc[k, "scenario"] = "S4"
    # S5: IF 내판, 1월 연주 고속주조(+0.25 m/min) → 슬리버/개재물 결함 증가
    k = m("IF270_IN", "2026-01-05", "2026-01-31")
    df.loc[k, "cast_speed"] += RNG.normal(0.25, 0.04, k.sum()); df.loc[k, "scenario"] = "S5"
    # S6: GA 전 강종, 6월 합금화로 온도 과다(+25℃) → 파우더링 증가
    k = df.prod_date.between("2026-06-01", "2026-06-30") & (df.line == "CGL_GA")
    df.loc[k, "GA_temp"] += RNG.normal(25, 4, k.sum())
    df.loc[k, "scenario"] = df.loc[k, "scenario"].where(df.loc[k, "scenario"] != "", "S6")
    return df


# ---------------------------------------------------------------------------
# 4. 재질 모델 (강종 계열별 민감도)
# ---------------------------------------------------------------------------
def properties(df):
    YS, TS, EL, BH = [], [], [], []
    for _, r in df.iterrows():
        g = GRADES[r.grade]; s = g["std"]; c = g["chem"]; f = g["family"]; b = g["base"]
        dCT, dSS, dRED, dSPM = r.CT - s["CT"], r.SS - (s["SS"] - (10 if r.line == "CGL_GA" else 0)), r.RED - s["RED"], r.SPM - s["SPM"]
        dSRT, dthk = r.SRT - s["SRT"], r.thk - 1.0
        ys, ts, el, bh = b["YS"], b["TS"], b["EL"], np.nan

        # 공통 고용강화 (Mn, Si, P)
        ys += 30 * (r.Mn - c["Mn"]) + 80 * (r.Si - c["Si"]) + 600 * (r.P - c["P"])
        ts += 60 * (r.Mn - c["Mn"]) + 90 * (r.Si - c["Si"]) + 750 * (r.P - c["P"])
        el += -4 * (r.Mn - c["Mn"]) - 80 * (r.P - c["P"])

        # 코일 선후단: 권취 시 과냉 → 실제 CT 낮음
        if r.coil_pos in ("T", "B"):
            dCT -= 15

        if f in ("IF", "IF_HS", "BH"):
            ys += -0.20 * dCT - 0.30 * dSS - 0.6 * dRED
            ts += -0.08 * dCT - 0.15 * dSS - 0.2 * dRED
            el += 0.030 * dCT + 0.045 * dSS + 0.12 * dRED
            if f == "IF_HS":          # 고CT에서 FeTiP 석출로 고용 P 소모
                ys += -0.10 * max(dCT, 0); ts += -0.12 * max(dCT, 0)
            if f in ("IF", "IF_HS"):  # 유효 Ti 부족 → 고용 C 잔존 → YS↑ EL↓
                ti_eff = r.Ti - 3.42 * r.N - 1.5 * r.S + (7.74 * r.Nb if r.Nb > 0 else 0) * 0.5
                if ti_eff < 4 * r.C:
                    ys += 15; el -= 1.5
            if r.SS < 800:            # 소둔온도 부족 → 부분 미재결정
                ys += 0.8 * (800 - r.SS); el -= 0.10 * (800 - r.SS)
            if f == "BH":
                bh = 38 + 0.25 * dSS - 0.15 * dCT + 3000 * (r.C - c["C"]) + RNG.normal(0, 3)
        elif f == "LC":
            ys += -0.30 * dCT - 0.25 * dSS - 0.3 * dRED
            ts += -0.15 * dCT - 0.15 * dSS - 0.1 * dRED
            el += 0.040 * dCT + 0.040 * dSS + 0.05 * dRED
            ys += 400 * (r.C - c["C"]); ts += 500 * (r.C - c["C"]); el -= 60 * (r.C - c["C"])
            if not np.isnan(r.OA):    # 과시효 부족 → 고용 C 잔존
                ys += -0.10 * (r.OA - s["OA"])
        elif f == "HSLA":
            ys += -0.85 * dCT - 0.45 * dSS + 0.15 * dSRT + 1500 * (r.Nb - c["Nb"])
            ts += -0.55 * dCT - 0.30 * dSS + 0.10 * dSRT + 900 * (r.Nb - c["Nb"]) + 400 * (r.C - c["C"])
            el += 0.030 * dCT + 0.030 * dSS
            if r.SS < 770:            # 미재결정 잔존
                ys += 35; el -= 3.5

        # 조질압연: YPE 제거 이후 추가 연신은 가공경화
        ys += 22 * dSPM; el -= 1.2 * dSPM
        # 두께: 박물일수록 연신율 낮음
        el += 3.0 * dthk
        # GA 재가열 열이력 (소폭)
        if r.line == "CGL_GA":
            ys += 4; el -= 0.4

        YS.append(ys + RNG.normal(0, 7 if f != "HSLA" else 12))
        TS.append(ts + RNG.normal(0, 5 if f != "HSLA" else 9))
        EL.append(el + RNG.normal(0, 0.9))
        BH.append(bh)
    df["YS"], df["TS"], df["EL"], df["BH"] = np.round(YS, 0), np.round(TS, 0), np.round(EL, 1), np.round(BH, 0)
    df["YR"] = (df.YS / df.TS).round(3)
    return df


# ---------------------------------------------------------------------------
# 5. 표면결함 모델 (로지스틱)
# ---------------------------------------------------------------------------
def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def defects(df):
    types, sev = [], []
    for _, r in df.iterrows():
        g = GRADES[r.grade]
        outer = g["family"] in ("IF_HS", "BH")  # 외판은 결함 판정 엄격
        p = {
            "슬리버": sigmoid(-5.0 + 9 * (r.cast_speed - 1.40) + 60 * (r.Al - 0.035) + (0.6 if outer else 0)),
            "스케일": sigmoid(-5.5 + 0.06 * (r.SRT - 1200) - 0.08 * (r.descale_press - 180)),
            "산세얼룩": sigmoid(-6.0 + 0.05 * (r.pickle_speed - 180) - 0.8 * (r.hcl_conc - 12)),
            "파우더링": sigmoid(-6.0 + 0.16 * (r.GA_temp - 520)) if r.line == "CGL_GA" else 0,
            "드로스": sigmoid(-6.0 + 0.4 * abs(r.pot_temp - 460)) if r.line == "CGL_GA" else 0,
        }
        hit = [k for k, v in p.items() if RNG.random() < v]
        if hit:
            t = max(hit, key=lambda k: p[k])
            types.append(t); sev.append(RNG.choice(["경", "중", "중대"], p=[.6, .3, .1]))
        else:
            types.append("없음"); sev.append("")
    df["defect_type"], df["defect_grade"] = types, sev
    return df


# ---------------------------------------------------------------------------
# 6. 판정 및 저장
# ---------------------------------------------------------------------------
def judge(df):
    res = []
    for _, r in df.iterrows():
        g = GRADES[r.grade]; ng = []
        if r.YS < g["ys"][0]: ng.append("YS미달")
        if r.YS > g["ys"][1]: ng.append("YS초과")
        if r.TS < g["ts"][0]: ng.append("TS미달")
        if r.TS > g["ts"][1]: ng.append("TS초과")
        if r.EL < g["el_min"]: ng.append("EL미달")
        if g["bh_min"] and r.BH < g["bh_min"]: ng.append("BH미달")
        if r.defect_grade in ("중", "중대"): ng.append("표면결함")
        res.append(",".join(ng) if ng else "합격")
    df["judge"] = res
    return df


def master_table():
    rows = []
    for code, g in GRADES.items():
        row = dict(grade=code, grade_name=g["name"], family=g["family"],
                   ys_min=g["ys"][0], ys_max=g["ys"][1], ts_min=g["ts"][0], ts_max=g["ts"][1],
                   el_min=g["el_min"], bh_min=g["bh_min"], lines="/".join(g["lines"]))
        row.update({f"aim_{k}": v for k, v in g["chem"].items()})
        row.update({f"std_{k}": v for k, v in g["std"].items()})
        row.update(FORM_SPEC.get(code, dict(rbar_min=None, n_min=None, dr_max=None)))
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 7. v2 확장 컬럼 (별도 난수 → 기존 컬럼·시나리오 값은 v1과 동일)
#    계보(slab_no, hot_coil_no), 시생산 구분(trial_flag), 성형성(r0, r45, r90, n_value)
# ---------------------------------------------------------------------------
RNG2 = np.random.default_rng(2026)

# 강종별 성형성 기준값: r̄, Δr, r90-r0 반폭, n
FORM_BASE = {
    "IF270_IN": dict(rbar=2.00, dr=0.45, a=0.25, n=0.240),
    "IF340_OUT": dict(rbar=1.75, dr=0.40, a=0.22, n=0.215),
    "BH340_OUT": dict(rbar=1.65, dr=0.35, a=0.20, n=0.210),
    "LC340": dict(rbar=1.35, dr=0.30, a=0.15, n=0.205),
    "LC440R": dict(rbar=1.15, dr=0.25, a=0.12, n=0.185),
    "HSLA590C": dict(rbar=0.95, dr=0.20, a=0.10, n=0.150),
}
FORM_SPEC = {  # grade_master 성형성 스펙 (가정값, 없으면 분포만 표시)
    "IF270_IN": dict(rbar_min=1.8, n_min=0.22, dr_max=0.70),
    "IF340_OUT": dict(rbar_min=1.5, n_min=0.19, dr_max=None),
    "BH340_OUT": dict(rbar_min=1.4, n_min=0.19, dr_max=None),
}
# 시생산 코일로 표시할 '조건을 바꾼 인자' 후보 (계열별, 인자, 방향)
TRIAL_FACTORS = {"IF": [("SS", +1), ("RED", +1)], "IF_HS": [("SS", -1), ("CT", +1)], "BH": [("SS", +1), ("CT", -1)],
                 "LC": [("SPM", +1), ("CT", +1)], "HSLA": [("CT", +1), ("SRT", -1)]}


def formability(df):
    """r값·n값: knowledge_base 3.7 방향 (압하율·IF강 CT/SS↑ → r̄↑, 고용원소↑ → r̄·n↓, 미재결정 → r̄ 급감)."""
    r0s, r45s, r90s, ns = [], [], [], []
    for _, r in df.iterrows():
        g = GRADES[r.grade]; s = g["std"]; c = g["chem"]; f = g["family"]; b = FORM_BASE[r.grade]
        dCT, dRED, dSPM = r.CT - s["CT"], r.RED - s["RED"], r.SPM - s["SPM"]
        dSS = r.SS - (s["SS"] - (10 if r.line == "CGL_GA" else 0))
        rbar, dr, n = b["rbar"], b["dr"], b["n"]
        rbar += 0.015 * dRED - 0.6 * (r.Mn - c["Mn"]) - 3.0 * (r.P - c["P"])
        n += -0.03 * (r.Mn - c["Mn"]) - 0.3 * (r.P - c["P"]) - 0.012 * dSPM
        if f in ("IF", "IF_HS", "BH"):
            rbar += 0.003 * dCT + 0.004 * dSS - 40 * (r.C - c["C"])
            n += 0.0002 * dCT + 0.0003 * dSS
            if r.SS < 800:   # 부분 미재결정
                rbar -= 0.015 * (800 - r.SS); dr += 0.008 * (800 - r.SS); n -= 0.0012 * (800 - r.SS)
        else:
            rbar += 0.002 * dSS - 1.5 * (r.C - c["C"])
            n += -0.2 * (r.C - c["C"]) + 0.0001 * dSS
        rbar += RNG2.normal(0, 0.05); dr += RNG2.normal(0, 0.05); n += RNG2.normal(0, 0.005)
        a = b["a"] + RNG2.normal(0, 0.04)
        r45 = rbar - dr / 2
        r0s.append(rbar + dr / 2 - a); r45s.append(r45); r90s.append(rbar + dr / 2 + a); ns.append(n)
    df["r0"], df["r45"], df["r90"] = np.round(r0s, 2), np.round(r45s, 2), np.round(r90s, 2)
    df["n_value"] = np.round(ns, 3)
    return df


def lineage(df):
    """슬라브 1 → 열연코일 1 → 냉연코일 1~2 (같은 강종·라인·두께 연속 코일 일부를 분할재로 묶음)."""
    slab, hot = [], []
    order = df.sort_values(["prod_date", "coil_no"]).index
    prev, idx = None, 0
    for i in order:
        r = df.loc[i]
        key = (r.grade, r.line, r.thk)
        if prev is not None and prev[0] == key and not prev[1] and RNG2.random() < 0.25:
            prev = (key, True)           # 직전 코일과 같은 열연코일에서 분할
        else:
            idx += 1
            prev = (key, False)
        tag = f"{pd.Timestamp(r.prod_date):%y%m}{idx:05d}"
        slab.append((i, f"SL{tag}")); hot.append((i, f"HC{tag}"))
    df["slab_no"] = pd.Series(dict(slab)); df["hot_coil_no"] = pd.Series(dict(hot))
    return df


def trials(df):
    """강종별 시생산 코일 표시. 시나리오 외 코일 중 '바꾼 인자'가 실제로 극단인 코일을 고른다 (기존 값 불변)."""
    df["trial_flag"] = "N"
    key = []
    for grade, g in GRADES.items():
        cand = df[(df.grade == grade) & (df.scenario == "") & (df.prod_date >= "2026-04-01")]
        for factor, sign in TRIAL_FACTORS[g["family"]]:
            z = sign * (cand[factor] - cand[factor].mean()) / cand[factor].std()
            pick = z[~z.index.isin(df.index[df.trial_flag == "Y"])].nlargest(3).index
            df.loc[pick, "trial_flag"] = "Y"
            key += [{"coil_no": df.at[i, "coil_no"], "grade": grade, "changed_factor": factor,
                     "direction": "+" if sign > 0 else "-"} for i in pick]
        normal = cand[~cand.index.isin(df.index[df.trial_flag == "Y"])].sample(2, random_state=7).index
        df.loc[normal, "trial_flag"] = "Y"
        key += [{"coil_no": df.at[i, "coil_no"], "grade": grade, "changed_factor": "", "direction": ""}
                for i in normal]
    return df, pd.DataFrame(key)


if __name__ == "__main__":
    df = judge(defects(properties(inject(make_coils()))))
    df = formability(df)
    df = lineage(df)
    df, trial_key = trials(df)
    num = df.select_dtypes("number").columns
    for col in ["C", "N", "Ti", "Nb", "B", "S", "P", "Al"]:
        df[col] = df[col].round(4)
    for col in ["Mn", "Si", "cast_speed", "SPM", "hot_thk"]:
        df[col] = df[col].round(2)
    for col in ["superheat", "SRT", "FDT", "CT", "descale_press", "RED", "pickle_speed", "hcl_conc",
                "SS", "line_speed", "OA", "pot_temp", "GA_temp"]:
        df[col] = df[col].round(1)
    df["prod_date"] = df["prod_date"].dt.strftime("%Y-%m-%d")

    cols = ["coil_no", "heat_no", "prod_date", "grade", "line", "C", "Mn", "Si", "P", "S", "N", "Al", "Ti", "Nb", "B",
            "cast_speed", "superheat", "SRT", "FDT", "CT", "descale_press", "hot_thk", "pickle_speed", "hcl_conc",
            "RED", "thk", "width", "SS", "line_speed", "OA", "pot_temp", "GA_temp", "SPM", "coil_pos",
            "YS", "TS", "EL", "YR", "BH", "defect_type", "defect_grade", "judge",
            "slab_no", "hot_coil_no", "trial_flag", "r0", "r45", "r90", "n_value", "scenario"]
    df = df[cols]
    master = master_table()

    # 에이전트용 데이터에는 정답(scenario) 컬럼 제외
    agent_df = df.drop(columns="scenario")
    agent_df.to_csv("coil_data.csv", index=False, encoding="utf-8-sig")
    master.to_csv("grade_master.csv", index=False, encoding="utf-8-sig")
    df[["coil_no", "scenario"]].to_csv("answer_key.csv", index=False, encoding="utf-8-sig")
    trial_key.to_csv("trial_key.csv", index=False, encoding="utf-8-sig")   # 시생산 평가용 정답 (비공개)
    agent_df.to_excel("coil_data.xlsx", index=False)

    with sqlite3.connect("steel.db") as con:
        agent_df.to_sql("coil", con, if_exists="replace", index=False)
        master.to_sql("grade_master", con, if_exists="replace", index=False)

    print(f"생성 완료: {len(df)} 코일")
    print(df.groupby("grade")["judge"].apply(lambda s: (s != "합격").mean()).round(3))
