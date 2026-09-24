"""여름철 수온 +1~+7일 예측: "시간 패턴" 변수의 효과 검증 실험.

2차 멘토링 후속: "고수온에 집중해 범위를 좁히고, 기온·풍속·강수량 등 환경요소의
패턴을 추가해 실제 수온을 얼마나 잘 맞추는지 확인하라 / 기온만, 기온+풍속,
기온+풍속+강수량 조합을 비교하라 / 위험수온 도달 시점을 예측하라."

질문: 하루치 값(스냅샷)만 보는 것보다, 최근 며칠~2주의 흐름(패턴)을 함께 보면
여름철 수온 예측이 좋아지는가?

설계
- 대상: 목표일(t+h)이 6~9월인 경우만 학습·평가 (여름철 제한). 단, 패턴 계산에
  필요한 직전 기간(예: 5월 말)의 관측치는 입력으로 사용한다.
- 문제: t일 저녁까지 관측된 정보만으로 t+h일(h=1~7) 수온 예측. 미래 기상(예보)은
  쓰지 않음 - 예보 입력 효과는 별도 실험으로 분리.
- 모델: 선형회귀, 예측일수(h)마다 별도 모델(direct 방식).
- 비교: 기상변수 조합 4가지(없음 / 기온 / 기온+풍속 / 기온+풍속+강수)
        x 입력 형태 2가지(스냅샷=당일값만 / 패턴=당일값+기간 흐름)
- 검증: 2021~2023 학습 / 2024~2025 평가 (기존 short_term_forecast.py와 동일).
  보조로 연도별 교차검증(한 해씩 빼고 학습)도 수행 - 여름 표본이 적어 특정 해에
  결과가 좌우되는지 확인하기 위함.
- 고수온 도달일 평가: 28℃(국립수산과학원 고수온 특보 기준) 이하인 날 예보를 냈을 때,
  7일 안에 28℃ 도달 예상일과 실제 도달일의 차이를 기록.
"""
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, REGIONS, DATE_COL, TEMP_COL  # noqa: E402
from data.load_data import load_raw_temperature  # noqa: E402
from data.load_weather import load_daily_weather  # noqa: E402

TRAIN_YEARS = [2021, 2022, 2023]
TEST_YEARS = [2024, 2025]
SUMMER_MONTHS = [6, 7, 8, 9]
HORIZONS = range(1, 8)
DANGER_TEMP = 28.0       # 고수온 특보 기준 수온 (warning_criteria 참고)
HOT_AIR_MAX = 30.0       # 폭염 기준 일 최고기온
CALM_QUANTILE = 0.25     # 약풍일 = 지역별 학습기간 여름 일평균풍속 하위 25%
RAIN_DAY_MM = 1.0        # 강수일 기준

# ---- 변수 그룹: 스냅샷(당일값) / 패턴(기간 흐름) ----
BASE = ["doy_sin", "doy_cos"]
SNAPSHOT = {
    "sea":  ["sea_temp", "sea_lag1", "sea_lag2"],
    "air":  ["air_mean", "air_max", "air_sea_diff"],
    "wind": ["wind_mean", "heatflux"],
    "rain": ["rain_sum"],
}
PATTERN = {
    "sea":  ["sea_mean7", "sea_trend3", "sea_trend7"],
    "air":  ["air_mean3", "air_mean7", "air_mean14", "hot_days7", "air_sea_diff7"],
    "wind": ["wind_mean3", "wind_mean7", "calm_days7", "heatflux7"],
    "rain": ["rain_sum3", "rain_sum7", "days_since_rain"],
}
WEATHER_SETS = {
    "수온만": [],
    "기온": ["air"],
    "기온+풍속": ["air", "wind"],
    "기온+풍속+강수": ["air", "wind", "rain"],
}


def feature_list(weather_set: str, with_pattern: bool) -> list:
    groups = ["sea"] + WEATHER_SETS[weather_set]
    cols = BASE + [c for g in groups for c in SNAPSHOT[g]]
    if with_pattern:
        cols += [c for g in groups for c in PATTERN[g]]
    return cols


CONFIGS = {f"{ws}|{'패턴' if p else '스냅샷'}": feature_list(ws, p)
           for ws in WEATHER_SETS for p in (False, True)}
ALL_FEATURES = sorted({c for cols in CONFIGS.values() for c in cols})


def build_dataset(region: str) -> pd.DataFrame:
    """일 단위 달력으로 재색인(결측일이 있어도 shift/rolling이 날짜 기준으로 맞도록)한 뒤 변수 생성."""
    sea = load_raw_temperature(region).set_index(DATE_COL)[TEMP_COL].rename("sea_temp")
    wx = load_daily_weather(region).set_index(DATE_COL)[
        ["air_temp_mean", "air_temp_max", "wind_speed_mean", "rain_sum"]]
    idx = pd.date_range(min(sea.index.min(), wx.index.min()), max(sea.index.max(), wx.index.max()), freq="D")
    df = pd.DataFrame(index=idx).join(sea).join(wx)
    df.index.name = DATE_COL

    s, air, wind, rain = df["sea_temp"], df["air_temp_mean"], df["wind_speed_mean"], df["rain_sum"]

    # 스냅샷
    df["sea_lag1"], df["sea_lag2"] = s.shift(1), s.shift(2)
    df["air_mean"], df["air_max"] = air, df["air_temp_max"]
    df["air_sea_diff"] = air - s
    df["wind_mean"] = wind
    df["heatflux"] = wind * (air - s)  # 벌크 열플럭스 구조 (short_term_forecast.py와 동일 발상)

    # 패턴 - 수온
    df["sea_mean7"] = s.rolling(7, min_periods=5).mean()
    df["sea_trend3"] = s - s.shift(3)
    df["sea_trend7"] = s - s.shift(7)
    # 패턴 - 기온 (누적 가열)
    for w in (3, 7, 14):
        df[f"air_mean{w}"] = air.rolling(w, min_periods=w - 1).mean()
    df["hot_days7"] = (df["air_temp_max"] >= HOT_AIR_MAX).astype(float).rolling(7, min_periods=6).sum()
    df["air_sea_diff7"] = df["air_sea_diff"].rolling(7, min_periods=5).mean()
    # 패턴 - 풍속 (약풍 지속 = 표층이 섞이지 않고 계속 데워짐)
    summer_train = df.index.month.isin(SUMMER_MONTHS) & df.index.year.isin(TRAIN_YEARS)
    calm_cut = wind[summer_train].quantile(CALM_QUANTILE)
    df["wind_mean3"] = wind.rolling(3, min_periods=2).mean()
    df["wind_mean7"] = wind.rolling(7, min_periods=6).mean()
    df["calm_days7"] = (wind <= calm_cut).astype(float).where(wind.notna()).rolling(7, min_periods=6).sum()
    df["heatflux7"] = df["heatflux"].rolling(7, min_periods=5).mean()
    # 패턴 - 강수
    df["rain_sum3"] = rain.rolling(3, min_periods=3).sum()
    df["rain_sum7"] = rain.rolling(7, min_periods=7).sum()
    rained = (rain >= RAIN_DAY_MM)
    last_rain = pd.Series(np.where(rained, np.arange(len(df)), np.nan), index=df.index).ffill()
    df["days_since_rain"] = (np.arange(len(df)) - last_rain).clip(upper=14).fillna(14)

    doy = df.index.dayofyear
    df["doy_sin"], df["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)

    for h in HORIZONS:
        df[f"y{h}"] = s.shift(-h)
    return df.reset_index()


def horizon_rows(df: pd.DataFrame, h: int) -> pd.DataFrame:
    """목표일(t+h)이 여름이고, 모든 설정의 입력과 정답이 존재하는 행 (설정 간 공정 비교용 공통 표본)."""
    target_month = (df[DATE_COL] + pd.Timedelta(days=h)).dt.month
    ok = target_month.isin(SUMMER_MONTHS) & df[ALL_FEATURES + [f"y{h}"]].notna().all(axis=1)
    return df[ok]


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, cols: list, h: int) -> np.ndarray:
    model = LinearRegression().fit(train[cols], train[f"y{h}"])
    return model.predict(test[cols])


def rmse(a, b) -> float:
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


def crossing_eval(df: pd.DataFrame, preds: dict, region: str, config: str) -> dict:
    """28℃ 도달일 평가. 예보일 t에 수온<28℃이고 +1~7일 정답·예측이 모두 있는 경우만."""
    issue = df.set_index(DATE_COL)
    pred_tab = pd.DataFrame({h: preds[h] for h in HORIZONS})  # index=예보일
    pred_tab = pred_tab.dropna()
    actual_tab = pd.DataFrame({h: issue[f"y{h}"] for h in HORIZONS}).loc[pred_tab.index].dropna()
    pred_tab = pred_tab.loc[actual_tab.index]
    below = issue.loc[actual_tab.index, "sea_temp"] < DANGER_TEMP
    pred_tab, actual_tab = pred_tab[below], actual_tab[below]

    def first_day(tab):
        hit = tab.to_numpy() >= DANGER_TEMP
        return np.where(hit.any(axis=1), hit.argmax(axis=1) + 1, 0)  # 0 = 7일 내 도달 안 함

    p, a = first_day(pred_tab), first_day(actual_tab)
    both = (p > 0) & (a > 0)
    err = p[both] - a[both]
    return {
        "region": region, "config": config, "n_issue_days": int(len(a)),
        "actual_events": int((a > 0).sum()), "hit": int(both.sum()),
        "miss": int(((a > 0) & (p == 0)).sum()), "false_alarm": int(((a == 0) & (p > 0)).sum()),
        "mean_abs_day_error": float(np.abs(err).mean()) if both.any() else np.nan,
        "mean_signed_day_error": float(err.mean()) if both.any() else np.nan,
        "within_1day_rate": float((np.abs(err) <= 1).mean()) if both.any() else np.nan,
    }


def run_region(region: str):
    df = build_dataset(region)
    year = df[DATE_COL].dt.year
    metric_rows, cross_rows, cv_rows = [], [], []
    test_preds = {cfg: {} for cfg in CONFIGS}

    for h in HORIZONS:
        rows = horizon_rows(df, h)
        ry = rows[DATE_COL].dt.year
        train, test = rows[ry.isin(TRAIN_YEARS)], rows[ry.isin(TEST_YEARS)]
        high = test[f"y{h}"] >= 25  # 고수온 구간 별도 성능
        metric_rows.append({"region": region, "h": h, "config": "지속성(오늘값 유지)",
                            "n": len(test), "rmse": rmse(test["sea_temp"], test[f"y{h}"]),
                            "rmse_25plus": rmse(test.loc[high, "sea_temp"], test.loc[high, f"y{h}"])})
        for cfg, cols in CONFIGS.items():
            pred = fit_predict(train, test, cols, h)
            test_preds[cfg][h] = pd.Series(pred, index=test[DATE_COL].to_numpy())
            metric_rows.append({"region": region, "h": h, "config": cfg, "n": len(test),
                                "rmse": rmse(pred, test[f"y{h}"]),
                                "rmse_25plus": rmse(pred[high.to_numpy()], test.loc[high, f"y{h}"])})
            # 연도별 교차검증 (한 해씩 빼고 학습)
            errs = []
            for y in sorted(ry.unique()):
                tr, te = rows[ry != y], rows[ry == y]
                errs.append(rmse(fit_predict(tr, te, cols, h), te[f"y{h}"]))
            cv_rows.append({"region": region, "h": h, "config": cfg, "cv_rmse_mean": float(np.mean(errs)),
                            **{f"rmse_{y}": e for y, e in zip(sorted(ry.unique()), errs)}})

    test_issue = df[year.isin(TEST_YEARS)]
    for cfg in CONFIGS:
        cross_rows.append(crossing_eval(test_issue, test_preds[cfg], region, cfg))
    return metric_rows, cross_rows, cv_rows


def main():
    warnings.filterwarnings("ignore", category=UserWarning)
    out = ROOT_DIR / "reports" / "pattern_experiment"
    out.mkdir(parents=True, exist_ok=True)

    metrics, cross, cv = [], [], []
    for region in REGIONS:
        m, c, v = run_region(region)
        metrics += m
        cross += c
        cv += v
    metrics, cross, cv = pd.DataFrame(metrics), pd.DataFrame(cross), pd.DataFrame(cv)
    metrics.to_csv(out / "metrics_by_horizon.csv", index=False, encoding="utf-8-sig")
    cross.to_csv(out / "crossing_28c.csv", index=False, encoding="utf-8-sig")
    cv.to_csv(out / "loyo_cv.csv", index=False, encoding="utf-8-sig")

    order = ["지속성(오늘값 유지)"] + list(CONFIGS)
    pd.set_option("display.width", 200)
    print("=== 평가(2024~2025 여름) RMSE, 4개 지역 평균 ===")
    piv = metrics.groupby(["config", "h"])["rmse"].mean().unstack("h").reindex(order)
    print(piv.round(3).to_string())
    print("\n=== 25℃ 이상 구간 RMSE, 4개 지역 평균 ===")
    print(metrics.groupby(["config", "h"])["rmse_25plus"].mean().unstack("h").reindex(order).round(3).to_string())
    print("\n=== 연도별 교차검증 RMSE (5개 연도 평균, 4개 지역 평균) ===")
    print(cv.groupby(["config", "h"])["cv_rmse_mean"].mean().unstack("h").reindex(order[1:]).round(3).to_string())
    print("\n=== 28℃ 도달일 예측 (2024~2025, 4개 지역 합계) ===")
    agg = cross.groupby("config").agg(actual_events=("actual_events", "sum"), hit=("hit", "sum"),
                                      miss=("miss", "sum"), false_alarm=("false_alarm", "sum")).reindex(order[1:])
    detail = pd.concat([cross.assign(w=cross["hit"]).groupby("config").apply(
        lambda g: pd.Series({
            "mean_abs_day_error": np.average(g["mean_abs_day_error"].fillna(0), weights=g["w"]) if g["w"].sum() else np.nan,
            "mean_signed_day_error": np.average(g["mean_signed_day_error"].fillna(0), weights=g["w"]) if g["w"].sum() else np.nan,
        }), include_groups=False)], axis=1)
    print(agg.join(detail).round(2).to_string())
    print(f"\n저장 완료: {out}")


if __name__ == "__main__":
    main()
