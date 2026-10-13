"""재질 이상 조기 감시: EWMA · CUSUM (prd_v4 M3).

재질 값을 생산 순서(일자·코일번호)로 놓고, 평균이 서서히 움직이는 것을 스펙을 벗어나기 전에 잡는다.
- 기준(μ₀, σ₀): 보는 기간 직전 base_months개월. 기간을 고르지 않았으면 데이터 처음 base_months개월.
- EWMA: zₜ = λxₜ + (1−λ)zₜ₋₁, 한계 μ₀ ± L·σ₀·√(λ/(2−λ)·(1−(1−λ)²ᵗ))
- CUSUM: C⁺ₜ = max(0, C⁺ₜ₋₁ + (xₜ−μ₀)/σ₀ − k), C⁻ₜ = max(0, C⁻ₜ₋₁ − (xₜ−μ₀)/σ₀ − k). h를 넘으면 경보 (k·h는 σ₀ 단위)
EWMA 경보는 한계 밖이 persist개 점 연속일 때만 센다 (점 하나의 잡음으로 울리는 헛경보를 줄임).
점이 max_points보다 많으면 일평균으로 바꾼다 (σ₀도 일평균 기준).
"""
import numpy as np
import pandas as pd

DEFAULTS = {"lam": 0.2, "L": 3.0, "k": 0.5, "h": 5.0, "base_months": 6, "persist": 3}
# 추천 조건 (prd_v5 T4): ⚙ 고급 설정의 프리셋 버튼
PRESETS = {
    "기본": DEFAULTS,
    "작은 변화도 빨리": {"lam": 0.1, "L": 2.7, "k": 0.25, "h": 4.0, "base_months": 3, "persist": 3},
    "헛경보 줄이기": {"lam": 0.3, "L": 3.0, "k": 0.75, "h": 6.0, "base_months": 12, "persist": 3},
}


def _baseline_window(dates: pd.Series, start, base_months: int):
    first = pd.Timestamp(dates.min())
    if start:
        b_end = pd.Timestamp(start)
        b_start = b_end - pd.DateOffset(months=base_months)
    else:
        b_start, b_end = first, first + pd.DateOffset(months=base_months)
    return b_start, b_end


def monitor(df: pd.DataFrame, prop: str, start=None, end=None, spec=(None, None), lam=0.2, L=3.0, k=0.5, h=5.0,
            base_months: int = 6, max_points: int = 2000, persist: int = 3) -> dict:
    """반환: {points: DataFrame, baseline: {...}, first_alarm: {...}|None, first_spec_out: date|None, lead_days, daily}."""
    d = df.dropna(subset=[prop]).sort_values(["prod_date", "coil_no"])[["prod_date", "coil_no", prop]].copy()
    if len(d) < 10:
        return {"error": f"{prop} 값이 있는 코일이 {len(d)}개뿐이라 감시할 수 없어요."}
    d["date"] = pd.to_datetime(d["prod_date"])
    b_start, b_end = _baseline_window(d["date"], start, base_months)
    view_end = pd.Timestamp(end) if end else d["date"].max()
    d = d[(d["date"] >= b_start) & (d["date"] <= view_end)]
    daily = len(d) > max_points
    if daily:
        d = d.groupby("date")[prop].mean().reset_index()
    base = d[(d["date"] >= b_start) & (d["date"] < b_end)][prop]
    if len(base) < 10:  # 기준 기간에 값이 거의 없으면 보는 범위 전체를 기준으로
        base = d[prop]
    mu, sd = float(base.mean()), float(base.std(ddof=1))
    if not sd or np.isnan(sd):
        return {"error": "기준 기간의 흩어짐이 0이라 감시할 수 없어요."}
    x = d[prop].to_numpy(float)
    n = len(x)
    z = np.empty(n)
    cp, cm = np.empty(n), np.empty(n)
    zp, p, m = mu, 0.0, 0.0
    for i, v in enumerate(x):
        zp = lam * v + (1 - lam) * zp
        z[i] = zp
        u = (v - mu) / sd
        p, m = max(0.0, p + u - k), max(0.0, m - u - k)
        cp[i], cm[i] = p, m
    t = np.arange(1, n + 1)
    width = L * sd * np.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * t)))
    pts = d.assign(ewma=z, ucl=mu + width, lcl=mu - width, cusum_hi=cp, cusum_lo=cm).reset_index(drop=True)
    out_hi, out_lo = pts["ewma"] > pts["ucl"], pts["ewma"] < pts["lcl"]
    run = lambda m: m.groupby((~m).cumsum()).cumsum() >= persist  # noqa: E731  연속 persist개째부터 경보
    pts["ewma_alarm"] = run(out_hi) | run(out_lo)
    pts["cusum_alarm"] = (pts["cusum_hi"] > h) | (pts["cusum_lo"] > h)
    watch = pts["date"] >= (pd.Timestamp(start) if start else b_end)  # 기준 기간 다음부터 경보를 센다
    pts.loc[~watch, ["ewma_alarm", "cusum_alarm"]] = False
    alarms = pts[watch & (pts["ewma_alarm"] | pts["cusum_alarm"])]
    first = None
    if len(alarms):
        a = alarms.iloc[0]
        up = (a["ewma"] > a["ucl"]) or (a["cusum_hi"] > h)
        first = {"date": a["date"].date().isoformat(), "direction": "높게" if up else "낮게",
                 "by": "EWMA" if a["ewma_alarm"] else "CUSUM", "value": round(float(a[prop]), 3)}
    lo, hi = spec
    out_mask = pd.Series(False, index=pts.index)
    if lo is not None:
        out_mask |= pts[prop] < lo
    if hi is not None:
        out_mask |= pts[prop] > hi
    spec_out = pts[watch & out_mask]
    first_out = spec_out.iloc[0]["date"].date().isoformat() if len(spec_out) else None
    lead = None
    if first and first_out:
        lead = (pd.Timestamp(first_out) - pd.Timestamp(first["date"])).days
    return {"points": pts, "prop": prop, "daily": daily, "first_alarm": first, "first_spec_out": first_out,
            "lead_days": lead, "n_alarm": int(len(alarms)),
            "baseline": {"start": b_start.date().isoformat(), "end": (b_end - pd.Timedelta(days=1)).date().isoformat(),
                         "mean": round(mu, 3), "std": round(sd, 4), "n": int(len(base))},
            "params": {"lam": lam, "L": L, "k": k, "h": h, "base_months": base_months, "persist": persist}}
