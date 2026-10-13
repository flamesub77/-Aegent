"""원인 가능성 순위 모델 (prd_v3 F1).

모든 모델은 analysis.compare()가 만든 인자별 행(차이·효과크기·야금 원리)에 점수(score)만 다시 매긴다.
그래서 그래프·해석·에이전트는 모델과 상관없이 같은 형식을 쓴다.
- 차이 크기: 문제 코일 vs 정상 코일 평균 차이 ÷ 표준편차 (v2 방식, 기본)
- 상관: 재질값과 인자의 순위상관 (Spearman)
- 랜덤포레스트 / 그래디언트 부스팅: 재질값 예측 모델의 순열 중요도
- 다중회귀: Lasso 표준화 계수
트리·회귀 점수에는 방향이 없어서, 방향은 문제 코일 − 정상 코일 평균 차이의 부호로 붙인다.
scikit-learn은 이 모델을 고를 때만 불러온다 (없으면 차이 크기로 돌아간다).
"""
import numpy as np
import pandas as pd

MODELS = {"effect": "차이 크기", "spearman": "상관", "rf": "랜덤포레스트", "gbm": "그래디언트 부스팅", "lasso": "다중회귀"}
DEFAULT = "effect"
HELP = {
    "effect": "두 그룹(문제 코일 vs 정상 코일) 평균이 평소 흩어짐의 몇 배만큼 다른지",
    "spearman": "재질값과 같이 오르내리는 정도 (-1~1)",
    "rf": "여러 인자를 같이 넣고 재질을 예측할 때, 그 인자를 섞으면 예측이 얼마나 나빠지는지",
    "gbm": "랜덤포레스트와 같은 방식이지만 비선형·상호작용을 더 잘 잡음. 빈 값도 그대로 학습",
    "lasso": "다른 인자를 고정했을 때 그 인자가 표준편차 1만큼 바뀌면 재질이 얼마나 바뀌는지",
}
SCORE_LABEL = {"effect": "차이 크기 (표준편차 몇 배)", "spearman": "순위상관 계수",
               "rf": "중요도 (예측 오차 증가)", "gbm": "중요도 (예측 오차 증가)", "lasso": "표준화 계수"}
MIN_ROWS, MIN_FACTORS, MAX_ROWS = 30, 3, 2000
SEED = 0


def _matrix(both: pd.DataFrame, factors: list[str], prop: str):
    data = both[factors + [prop]].dropna(subset=[prop])
    if len(data) > MAX_ROWS:  # 큰 데이터는 표본으로 (속도)
        data = data.sample(MAX_ROWS, random_state=SEED)
    return data[factors], data[prop]


def _perm(model, X, y) -> np.ndarray:
    from sklearn.inspection import permutation_importance
    model.fit(X, y)
    return permutation_importance(model, X, y, n_repeats=3, random_state=SEED, n_jobs=1).importances_mean


def scores(model: str, both: pd.DataFrame, factors: list[str], prop: str) -> dict:
    """{인자: 점수(크기)}. 계산할 수 없으면 빈 dict."""
    X, y = _matrix(both, factors, prop)
    if model == "spearman":
        return {f: X[f].corr(y, method="spearman") for f in factors if X[f].notna().sum() > 5}
    if model == "rf":
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import make_pipeline
        rf = make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True),
                           RandomForestRegressor(n_estimators=60, max_depth=8, min_samples_leaf=3,
                                                 random_state=SEED, n_jobs=-1))
        return dict(zip(factors, _perm(rf, X, y)))
    if model == "gbm":
        from sklearn.ensemble import HistGradientBoostingRegressor
        return dict(zip(factors, _perm(HistGradientBoostingRegressor(max_iter=120, random_state=SEED), X, y)))
    if model == "lasso":
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LassoCV
        from sklearn.preprocessing import StandardScaler
        Xs = StandardScaler().fit_transform(SimpleImputer(strategy="median", keep_empty_features=True).fit_transform(X))
        coef = LassoCV(cv=5, random_state=SEED, alphas=30, max_iter=5000).fit(Xs, (y - y.mean()) / y.std()).coef_
        return dict(zip(factors, coef))
    return {}


def rerank(rows: list[dict], both: pd.DataFrame, prop: str, model: str) -> tuple[list[dict], str, str | None]:
    """compare()의 인자 행에 모델 점수를 붙이고 정렬한다. 반환: (행, 실제로 쓴 모델, 안내 문구)."""
    note = None
    if model not in MODELS:
        model = DEFAULT
    if model != DEFAULT:
        n = int(both[prop].notna().sum())
        if n < MIN_ROWS or len(rows) < MIN_FACTORS:
            note = f"코일 {n}개·인자 {len(rows)}개로는 {MODELS[model]} 모델을 쓰기 어려워 차이 크기로 계산했어요."
            model = DEFAULT
    if model != DEFAULT:
        try:
            sc = scores(model, both, [r["factor"] for r in rows], prop)
        except ImportError:
            sc, note = {}, "scikit-learn이 설치되지 않아 차이 크기로 계산했어요."
        if not sc:
            model = DEFAULT
    for r in rows:
        if model == DEFAULT:
            r["score"] = r["effect_size"]
        elif model in ("spearman", "lasso"):  # 부호 있는 점수
            r["score"] = round(float(np.nan_to_num(sc.get(r["factor"], 0.0))), 3)
        else:  # 크기만 있는 점수 → 평균 차이 부호로 방향
            mag = max(float(np.nan_to_num(sc.get(r["factor"], 0.0))), 0.0)
            r["score"] = round(mag * (1 if (r["diff"] or 0) >= 0 else -1), 4)
        r["model"] = model
    rows.sort(key=lambda x: -abs(x["score"] or 0))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows, model, note
