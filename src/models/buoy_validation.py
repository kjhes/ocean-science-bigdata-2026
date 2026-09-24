"""모델 구조 검증: 기상청 파고부이 수온(2016-09~)에 같은 구조를 적용해 본다.

배경: 수과원 수온(2021~2025)은 여름 표본이 적어, 고수온 구간만 학습(24℃+/26℃+)하면 오히려
나빠졌다(통영 26℃+ 학습일 44일). 파고부이는 수과원 관측소와 위치가 달라(노화도는 여름 평균 약
4℃ 낮음) 수과원 수온을 대신할 수는 없지만, **같은 모델 구조가 다른 지점·더 긴 기간에서도
통하는지** 확인하는 독립 검증 데이터로 쓸 수 있다.

질문
  1) 학습 기간을 3년 → 7년으로 늘리면 도달일 예측이 좋아지는가? (데이터 부족이 원인이었는지)
  2) 데이터가 많으면 고수온 구간만 학습하는 방식이 효과를 내는가?
  3) recursive_experiment.py의 결론(기간평균 패턴·경보 여유폭)이 다른 지점에서도 유지되는가?

설계
  - 수온: 파고부이 일평균 수온(tw). 기상: 해당 지역 ASOS (수과원 실험과 동일)
  - 평가: 2023~2025 여름. 학습: 2020~2022(3년) vs 2016~2022(7년, 2016은 9월만)
  - 위험수온: 부이마다 수온 수준이 달라(외해일수록 차가움) 28℃ 대신 학습기간 여름 일수온의
    상위 5% 값을 그 지점의 위험수온으로 사용
  - 고수온 구간 학습 기준도 위험수온 기준 상대값(-8/-4/-2℃ = 수과원의 20/24/26℃에 대응)
"""
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, DATA_EXTERNAL_DIR, DATE_COL  # noqa: E402
from data.load_weather import load_daily_weather, load_morning_weather  # noqa: E402
from data.fetch_wave_buoy import BUOYS  # noqa: E402
from models.pattern_experiment import SUMMER_MONTHS, rmse  # noqa: E402
from models import recursive_experiment as rx  # noqa: E402

TEST_YEARS = [2023, 2024, 2025]
TRAIN_SETS = {"3년(2020~22)": [2020, 2021, 2022], "7년(2016~22)": list(range(2016, 2023))}
DANGER_QUANTILE = 0.95
RUN_CONFIGS = ["기존모델", "기존+기간평균패턴", "5일패턴:수온+기온+풍속+강수"]
REL_FILTERS = {"여름전체": None, "위험-8℃+": 8.0, "위험-4℃+": 4.0, "위험-2℃+": 2.0}


QC_RANGE = (-2.0, 33.0)   # 남해안 표층수온으로 물리적으로 가능한 범위
QC_SPIKE = 3.0            # 전후 3일(±3) 중앙값과 이 이상 차이 나면 센서 튐으로 보고 결측 처리


def qc_temperature(sea: pd.Series) -> pd.Series:
    """부이 수온 품질검사. 첫 실행에서 두미도 2021-07에 563.9·742.9℃ 같은 센서 오류값이 섞여
    회귀계수가 망가지고 재귀 예측이 발산했음(+7일 RMSE 3,000℃대) → 범위·급변 검사 추가."""
    s = sea.asfreq("D")
    s = s.where((s >= QC_RANGE[0]) & (s <= QC_RANGE[1]))
    med = s.rolling(7, center=True, min_periods=3).median()
    s = s.where((s - med).abs() <= QC_SPIKE)
    return s.reindex(sea.index)


def load_buoy_series(stn: str) -> pd.DataFrame:
    name, region = BUOYS[stn]
    b = pd.read_csv(DATA_EXTERNAL_DIR / "kma_wave_buoy" / f"{stn}_{name}.csv", parse_dates=["date"],
                    keep_default_na=False, na_values=[""])
    sea = pd.to_numeric(b.set_index("date")["tw"], errors="coerce").rename("sea")  # x/null = 결측
    sea = qc_temperature(sea)
    wx = load_daily_weather(region).set_index(DATE_COL)[
        ["air_temp_mean", "air_temp_min", "air_temp_max", "wind_speed_mean", "rain_sum"]]
    wx.columns = ["air_mean", "air_min", "air_max", "wind", "rain"]
    dawn = load_morning_weather(region, cutoff_hour=6).set_index(DATE_COL)[
        ["air_temp_morning_mean", "wind_speed_morning_mean"]]
    dawn.columns = ["air_dawn", "wind_dawn"]
    idx = pd.date_range(sea.index.min(), min(sea.index.max(), wx.index.max()), freq="D")
    df = pd.DataFrame(index=idx).join(sea).join(wx).join(dawn)
    df.index.name = DATE_COL
    return df


def main():
    warnings.filterwarnings("ignore", category=UserWarning)
    out = ROOT_DIR / "reports" / "buoy_validation"
    out.mkdir(parents=True, exist_ok=True)
    all_rec, dangers, info = [], {}, []

    for stn, (name, region) in BUOYS.items():
        path = DATA_EXTERNAL_DIR / "kma_wave_buoy" / f"{stn}_{name}.csv"
        if not path.exists():
            print(f"[건너뜀] {name}: 파일 없음")
            continue
        df = load_buoy_series(stn)
        label = f"{name}({region})"
        summer = df[df.index.month.isin(SUMMER_MONTHS)]["sea"]
        danger = round(float(summer[summer.index.year.isin(TRAIN_SETS["7년(2016~22)"])].quantile(DANGER_QUANTILE)) * 2) / 2
        dangers[label] = danger
        info.append({"buoy": label, "danger_temp": danger,
                     **{f"여름관측일_{y}": int(summer[summer.index.year == y].notna().sum()) for y in range(2016, 2026)}})
        for tname, years in TRAIN_SETS.items():
            runs = {f"{cfg}|{fn}|{tname}": (cfg, None if off is None else danger - off)
                    for cfg in RUN_CONFIGS for fn, off in REL_FILTERS.items()}
            rec = rx.run_series(df, label, runs=runs, train_years=years, test_years=TEST_YEARS)
            all_rec.append(rec)

    rec = pd.concat(all_rec, ignore_index=True)
    rec.to_csv(out / "predictions.csv", index=False, encoding="utf-8-sig")
    info = pd.DataFrame(info)
    info.to_csv(out / "buoy_info.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 220)
    print("\n=== 부이별 위험수온(학습기간 여름 상위 5%) / 여름 관측일수 ===")
    print(info.to_string(index=False))

    parts = rec["config"].str.split("|", expand=True)
    rec["model"], rec["filter"], rec["train"] = parts[0], parts[1], parts[2]
    scored = rec[rec["target_date"].dt.month.isin(SUMMER_MONTHS)].dropna(subset=["pred", "actual"])
    r = scored.groupby(["train", "model", "filter", "region", "h"]).apply(
        lambda g: rmse(g["pred"], g["actual"]), include_groups=False).groupby(["train", "model", "filter", "h"]).mean()
    pers = scored.drop_duplicates(["region", "issue_date", "h"]).groupby(["region", "h"]).apply(
        lambda g: rmse(g["today"], g["actual"]), include_groups=False).groupby("h").mean()
    print("\n=== 여름 RMSE (2023~2025, 부이 평균) - h=1,3,7 ===")
    print(f"(기준) 지속성=오늘값 유지: h1 {pers[1]:.3f} / h3 {pers[3]:.3f} / h7 {pers[7]:.3f}")
    print(r.unstack("h")[[1, 3, 7]].round(3).to_string())

    cross = rx.crossing_summary(rec.drop(columns=["model", "filter", "train"]), danger=dangers)
    cross.to_csv(out / "crossing.csv", index=False, encoding="utf-8-sig")
    agg = cross.groupby(["config", "margin"])[["actual_events", "hit", "false_alarm", "abs_err_sum"]].sum()
    agg["recall"] = agg["hit"] / agg["actual_events"]
    agg["precision"] = agg["hit"] / (agg["hit"] + agg["false_alarm"]).replace(0, np.nan)
    agg["day_err"] = agg["abs_err_sum"] / agg["hit"].replace(0, np.nan)
    tab = agg[["recall", "precision", "day_err"]].unstack("margin")
    idx = tab.index.to_series().str.split("|", expand=True)
    tab.index = pd.MultiIndex.from_arrays([idx[2], idx[0], idx[1]], names=["train", "model", "filter"])
    tab = tab.sort_index()
    tab.to_csv(out / "crossing_summary.csv", encoding="utf-8-sig")
    n_events = int(cross.groupby("config")["actual_events"].sum().iloc[0])
    print(f"\n=== 위험수온 도달일 예측 (2023~2025, 부이 합계, 실제 도달 {n_events}건, 열=경보 여유폭 ℃) ===")
    print(tab.round(2).to_string())
    print(f"\n저장 완료: {out}")


if __name__ == "__main__":
    main()
