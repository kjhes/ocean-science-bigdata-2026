"""앱에 들어가는 최종 예측 모델: 학습·저장·7일 예보.

모델 구성 (근거: reports/long_history_experiment, reports/holdout_2026)
  - 입력: 기존 1일 모델 변수(수온 lag1~3, 전날 기온·풍속·강수, 새벽 기온·풍속, 열플럭스, 계절)
          + 기간평균 패턴(3·7·14일 기온, 폭염일수, 약풍일수, 누적강수 등)
  - 지역별 선형회귀, 전날 수온 20℃ 이상이면 고수온 구간 전용 모델로 전환
  - 하루씩 굴려 +7일까지 예측, 예보일 이후 기상은 예보일 값이 유지된다고 가정(검증과 동일 조건)
  - 학습: 수과원 과거 관측정보 2012~2025 여름(6~9월). 완도 군외는 2020년 설치라 2020~
  - 2026년 여름(모델 선택에 안 쓴 자료) 검증: +1일 오차 1℃ 이내 98%, +3일 82%, +7일 65%
  - 위험 판정 여유폭 0.75℃: 모델이 급상승을 작게 예측하는 경향이 있어, 예측이 기준보다
    0.75℃ 낮은 시점부터 '위험'으로 본다 (2026년 28℃ 도달 71% 포착, 도달일 오차 평균 1.7일)
"""
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, REGIONS  # noqa: E402
from models import recursive_experiment as rx  # noqa: E402
from models.pattern_experiment import HORIZONS  # noqa: E402

CONFIG = "기존+기간평균패턴"
HOT_THRESHOLD = 20.0
TRAIN_YEARS = list(range(2012, 2026))
ALERT_MARGIN = 0.75
MODEL_PATH = ROOT_DIR / "models" / "final_model.pkl"

# 2026년 여름 검증(reports/holdout_2026) 결과 - 앱의 '예보 정확도' 안내에 사용
VALIDATION = {"기간": "2026년 6~9월", "1일": 0.98, "3일": 0.82, "5일": 0.66, "7일": 0.65,
              "도달포착": 0.71, "도달일오차": 1.7}


def train() -> dict:
    cols = rx.CONFIGS[CONFIG]
    bundle = {"config": CONFIG, "cols": cols, "hot_threshold": HOT_THRESHOLD, "train_years": TRAIN_YEARS,
              "alert_margin": ALERT_MARGIN, "validation": VALIDATION, "regions": {}}
    for region in REGIONS:
        df = rx.load_series(region, long_history=True)
        a, feats, target, summer_train, calm_cut = rx.build_features(df, TRAIN_YEARS)
        ok = summer_train & target.notna().to_numpy() & feats[cols].notna().all(axis=1).to_numpy()
        hot = ok & (feats["sea_lag1"] >= HOT_THRESHOLD).to_numpy()
        base = LinearRegression().fit(feats.loc[ok, cols].to_numpy(), target[ok].to_numpy())
        hot_model = LinearRegression().fit(feats.loc[hot, cols].to_numpy(), target[hot].to_numpy())
        bundle["regions"][region] = {"base": base, "hot": hot_model, "calm_cut": float(calm_cut),
                                     "n_train": int(ok.sum()), "n_hot": int(hot.sum())}
        print(f"[{region}] 학습 {int(ok.sum())}일 (고수온 구간 {int(hot.sum())}일)")
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(bundle, f)
    print(f"저장: {MODEL_PATH}")
    return bundle


def load() -> dict:
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)


def forecast(df: pd.DataFrame, bundle: dict, region: str, issue_date: pd.Timestamp = None) -> pd.DataFrame:
    """issue_date(수온·기상 관측이 끝난 마지막 날)로부터 +1~+7일 예상 수온.

    recursive_experiment.recursive_predict의 '예보없음' 시나리오와 같은 규칙으로 계산한다."""
    m = bundle["regions"][region]
    cols = bundle["cols"]
    if issue_date is None:
        issue_date = df.index[df["sea"].notna() & df["air_mean"].notna()].max()
    idx = pd.date_range(issue_date - pd.Timedelta(days=rx.LOOKBACK), issue_date + pd.Timedelta(days=7), freq="D")
    w = df.reindex(idx)
    a = {k: v.copy() for k, v in rx.arrays(w).items()}  # pandas 3는 읽기전용 배열을 줄 수 있음
    t = rx.LOOKBACK
    a["sea"][t + 1:] = np.nan
    for c in rx.WX_COLS:
        a[c][t + 1:] = a[c][t]
    rows = []
    for h in HORIZONS:
        x = rx.day_features(a, t + h, idx[t + h].dayofyear, m["calm_cut"])
        xv = np.array([[x[c] for c in cols]], dtype=float)
        model = m["hot"] if x["sea_lag1"] >= bundle["hot_threshold"] else m["base"]
        pred = float(model.predict(xv)[0]) if np.isfinite(xv).all() else np.nan
        a["sea"][t + h] = pred
        rows.append({"date": idx[t + h], "h": h, "pred": pred})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    train()
