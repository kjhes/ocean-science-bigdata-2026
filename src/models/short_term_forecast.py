"""환경변수(기온·풍속·풍향)를 반영한 단기(1일 뒤) 수온 예측 모델.

1차 멘토링 후속: "수온 하나만으로는 정확도가 나오지 않는다. 기온·일사량·
강수량·해풍을 추가하라"는 지적에 대응. 일사량·강수량은 지역별 결측 문제로
보류(docs/기상데이터_점검.md 참고)하고, 우선 기온·풍속·풍향만 사용한다.

문제 정의: 어제(t-1)까지의 정보(수온·기온·풍속)로 오늘(t)의 수온을 예측.
같은 날 기온을 입력으로 쓰지 않는다 (실제 운영 시점엔 오늘 기온도 아직
다 관측되지 않았을 수 있어 보수적으로 lag1만 사용 - 데이터 누수 방지).

검증: 2021~2023년 학습, **2024~2025년 2년을 검증용으로 남겨둠**
(2024년 9월 이상값 사례가 검증 기간에 포함되어, 환경변수 추가가 실제로
그 사례를 더 잘 잡는지 확인 가능).
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, REGIONS, DATE_COL, REGION_COL, TEMP_COL  # noqa: E402
from data.load_data import load_raw_temperature  # noqa: E402
from data.load_weather import load_daily_weather  # noqa: E402
from models.forecast import evaluate  # noqa: E402

TRAIN_RANGE = ("2021-01-01", "2023-12-31")
TEST_RANGE = ("2024-01-01", "2025-12-31")

FEATURE_COLS = [
    "sea_temp_lag1", "sea_temp_lag2", "sea_temp_lag3",
    "air_temp_mean_lag1", "air_temp_min_lag1", "air_temp_max_lag1",
    "wind_speed_mean_lag1", "doy_sin", "doy_cos",
]


def build_region_dataset(region: str) -> pd.DataFrame:
    """지역 하나의 수온+기상 일별 데이터를 병합하고 lag 피처를 만든다."""
    sea = load_raw_temperature(region)[[DATE_COL, TEMP_COL]].rename(columns={TEMP_COL: "sea_temp"})
    weather = load_daily_weather(region)[[DATE_COL, "air_temp_mean", "air_temp_min", "air_temp_max",
                                           "wind_speed_mean", "wind_dir_mean_deg"]]
    df = sea.merge(weather, on=DATE_COL, how="inner").sort_values(DATE_COL).reset_index(drop=True)

    df["sea_temp_lag1"] = df["sea_temp"].shift(1)
    df["sea_temp_lag2"] = df["sea_temp"].shift(2)
    df["sea_temp_lag3"] = df["sea_temp"].shift(3)
    df["air_temp_mean_lag1"] = df["air_temp_mean"].shift(1)
    df["air_temp_min_lag1"] = df["air_temp_min"].shift(1)
    df["air_temp_max_lag1"] = df["air_temp_max"].shift(1)
    df["wind_speed_mean_lag1"] = df["wind_speed_mean"].shift(1)

    doy = df[DATE_COL].dt.dayofyear
    df["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)

    df[REGION_COL] = region
    return df


def climatology_baseline(train: pd.DataFrame, test: pd.DataFrame, window: int = 3) -> np.ndarray:
    """기존 평년값 방식(±window일 평균)을 이 데이터 형태에 맞춰 재사용."""
    def ref_doy(dates):
        s = pd.DatetimeIndex(dates)
        d = s.dayofyear.to_numpy().astype(float)
        d[(s.is_leap_year) & (s.month > 2)] -= 1
        return d

    obs = train.dropna(subset=["sea_temp"])  # 결측 제거 후 평균 (안 하면 window 안에 결측이 하나만
    train_doy = ref_doy(obs[DATE_COL])       # 껴도 그 날짜 전체가 NaN이 되어버림 - 실제로 남해군에서 발생했던 버그)
    train_temp = obs["sea_temp"].to_numpy(dtype=float)
    test_doy = ref_doy(test[DATE_COL])
    preds = np.full(len(test_doy), np.nan)
    for i, day in enumerate(test_doy):
        diff = np.abs(train_doy - day)
        diff = np.minimum(diff, 365 - diff)
        near = diff <= window
        if near.any():
            preds[i] = train_temp[near].mean()
    return preds


def run_region(region: str) -> dict:
    df = build_region_dataset(region)
    train = df[(df[DATE_COL] >= TRAIN_RANGE[0]) & (df[DATE_COL] <= TRAIN_RANGE[1])]
    test = df[(df[DATE_COL] >= TEST_RANGE[0]) & (df[DATE_COL] <= TEST_RANGE[1])]

    train_valid = train.dropna(subset=FEATURE_COLS + ["sea_temp"])
    test_valid_mask = test[FEATURE_COLS + ["sea_temp"]].notna().all(axis=1)

    results = {}

    # 1) Persistence baseline: 어제 값 = 오늘 예측
    persistence_pred = test["sea_temp_lag1"].to_numpy()
    actual = test["sea_temp"].to_numpy()
    mask_p = np.isfinite(actual) & np.isfinite(persistence_pred)
    results["persistence"] = {"pred": persistence_pred, "mask": mask_p}

    # 2) 평년값(climatology) baseline
    clim_pred = climatology_baseline(train, test)
    mask_c = np.isfinite(actual) & np.isfinite(clim_pred)
    results["climatology"] = {"pred": clim_pred, "mask": mask_c}

    # 3) 선형회귀 (기온·풍속·풍향 + lag + 계절)
    lr = LinearRegression().fit(train_valid[FEATURE_COLS], train_valid["sea_temp"])
    lr_pred = np.full(len(test), np.nan)
    lr_pred[test_valid_mask.to_numpy()] = lr.predict(test.loc[test_valid_mask, FEATURE_COLS])
    mask_lr = np.isfinite(actual) & np.isfinite(lr_pred)
    results["linear_regression"] = {"pred": lr_pred, "mask": mask_lr}

    # 4) 랜덤포레스트 (비선형 비교용)
    rf = RandomForestRegressor(n_estimators=300, max_depth=6, random_state=0)
    rf.fit(train_valid[FEATURE_COLS], train_valid["sea_temp"])
    rf_pred = np.full(len(test), np.nan)
    rf_pred[test_valid_mask.to_numpy()] = rf.predict(test.loc[test_valid_mask, FEATURE_COLS])
    mask_rf = np.isfinite(actual) & np.isfinite(rf_pred)
    results["random_forest"] = {"pred": rf_pred, "mask": mask_rf}

    common = mask_p & mask_c & mask_lr & mask_rf

    rows = []
    for name, r in results.items():
        m = common  # 공통 평가일 기준 (모델 간 공정 비교)
        rows.append({"region": region, "model": name, "scope": "common_dates",
                     "n_scored": int(m.sum()), **evaluate(actual[m], r["pred"][m])})
        # 2024년 9월만 별도 (이상값 사례 특화 검증)
        sep2024 = (test[DATE_COL].dt.year == 2024) & (test[DATE_COL].dt.month == 9)
        m2 = (m.to_numpy() if hasattr(m, "to_numpy") else m) & sep2024.to_numpy()
        if m2.any():
            rows.append({"region": region, "model": name, "scope": "2024-09",
                         "n_scored": int(m2.sum()), **evaluate(actual[m2], r["pred"][m2])})

    return {"metrics": rows, "test_dates": test[DATE_COL].to_numpy(), "actual": actual,
            "preds": {k: v["pred"] for k, v in results.items()},
            "lr_coef": dict(zip(FEATURE_COLS, lr.coef_)), "lr_intercept": lr.intercept_}


def main():
    output = ROOT_DIR / "reports" / "short_term_forecast"
    (output / "figures").mkdir(parents=True, exist_ok=True)

    all_metrics = []
    coef_rows = []
    for region in REGIONS:
        out = run_region(region)
        all_metrics.extend(out["metrics"])
        coef_rows.append({"region": region, "intercept": out["lr_intercept"], **out["lr_coef"]})

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        dates = pd.DatetimeIndex(out["test_dates"])
        sep_mask = (dates.year == 2024) & (dates.month == 9)
        fig, ax = plt.subplots(figsize=(10, 4.5))
        ax.plot(dates[sep_mask], out["actual"][sep_mask], color="#222222", lw=1.6, label="실제 관측")
        ax.plot(dates[sep_mask], out["preds"]["climatology"][sep_mask], color="#898781", lw=1.2,
                linestyle="--", label="평년값 (환경변수 없음)")
        ax.plot(dates[sep_mask], out["preds"]["linear_regression"][sep_mask], color="#2a78d6", lw=1.4,
                label="선형회귀 (기온·풍속 반영)")
        ax.set_title(f"{region} 2024년 9월: 환경변수 반영 전후 비교")
        ax.set_ylabel("수온 (℃)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(output / "figures" / f"{region}_2024_09.png", dpi=150)
        plt.close(fig)

    metric_df = pd.DataFrame(all_metrics)
    metric_df.to_csv(output / "metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(coef_rows).to_csv(output / "linear_regression_coefficients.csv", index=False, encoding="utf-8-sig")

    print(metric_df.query("scope == 'common_dates'").to_string(index=False))
    print()
    print("=== 2024년 9월 (이상값 사례) ===")
    print(metric_df.query("scope == '2024-09'").to_string(index=False))
    print(f"\n저장 완료: {output}")
    return metric_df


if __name__ == "__main__":
    main()
