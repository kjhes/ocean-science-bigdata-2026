"""남해 수과원 관측소마다 예보 모델을 학습·검증 (양식장 위치별 예보용).

구성은 4개 대표 지점 최종 모델(src/app/final_model.py)과 같다:
  기존 1일 모델 변수 + 3·7·14일 기상 흐름, 전날 수온 20℃ 이상이면 고수온 구간 전용 모델, 하루씩 굴려 7일.
기상은 관측소에서 가장 가까운 ASOS 지점(data/processed/nifs_station_catalog.csv의 asos).

- 학습: 그 관측소의 2025년까지 여름(6~9월). 여름 자료(60일 이상인 해)가 3년 이상인 관측소만
- 검증: 2026년 여름(학습에 안 쓴 기간) → 관측소별 정확도. 기준 미달 관측소는 앱에서 뺀다

사용: python src/app/station_models.py        (학습+검증 → models/station_models.pkl, reports/station_models/)
"""
from pathlib import Path
import pickle
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, DATE_COL, DATA_PROCESSED_DIR  # noqa: E402
from data.nifs_past import load_nifs_daily, load_code_series  # noqa: E402
from data.load_weather import load_station_weather  # noqa: E402
from models import recursive_experiment as rx  # noqa: E402
from models.pattern_experiment import SUMMER_MONTHS, HORIZONS  # noqa: E402

CATALOG_PATH = DATA_PROCESSED_DIR / "nifs_station_catalog.csv"
MODELS_PATH = ROOT_DIR / "models" / "station_models.pkl"
REPORT_DIR = ROOT_DIR / "reports" / "station_models"
CONFIG = "기존+기간평균패턴"
HOT_THRESHOLD = 20.0
LAST_TRAIN_YEAR = 2025
MIN_SUMMERS = 3
TEST_YEAR = 2026
# 앱 포함 기준 (2026 검증): 3일 뒤 ±1℃ 이내 60% 이상, 다음 날 RMSE 0.8℃ 이하
MIN_WITHIN1_H3 = 0.60
MAX_RMSE_H1 = 0.8


def station_frame(code: str, asos: int, weather_cache: dict, daily=None, recent=None) -> pd.DataFrame:
    """rx.load_series와 같은 모양(sea, air_mean, air_min, air_max, wind, rain, air_dawn, wind_dawn)."""
    sea = load_code_series(code, daily, recent)
    if asos not in weather_cache:
        w = load_station_weather(asos).set_index(DATE_COL)
        w.columns = ["air_mean", "air_min", "air_max", "wind", "rain", "air_dawn", "wind_dawn"]
        weather_cache[asos] = w
    wx = weather_cache[asos]
    idx = pd.date_range(sea.index.min(), max(sea.index.max(), wx.index.max()), freq="D")
    df = pd.DataFrame(index=idx).join(sea).join(wx)
    df.index.name = DATE_COL
    return df


def train_one(df: pd.DataFrame, train_years) -> dict:
    cols = rx.CONFIGS[CONFIG]
    a, feats, target, summer_train, calm_cut = rx.build_features(df, train_years)
    ok = summer_train & target.notna().to_numpy() & feats[cols].notna().all(axis=1).to_numpy()
    hot = ok & (feats["sea_lag1"] >= HOT_THRESHOLD).to_numpy()
    base = LinearRegression().fit(feats.loc[ok, cols].to_numpy(), target[ok].to_numpy())
    hot_model = LinearRegression().fit(feats.loc[hot, cols].to_numpy(), target[hot].to_numpy()) if hot.sum() >= 60 else base
    return {"base": base, "hot": hot_model, "calm_cut": float(calm_cut), "n_train": int(ok.sum()), "n_hot": int(hot.sum())}


def bundle_for(model: dict) -> dict:
    """app.final_model.forecast 가 받는 형태로 감싼다."""
    return {"cols": rx.CONFIGS[CONFIG], "hot_threshold": HOT_THRESHOLD, "regions": {"x": model}}


def validate(df: pd.DataFrame, model: dict) -> dict:
    from app import final_model as fm
    b = bundle_for(model)
    errs = {h: [] for h in HORIZONS}
    days = [d for d in df.index if d.year == TEST_YEAR and d.month in SUMMER_MONTHS
            and np.isfinite(df.at[d, "sea"]) and np.isfinite(df.at[d, "air_mean"])
            and (d + pd.Timedelta(days=7)).month in SUMMER_MONTHS and d + pd.Timedelta(days=7) <= df.index.max()]
    for d in days:
        f = fm.forecast(df, b, "x", d)
        for r in f.itertuples():
            y = df["sea"].get(r.date)
            if np.isfinite(r.pred) and y is not None and np.isfinite(y):
                errs[r.h].append(r.pred - y)
    out = {"n_days": len(days)}
    for h in HORIZONS:
        e = np.array(errs[h])
        out[f"rmse_h{h}"] = float(np.sqrt((e ** 2).mean())) if len(e) else np.nan
        out[f"within1_h{h}"] = float((np.abs(e) <= 1).mean()) if len(e) else np.nan
    return out


def main():
    warnings.filterwarnings("ignore")
    cat = pd.read_csv(CATALOG_PATH)
    cat = cat[cat["summers"] >= MIN_SUMMERS].reset_index(drop=True)
    daily = load_nifs_daily()
    recent = pd.read_csv(DATA_PROCESSED_DIR / "nifs_daily_recent.csv", parse_dates=["date"])
    cache, models, rows = {}, {}, []
    for i, r in cat.iterrows():
        try:
            df = station_frame(r["code"], int(r["asos"]), cache, daily, recent)
        except FileNotFoundError as e:
            print(f"[건너뜀] {r['name']}: {e}")
            continue
        years = [y for y in range(2011, LAST_TRAIN_YEAR + 1)]
        m = train_one(df, years)
        v = validate(df, m) if (df.index.year == TEST_YEAR).any() else {"n_days": 0}
        models[r["code"]] = m
        rows.append({"code": r["code"], "name": r["name"], "lat": r["lat"], "lon": r["lon"], "asos": int(r["asos"]),
                     "asos_km": r["asos_km"], "summers": int(r["summers"]), "n_train": m["n_train"], **v})
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(cat)} 관측소", flush=True)
    rep = pd.DataFrame(rows)
    rep["app_ok"] = (rep["within1_h3"] >= MIN_WITHIN1_H3) & (rep["rmse_h1"] <= MAX_RMSE_H1) & (rep["n_days"] >= 30)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.to_csv(REPORT_DIR / "station_validation_2026.csv", index=False, encoding="utf-8-sig")
    MODELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODELS_PATH, "wb") as f:
        pickle.dump({"config": CONFIG, "hot_threshold": HOT_THRESHOLD, "last_train_year": LAST_TRAIN_YEAR,
                     "models": models, "report": rep}, f)
    pd.set_option("display.width", 200)
    v = rep[rep["n_days"] >= 30]
    print(f"\n학습 {len(rep)}곳, 2026 검증 가능 {len(v)}곳, 앱 포함 기준 통과 {int(rep['app_ok'].sum())}곳")
    print(v[["rmse_h1", "rmse_h3", "rmse_h7", "within1_h1", "within1_h3", "within1_h7"]].describe().round(3).to_string())
    print("\n기준 미달:", rep.loc[~rep["app_ok"], ["name", "n_days", "rmse_h1", "within1_h3"]].round(2).to_string(index=False))
    print(f"\n저장: {MODELS_PATH}, {REPORT_DIR}")


def load() -> dict:
    with open(MODELS_PATH, "rb") as f:
        return pickle.load(f)


if __name__ == "__main__":
    main()
