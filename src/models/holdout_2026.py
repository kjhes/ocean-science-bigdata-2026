"""최종 검증: 모델 선택에 한 번도 쓰지 않은 2026년 여름으로 성능 확인.

지금까지 성능(예: +3일 예측 1℃ 이내 약 80%)은 2024~2025년으로 쟀고, 모델 구성도 그 결과를 보고
골랐다. 그 수치가 부풀려지지 않았는지 2026년 6~9월(수과원 실시간 조회로 받은 자료)로 다시 잰다.

모델: 기존+기간평균패턴, 20℃ 이상 고수온 전용 모델 전환 (long_history_experiment.py 후보)
  - 2012~2023 학습: 2024~2025에서 평가했던 것과 동일한 모델
  - 2012~2025 학습: 앱에 넣을 최종 모델
비교 기준: 지속성(오늘 수온이 그대로 유지된다고 예측)
"""
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, REGIONS  # noqa: E402
from models.pattern_experiment import SUMMER_MONTHS  # noqa: E402
from models import recursive_experiment as rx  # noqa: E402

TEST_YEARS = [2026]
TRAIN_SETS = {"2012~2023 학습": list(range(2012, 2024)), "2012~2025 학습(최종)": list(range(2012, 2026))}
MODEL = ("기존+기간평균패턴", 20.0)
MARGINS = [0.0, 0.5, 0.75, 1.0]
REFERENCE_2024_25 = {1: 0.97, 3: 0.78, 5: 0.67, 7: 0.50}  # 앞서 보고한 '오차 1℃ 이내' 비율 (7일 1℃ 이상 상승 중인 날 기준)


def summarize(rec: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for h, g in rec.groupby("h"):
        err = g["pred"] - g["actual"]
        a_rise, p_rise = g["actual"] - g["today"], g["pred"] - g["today"]
        rows.append({"모델": label, "h": h, "예보일수": g["issue_date"].nunique() // max(g["region"].nunique(), 1),
                     "RMSE": float(np.sqrt((err ** 2).mean())), "오차1℃이내": float((err.abs() <= 1).mean()),
                     "오차0.5℃이내": float((err.abs() <= 0.5).mean()),
                     "방향적중": float(((a_rise > 0.2) == (p_rise > 0.2)).mean())})
    return pd.DataFrame(rows)


def main():
    warnings.filterwarnings("ignore", category=UserWarning)
    rx.MARGINS = MARGINS
    out = ROOT_DIR / "reports" / "holdout_2026"
    out.mkdir(parents=True, exist_ok=True)

    recs = []
    for region in REGIONS:
        df = rx.load_series(region, long_history=True)
        for tname, years in TRAIN_SETS.items():
            runs = {tname: MODEL}
            recs.append(rx.run_series(df, region, runs=runs, train_years=years, test_years=TEST_YEARS))
    rec = pd.concat(recs, ignore_index=True)
    rec.to_csv(out / "predictions.csv", index=False, encoding="utf-8-sig")
    scored = rec[rec["target_date"].dt.month.isin(SUMMER_MONTHS)].dropna(subset=["pred", "actual"])

    tables = [summarize(g, name) for name, g in scored.groupby("config", sort=False)]
    base = scored[scored["config"] == list(TRAIN_SETS)[0]].assign(pred=lambda d: d["today"])
    tables.append(summarize(base, "지속성(오늘값 유지)"))
    t = pd.concat(tables, ignore_index=True)
    t.to_csv(out / "accuracy_by_horizon.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 200)
    print(f"=== 2026년 여름 검증 (평가 기간 {scored['target_date'].min().date()} ~ {scored['target_date'].max().date()}, 4개 지점) ===")
    for h in [1, 3, 5, 7]:
        print(f"\n--- +{h}일 (2024~2025 평가 때 '1℃ 이내' 약 {REFERENCE_2024_25[h]:.0%}) ---")
        print(t[t["h"] == h].drop(columns="h").round(3).to_string(index=False))

    print("\n=== 지점별 +3일 '오차 1℃ 이내' 비율 ===")
    h3 = scored[scored["h"] == 3]
    print(h3.assign(ok=(h3["pred"] - h3["actual"]).abs() <= 1).groupby(["config", "region"])["ok"].mean()
          .unstack("region").round(2).to_string())

    cross = rx.crossing_summary(rec)
    agg = cross.groupby(["config", "margin"])[["actual_events", "hit", "false_alarm", "abs_err_sum"]].sum()
    agg["recall"] = agg["hit"] / agg["actual_events"].replace(0, np.nan)
    agg["precision"] = agg["hit"] / (agg["hit"] + agg["false_alarm"]).replace(0, np.nan)
    agg["day_err"] = agg["abs_err_sum"] / agg["hit"].replace(0, np.nan)
    agg.to_csv(out / "crossing_28c.csv", encoding="utf-8-sig")
    n_events = int(agg["actual_events"].xs(0.0, level="margin").iloc[0])
    print(f"\n=== 2026년 28℃ 도달일 예측 (실제 도달 {n_events}건) ===")
    print(agg[["hit", "false_alarm", "recall", "precision", "day_err"]].round(2).to_string())
    print("\n2026년 여름 지점별 최고 수온:")
    summer = scored.drop_duplicates(["region", "target_date"])
    print(summer.groupby("region")["actual"].max().round(1).to_string())
    print(f"\n저장 완료: {out}")


if __name__ == "__main__":
    main()
