"""수과원 같은 관측소의 과거 자료(2012~)로 학습 기간을 늘렸을 때 효과 검증.

배경
  - recursive_experiment.py: 학습 2021~2023(3년)뿐이라 고수온 구간만 학습하면 표본 부족으로 오히려 나빠짐
  - buoy_validation.py: 같은 구조에서 학습을 3→7년 늘리면 좋아짐 (단, 외해 부이라 양식장과 반응이 다름)
  - pooled_experiment.py: 부이를 섞으면 수온 오차는 줄지만 도달일은 개선 안 됨 → 양식장 지점 데이터가 필요
  - 2026-09-24 수과원 '과거 관측정보 다운로드'에서 같은 관측소의 2012~ 자료 확보 (src/data/nifs_past.py)

설계: 평가는 기존과 동일(2024~2025 여름, 28℃). 학습 3년(2021~23) vs 장기(2012~23, 완도 군외는 2020년 설치라 2020~23).
경보 여유폭은 0~1.5℃를 모두 보고, 잡은 비율·경보 정확도 균형(F1)이 가장 좋은 지점으로 비교.
"""
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, REGIONS  # noqa: E402
from models.pattern_experiment import SUMMER_MONTHS, rmse  # noqa: E402
from models import recursive_experiment as rx  # noqa: E402

TEST_YEARS = [2024, 2025]
TRAIN_SETS = {"3년(2021~23)": [2021, 2022, 2023], "장기(2012~23)": list(range(2012, 2024))}
RUN_CONFIGS = ["기존모델", "기존+기간평균패턴", "5일패턴:수온+기온+풍속+강수"]
FILTERS = {"여름전체": None, "20℃+": 20.0, "24℃+": 24.0, "26℃+": 26.0}
MARGINS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5]


def main():
    warnings.filterwarnings("ignore", category=UserWarning)
    rx.MARGINS = MARGINS
    out = ROOT_DIR / "reports" / "long_history_experiment"
    out.mkdir(parents=True, exist_ok=True)

    recs, sizes = [], []
    for region in REGIONS:
        df = rx.load_series(region, long_history=True)
        for tname, years in TRAIN_SETS.items():
            runs = {f"{tname}|{cfg}|{fn}": (cfg, thr) for cfg in RUN_CONFIGS for fn, thr in FILTERS.items()}
            recs.append(rx.run_series(df, region, runs=runs, train_years=years, test_years=TEST_YEARS))
    rec = pd.concat(recs, ignore_index=True)
    rec.to_csv(out / "predictions.csv", index=False, encoding="utf-8-sig")
    order = list(dict.fromkeys(rec["config"]))

    scored = rec[rec["target_date"].dt.month.isin(SUMMER_MONTHS)].dropna(subset=["pred", "actual"])

    def rmse_table(d):
        return d.groupby(["config", "region", "h"]).apply(
            lambda g: rmse(g["pred"], g["actual"]), include_groups=False).groupby(["config", "h"]).mean().unstack("h")

    table = pd.concat({"전체": rmse_table(scored)[[1, 3, 7]],
                       "25℃이상": rmse_table(scored[scored["actual"] >= 25])[[1, 3, 7]]}, axis=1).reindex(order)
    table.to_csv(out / "rmse.csv", encoding="utf-8-sig")
    pd.set_option("display.width", 220)
    print("=== 여름 RMSE (2024~2025, 4개 지점 평균) ===")
    print(table.round(3).to_string())

    cross = rx.crossing_summary(rec)
    agg = cross.groupby(["config", "margin"])[["actual_events", "hit", "false_alarm", "abs_err_sum"]].sum()
    agg["recall"] = agg["hit"] / agg["actual_events"]
    agg["precision"] = agg["hit"] / (agg["hit"] + agg["false_alarm"]).replace(0, np.nan)
    agg["F1"] = 2 * agg["hit"] / (agg["hit"] + agg["false_alarm"] + agg["actual_events"])
    agg["day_err"] = agg["abs_err_sum"] / agg["hit"].replace(0, np.nan)
    agg.to_csv(out / "crossing_by_margin.csv", encoding="utf-8-sig")
    best = agg.reset_index().loc[lambda t: t.groupby("config")["F1"].idxmax()].set_index("config").reindex(order)
    best.to_csv(out / "crossing_best.csv", encoding="utf-8-sig")
    n_events = int(agg["actual_events"].xs(0.0, level="margin").iloc[0])
    print(f"\n=== 28℃ 도달일: 모델별 최적 여유폭에서의 성능 (실제 도달 {n_events}건) ===")
    print(best[["margin", "recall", "precision", "F1", "day_err"]].round(2).to_string())
    print(f"\n저장 완료: {out}")


if __name__ == "__main__":
    main()
