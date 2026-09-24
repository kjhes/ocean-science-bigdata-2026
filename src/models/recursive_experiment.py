"""기존 1일 예측 모델(short_term_forecast.py) + 패턴 변수를 하루씩 굴려 +7일까지 예측하는 실험.

pattern_experiment.py 결과: 과거 정보만으로 +h일을 바로 예측(direct)하면 패턴 효과가 없고,
28℃ 도달을 거의 못 맞춤(예측이 평평해짐). 병목은 "앞으로의 날씨"였다.

여기서는 이미 검증된 1일 예측 모델(수온 lag1~3 + 어제 기상 + 당일 새벽 기온·풍속 +
열플럭스 + 계절)을 기본으로, 패턴 변수를 더해 하루씩 재귀적으로 예측한다
(t+1 예측값을 t+2 예측의 '어제 수온'으로 사용).

+2일부터는 그날의 기상이 필요하므로 두 시나리오로 비교:
  - 예보없음: t일 이후 기상은 t일 값이 그대로 유지된다고 가정
  - 예보가정: 실제 관측 기상을 "정확한 예보"로 간주 (앱에서 기상청 예보를 넣는 상황의 상한선)

학습: 목표일이 6~9월인 날만, 2021~2023 / 평가: 2024~2025 (pattern_experiment.py와 동일).
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
from data.load_weather import load_daily_weather, load_morning_weather  # noqa: E402
from models.pattern_experiment import (TRAIN_YEARS, TEST_YEARS, SUMMER_MONTHS, HORIZONS, DANGER_TEMP,  # noqa: E402
                                       HOT_AIR_MAX, CALM_QUANTILE, RAIN_DAY_MM, rmse)

EXISTING = ["sea_lag1", "sea_lag2", "sea_lag3", "air_mean_lag1", "air_min_lag1", "air_max_lag1",
            "wind_lag1", "rain_lag1", "doy_sin", "doy_cos", "air_dawn", "wind_dawn", "heatflux_dawn"]
SEA_PATTERN = ["sea_mean7", "sea_trend3", "sea_trend7"]
WX_PATTERN = ["air_mean3", "air_mean7", "air_mean14", "hot_days7", "air_sea_diff7",
              "wind_mean3", "wind_mean7", "calm_days7", "heatflux7", "rain_sum3", "rain_sum7", "days_since_rain"]
# 5일 패턴: 기간 평균 대신 최근 1~5일 전 값을 날짜별로 그대로 입력 (최근 5일의 상승 모양 자체를 학습)
LAG_DAYS = range(1, 6)
LAG5 = {
    "sea": [f"sea_lag{k}" for k in LAG_DAYS],
    "air": [f"air_mean_lag{k}" for k in LAG_DAYS],
    "wind": [f"wind_lag{k}" for k in LAG_DAYS],
    "rain": [f"rain_lag{k}" for k in LAG_DAYS],
}


def with_lag5(groups):
    return EXISTING + [c for g in groups for c in LAG5[g] if c not in EXISTING]


CONFIGS = {
    "기존모델": EXISTING,
    "기존+기간평균패턴": EXISTING + SEA_PATTERN + WX_PATTERN,
    "5일패턴:수온": with_lag5(["sea"]),
    "5일패턴:수온+기온": with_lag5(["sea", "air"]),
    "5일패턴:수온+기온+풍속": with_lag5(["sea", "air", "wind"]),
    "5일패턴:수온+기온+풍속+강수": with_lag5(["sea", "air", "wind", "rain"]),
}
MARGINS = [0.0, 0.5, 1.0]  # 예측이 (위험수온 - 여유폭)에 도달하면 경보

# 학습 구간 좁히기: 어제 수온이 기준(℃) 이상인 날만으로 고수온 전용 모델 학습 (None = 여름 전체)
TRAIN_FILTERS = {"여름전체": None, "20℃+": 20.0, "24℃+": 24.0, "26℃+": 26.0}
RUN_CONFIGS = ["기존모델", "기존+기간평균패턴", "5일패턴:수온+기온+풍속+강수"]
RUNS = {f"{cfg}|{fn}": (cfg, thr) for cfg in RUN_CONFIGS for fn, thr in TRAIN_FILTERS.items()}
SCENARIOS = ["예보없음"]  # 예보가정은 도달일 성능에 차이가 거의 없어 이번 실험에서 제외
WX_COLS = ["air_mean", "air_min", "air_max", "wind", "rain", "air_dawn", "wind_dawn"]
LOOKBACK = 15  # 가장 긴 패턴 창(14일) + 1


def load_series(region: str, long_history: bool = False) -> pd.DataFrame:
    """long_history=True: 수과원 과거 관측정보(2012~, data/processed/nifs_daily_southsea.csv) 사용."""
    if long_history:
        from data.nifs_past import load_station_series
        sea = load_station_series(region)
    else:
        sea = load_raw_temperature(region).set_index(DATE_COL)[TEMP_COL].rename("sea")
    wx = load_daily_weather(region).set_index(DATE_COL)[
        ["air_temp_mean", "air_temp_min", "air_temp_max", "wind_speed_mean", "rain_sum"]]
    wx.columns = ["air_mean", "air_min", "air_max", "wind", "rain"]
    dawn = load_morning_weather(region, cutoff_hour=6).set_index(DATE_COL)[
        ["air_temp_morning_mean", "wind_speed_morning_mean"]]
    dawn.columns = ["air_dawn", "wind_dawn"]
    idx = pd.date_range(sea.index.min(), sea.index.max(), freq="D")
    df = pd.DataFrame(index=idx).join(sea).join(wx).join(dawn)
    df.index.name = DATE_COL
    return df


def day_features(a: dict, i: int, doy: int, calm_cut: float) -> dict:
    """i번째 날(목표일) 예측용 입력. 수온·일별기상은 i-1까지, 새벽기상은 i일 것만 사용 (short_term_forecast.py와 동일 규칙)."""
    s, am, w, r = a["sea"], a["air_mean"], a["wind"], a["rain"]
    past = slice(i - 7, i)

    def mean(x, sl, min_n):
        v = x[sl]
        return np.nanmean(v) if np.isfinite(v).sum() >= min_n else np.nan

    rained = np.where(r[:i] >= RAIN_DAY_MM)[0]
    lags = {}
    for k in LAG_DAYS:
        lags[f"sea_lag{k}"], lags[f"air_mean_lag{k}"] = s[i - k], am[i - k]
        lags[f"wind_lag{k}"], lags[f"rain_lag{k}"] = w[i - k], r[i - k]
    return {
        **lags,
        "sea_lag1": s[i - 1], "sea_lag2": s[i - 2], "sea_lag3": s[i - 3],
        "air_mean_lag1": am[i - 1], "air_min_lag1": a["air_min"][i - 1], "air_max_lag1": a["air_max"][i - 1],
        "wind_lag1": w[i - 1], "rain_lag1": r[i - 1],
        "doy_sin": np.sin(2 * np.pi * doy / 365.25), "doy_cos": np.cos(2 * np.pi * doy / 365.25),
        "air_dawn": a["air_dawn"][i], "wind_dawn": a["wind_dawn"][i],
        "heatflux_dawn": a["wind_dawn"][i] * (a["air_dawn"][i] - s[i - 1]),
        "sea_mean7": mean(s, past, 5), "sea_trend3": s[i - 1] - s[i - 4], "sea_trend7": s[i - 1] - s[i - 8],
        "air_mean3": mean(am, slice(i - 3, i), 2), "air_mean7": mean(am, past, 6), "air_mean14": mean(am, slice(i - 14, i), 13),
        "hot_days7": float((a["air_max"][past] >= HOT_AIR_MAX).sum()),
        "air_sea_diff7": mean(am - s, past, 5),
        "wind_mean3": mean(w, slice(i - 3, i), 2), "wind_mean7": mean(w, past, 6),
        "calm_days7": float((w[past] <= calm_cut).sum()),
        "heatflux7": mean(w * (am - s), past, 5),
        "rain_sum3": np.nansum(r[i - 3:i]), "rain_sum7": np.nansum(r[past]),
        "days_since_rain": float(min(i - rained[-1], 14)) if rained.size else 14.0,
    }


def arrays(df: pd.DataFrame) -> dict:
    return {c: df[c].to_numpy(dtype=float) for c in ["sea"] + WX_COLS}


def run_region(region: str):
    return run_series(load_series(region), region)


def build_features(df: pd.DataFrame, train_years=TRAIN_YEARS):
    """일별 표 -> (배열, 날짜별 입력변수, 정답, 여름학습일 마스크, 약풍 기준)."""
    dates = df.index
    summer_train = dates.month.isin(SUMMER_MONTHS) & dates.year.isin(train_years)
    calm_cut = df["wind"][summer_train].quantile(CALM_QUANTILE)
    a = arrays(df)
    feats = pd.DataFrame([day_features(a, i, dates[i].dayofyear, calm_cut) if i >= LOOKBACK else {}
                          for i in range(len(df))], index=dates)
    return a, feats, df["sea"], summer_train, calm_cut


def recursive_predict(df: pd.DataFrame, a: dict, calm_cut: float, region: str, runs: dict, models: dict,
                      test_years=TEST_YEARS) -> pd.DataFrame:
    """재귀 예측: 예보일 t (t까지 관측 완료) -> t+1..t+7. models[run] = (기본모델, 고수온모델|None, 전환기준|None)."""
    dates = df.index
    records = []
    issue_idx = [i for i in range(LOOKBACK, len(df) - 7)
                 if dates[i].year in test_years and np.isfinite(a["sea"][i])
                 and any(dates[i + h].month in SUMMER_MONTHS for h in HORIZONS)]
    for scenario in SCENARIOS:
        for run, (cfg, _) in runs.items():
            cols = CONFIGS[cfg]
            base, hot_model, thr = models[run]
            for i in issue_idx:
                lo = i - LOOKBACK
                w = {k: v[lo:i + 8].copy() for k, v in a.items()}
                t = LOOKBACK  # 창 안에서의 예보일 위치
                w["sea"][t + 1:] = np.nan
                if scenario == "예보없음":
                    for c in WX_COLS:
                        w[c][t + 1:] = w[c][t]
                for h in HORIZONS:
                    x = day_features(w, t + h, dates[i + h].dayofyear, calm_cut)
                    xv = np.array([[x[c] for c in cols]])
                    # 어제 수온(실측 또는 앞 단계 예측)이 기준 이상이면 고수온 전용 모델로 전환
                    model = hot_model if thr is not None and x["sea_lag1"] >= thr else base
                    pred = model.predict(pd.DataFrame(xv, columns=cols))[0] if np.isfinite(xv).all() else np.nan
                    w["sea"][t + h] = pred
                    records.append({"region": region, "scenario": scenario, "config": run,
                                    "issue_date": dates[i], "h": h, "target_date": dates[i + h],
                                    "today": a["sea"][i], "pred": pred, "actual": a["sea"][i + h]})
    return pd.DataFrame(records)


def run_series(df: pd.DataFrame, region: str, runs: dict = None, train_years=TRAIN_YEARS, test_years=TEST_YEARS):
    """수온(sea)+기상 일별 표를 받아 학습·재귀예측. 수과원 수온 외 다른 수온(예: 기상청 파고부이)에도 같은 구조 적용용."""
    runs = runs or RUNS
    a, feats, target, summer_train, calm_cut = build_features(df, train_years)
    base_ok = summer_train & target.notna().to_numpy()
    models, train_sizes = {}, {}
    for run, (cfg, thr) in runs.items():
        cols = CONFIGS[cfg]
        ok = base_ok & feats[cols].notna().all(axis=1).to_numpy()
        base = LinearRegression().fit(feats.loc[ok, cols], target[ok])
        if thr is None:
            models[run] = (base, None, None)
            train_sizes[run] = int(ok.sum())
        else:
            # 고수온 구간 전용 모델: 입력(어제 수온)이 thr 이상인 날만 학습 (정답이 아닌 입력 기준이라 리크 없음)
            hot = ok & (feats["sea_lag1"] >= thr).to_numpy()
            models[run] = (base, LinearRegression().fit(feats.loc[hot, cols], target[hot]), thr)
            train_sizes[run] = int(hot.sum())
    print(f"[{region}] 학습 표본 수:", train_sizes)
    return recursive_predict(df, a, calm_cut, region, runs, models, test_years)


def crossing_summary(rec: pd.DataFrame, danger=None) -> pd.DataFrame:
    """28℃ 도달일 평가 (pattern_experiment.crossing_eval과 같은 규칙) + 경보 여유폭별 비교.
    예보일 t에 수온<28℃이고 +1~7일이 모두 여름이며 정답·예측이 모두 있는 경우만 평가."""
    rows = []
    for (scn, cfg, region), gr in rec.groupby(["scenario", "config", "region"]):
        p = gr.pivot(index="issue_date", columns="h", values="pred")
        act = gr.pivot(index="issue_date", columns="h", values="actual")
        today = gr.groupby("issue_date")["today"].first()
        summer_all = gr.groupby("issue_date")["target_date"].apply(lambda d: d.dt.month.isin(SUMMER_MONTHS).all())
        # danger: None=28℃ 공통, dict=지역(지점)별 위험수온
        d = DANGER_TEMP if danger is None else danger[region]
        keep = p.notna().all(axis=1) & act.notna().all(axis=1) & (today < d) & summer_all
        av = act[keep].to_numpy() >= d
        af = np.where(av.any(1), av.argmax(1) + 1, 0)  # 0 = 7일 내 도달 안 함
        for margin in MARGINS:
            pv = p[keep].to_numpy() >= d - margin
            pf = np.where(pv.any(1), pv.argmax(1) + 1, 0)
            both = (pf > 0) & (af > 0)
            rows.append({"scenario": scn, "config": cfg, "margin": margin, "region": region,
                         "actual_events": int((af > 0).sum()), "hit": int(both.sum()),
                         "false_alarm": int(((af == 0) & (pf > 0)).sum()),
                         "abs_err_sum": float(np.abs(pf[both] - af[both]).sum()),
                         "signed_err_sum": float((pf[both] - af[both]).sum())})
    return pd.DataFrame(rows)


def main():
    warnings.filterwarnings("ignore", category=UserWarning)
    out = ROOT_DIR / "reports" / "recursive_experiment"
    out.mkdir(parents=True, exist_ok=True)
    rec = pd.concat([run_region(r) for r in REGIONS], ignore_index=True)
    rec.to_csv(out / "predictions.csv", index=False, encoding="utf-8-sig")

    scored = rec[rec["target_date"].dt.month.isin(SUMMER_MONTHS)].dropna(subset=["pred", "actual"])
    pd.set_option("display.width", 200)
    order = [(s, c) for s in SCENARIOS for c in RUNS]
    by = scored.groupby(["scenario", "config", "region", "h"]).apply(
        lambda g: rmse(g["pred"], g["actual"]), include_groups=False).groupby(["scenario", "config", "h"]).mean()
    table = by.unstack("h").reindex(order)
    table.to_csv(out / "rmse_by_horizon.csv", encoding="utf-8-sig")
    print("=== 여름 RMSE (2024~2025, 4개 지역 평균) ===")
    print(table.round(3).to_string())

    hi = scored[scored["actual"] >= 25]
    hi_t = hi.groupby(["scenario", "config", "region", "h"]).apply(
        lambda g: rmse(g["pred"], g["actual"]), include_groups=False).groupby(["scenario", "config", "h"]).mean()
    print("\n=== 25℃ 이상 구간 RMSE ===")
    print(hi_t.unstack("h").reindex(order).round(3).to_string())

    cross = crossing_summary(rec)
    cross.to_csv(out / "crossing_28c.csv", index=False, encoding="utf-8-sig")
    agg = cross.groupby(["scenario", "config", "margin"])[
        ["actual_events", "hit", "false_alarm", "abs_err_sum", "signed_err_sum"]].sum()
    agg["recall"] = agg["hit"] / agg["actual_events"]
    agg["precision"] = agg["hit"] / (agg["hit"] + agg["false_alarm"]).replace(0, np.nan)
    agg["day_err"] = agg["abs_err_sum"] / agg["hit"].replace(0, np.nan)
    print("\n=== 28℃ 도달일 예측 (4개 지역 합계, 열=경보 여유폭 ℃) ===")
    for scn in SCENARIOS:
        print(f"--- {scn} (실제 도달 {int(agg.loc[scn, 'actual_events'].iloc[0])}건) ---")
        print(agg.loc[scn][["recall", "precision", "day_err"]].unstack("margin")
              .reindex(list(RUNS)).round(2).to_string())
    print(f"\n저장 완료: {out}")


if __name__ == "__main__":
    main()
