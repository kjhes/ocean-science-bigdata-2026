"""수과원 수온 + 기상청 파고부이 수온을 합쳐서 학습 → 수과원 4개 지점에서 평가.

buoy_validation.py 결론: 같은 모델 구조에서 학습 기간을 3년→7년으로 늘리면 도달일 예측이 좋아짐
(데이터 부족이 병목). 부이는 수과원 지점과 수온 수준이 달라(노화도 여름 약 4℃ 낮음) 대신 쓸 수는
없지만, "기상 → 수온 상승" 패턴 자체는 함께 배울 수 있는지 확인한다.

설계
  - 평가: 수과원 4개 지점, 2024~2025 여름 (recursive_experiment.py와 동일 → 결과 직접 비교 가능)
  - 학습: 수과원 2021~2023 + 부이 5곳 2016-09~2023 (부이 2024~2025는 평가기간 정보가 새므로 제외)
  - 지점 차이: 지점별 절편(더미변수)으로 수온 수준 차이만 보정, 기울기(패턴 반응)는 공유
  - 고수온 구간 학습 기준: 수과원 20℃(=28-8), 부이는 지점별 위험수온-8℃ (buoy_validation과 같은 상대 기준)
  - 비교: 수과원만 / 통합 / 통합+수과원 가중치(수과원·부이 전체 가중치 합을 같게)
"""
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, REGIONS  # noqa: E402
from data.fetch_wave_buoy import BUOYS  # noqa: E402
from models.pattern_experiment import SUMMER_MONTHS, DANGER_TEMP, rmse  # noqa: E402
from models import recursive_experiment as rx  # noqa: E402
from models.buoy_validation import load_buoy_series, DANGER_QUANTILE  # noqa: E402

NIFS_TRAIN = [2021, 2022, 2023]
BUOY_TRAIN = list(range(2016, 2024))
TEST_YEARS = [2024, 2025]
HOT_OFFSET = 8.0  # 위험수온 - 8℃ 이상만 학습하는 고수온 전용 모델 (수과원 28-8=20℃)
RUN_CONFIGS = ["기존모델", "기존+기간평균패턴"]
FILTERS = {"여름전체": False, "고수온(위험-8℃+)": True}
VARIANTS = ["수과원만", "통합", "통합+가중치"]


class WithStation:
    """지점 더미를 붙여서 예측하는 래퍼 (recursive_predict가 model.predict(DataFrame)만 호출하므로)."""

    def __init__(self, lr, dummy):
        self.lr, self.dummy = lr, np.asarray(dummy, dtype=float)

    def predict(self, X):
        X = np.asarray(X, dtype=float)
        return self.lr.predict(np.hstack([X, np.tile(self.dummy, (len(X), 1))]))


def load_stations():
    """지점별 (일별표, 학습연도, 위험수온, 구분) 목록."""
    st = {}
    for region in REGIONS:
        st[region] = (rx.load_series(region), NIFS_TRAIN, DANGER_TEMP, "수과원")
    for stn, (name, region) in BUOYS.items():
        df = load_buoy_series(stn)
        summer = df[df.index.month.isin(SUMMER_MONTHS) & df.index.year.isin(BUOY_TRAIN)]["sea"]
        danger = round(float(summer.quantile(DANGER_QUANTILE)) * 2) / 2
        st[f"부이:{name}"] = (df, BUOY_TRAIN, danger, "부이")
    return st


def main():
    warnings.filterwarnings("ignore", category=UserWarning)
    out = ROOT_DIR / "reports" / "pooled_experiment"
    out.mkdir(parents=True, exist_ok=True)

    stations = load_stations()
    names = list(stations)
    built = {}
    for n, (df, years, danger, kind) in stations.items():
        a, feats, target, summer_train, calm_cut = rx.build_features(df, years)
        built[n] = dict(df=df, a=a, feats=feats, target=target, ok=summer_train & target.notna().to_numpy(),
                        calm_cut=calm_cut, danger=danger, kind=kind)

    def dummy(n):
        return [1.0 if m == n else 0.0 for m in names]

    runs, models = {}, {r: {} for r in REGIONS}
    sizes = []
    for variant in VARIANTS:
        use = [n for n in names if variant != "수과원만" or built[n]["kind"] == "수과원"]
        for cfg in RUN_CONFIGS:
            cols = rx.CONFIGS[cfg]
            for fname, hot_only in FILTERS.items():
                run = f"{variant}|{cfg}|{fname}"
                runs[run] = (cfg, None)

                def stack(hot):
                    X, y, wts = [], [], []
                    for n in use:
                        b = built[n]
                        ok = b["ok"] & b["feats"][cols].notna().all(axis=1).to_numpy()
                        if hot:
                            ok &= (b["feats"]["sea_lag1"] >= b["danger"] - HOT_OFFSET).to_numpy()
                        Xn = b["feats"].loc[ok, cols].to_numpy(dtype=float)
                        X.append(np.hstack([Xn, np.tile(dummy(n), (len(Xn), 1))]))
                        y.append(b["target"][ok].to_numpy(dtype=float))
                        wts.append(np.full(len(Xn), 1.0 if b["kind"] == "수과원" else np.nan))
                    X, y, wts = np.vstack(X), np.concatenate(y), np.concatenate(wts)
                    is_nifs = ~np.isnan(wts)
                    if variant == "통합+가중치" and (~is_nifs).any():
                        wts[~is_nifs] = is_nifs.sum() / (~is_nifs).sum()  # 수과원·부이 전체 가중치 합을 같게
                    wts[np.isnan(wts)] = 1.0
                    return X, y, wts

                # fit_intercept=False: 지점 더미가 절편 역할
                X, y, wts = stack(False)
                base = LinearRegression(fit_intercept=False).fit(X, y, sample_weight=wts)
                hot = None
                if hot_only:
                    Xh, yh, wh = stack(True)
                    hot = LinearRegression(fit_intercept=False).fit(Xh, yh, sample_weight=wh)
                    sizes.append({"run": run, "기본모델_표본": len(y), "고수온모델_표본": len(yh)})
                else:
                    sizes.append({"run": run, "기본모델_표본": len(y)})
                for r in REGIONS:
                    thr = DANGER_TEMP - HOT_OFFSET if hot_only else None
                    models[r][run] = (WithStation(base, dummy(r)),
                                      WithStation(hot, dummy(r)) if hot is not None else None, thr)

    pd.set_option("display.width", 220)
    print("=== 학습 표본 수 ===")
    print(pd.DataFrame(sizes).to_string(index=False))

    rec = pd.concat([rx.recursive_predict(built[r]["df"], built[r]["a"], built[r]["calm_cut"], r, runs,
                                          models[r], TEST_YEARS) for r in REGIONS], ignore_index=True)
    rec.to_csv(out / "predictions.csv", index=False, encoding="utf-8-sig")

    scored = rec[rec["target_date"].dt.month.isin(SUMMER_MONTHS)].dropna(subset=["pred", "actual"])
    by = scored.groupby(["config", "region", "h"]).apply(
        lambda g: rmse(g["pred"], g["actual"]), include_groups=False).groupby(["config", "h"]).mean().unstack("h")
    hi = scored[scored["actual"] >= 25].groupby(["config", "region", "h"]).apply(
        lambda g: rmse(g["pred"], g["actual"]), include_groups=False).groupby(["config", "h"]).mean().unstack("h")
    table = pd.concat({"전체": by[[1, 3, 7]], "25℃이상": hi[[1, 3, 7]]}, axis=1).reindex(list(runs))
    table.to_csv(out / "rmse.csv", encoding="utf-8-sig")
    print("\n=== 수과원 4개 지점 여름 RMSE (2024~2025, 지점 평균) ===")
    print(table.round(3).to_string())

    cross = rx.crossing_summary(rec)
    cross.to_csv(out / "crossing_28c.csv", index=False, encoding="utf-8-sig")
    agg = cross.groupby(["config", "margin"])[["actual_events", "hit", "false_alarm", "abs_err_sum"]].sum()
    agg["recall"] = agg["hit"] / agg["actual_events"]
    agg["precision"] = agg["hit"] / (agg["hit"] + agg["false_alarm"]).replace(0, np.nan)
    agg["day_err"] = agg["abs_err_sum"] / agg["hit"].replace(0, np.nan)
    tab = agg[["recall", "precision", "day_err"]].unstack("margin").reindex(list(runs))
    tab.to_csv(out / "crossing_summary.csv", encoding="utf-8-sig")
    n_events = int(cross.groupby("config")["actual_events"].sum().iloc[0])
    print(f"\n=== 28℃ 도달일 예측 (수과원 4개 지점 합계, 실제 도달 {n_events}건, 열=경보 여유폭 ℃) ===")
    print(tab.round(2).to_string())
    print(f"\n저장 완료: {out}")


if __name__ == "__main__":
    main()
