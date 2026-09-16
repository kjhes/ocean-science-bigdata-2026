"""예측값에 경보 로직을 연결: "우리 모델이 실제로 제때 경보를 냈을까?"

short_term_forecast.py의 1일 뒤 예측(선형회귀)을 alert.py의 경보 판정에
그대로 넣어, 검증기간(2024~2025) 동안 "실제 관측 기준 경보"와
"예측 기준 경보"가 얼마나 일치하는지 비교한다. 평년값(climatology) 기준선은
실제 관측 전체(2021~2025)로 한 번만 계산해 양쪽에 동일하게 사용한다
(기준이 다르면 비교가 공정하지 않으므로).
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, REGIONS, DATE_COL, REGION_COL, TEMP_COL  # noqa: E402
from data.load_data import load_raw_temperature  # noqa: E402
from models.alert import classify_series, climatology_lookup  # noqa: E402
from models.short_term_forecast import run_region  # noqa: E402


def run():
    output = ROOT_DIR / "reports" / "forecast_alert"
    output.mkdir(parents=True, exist_ok=True)

    all_rows = []
    confusion_rows = []
    for region in REGIONS:
        # 평년값 기준선: 실제 관측 전체 기간으로 한 번만 계산 (예측/실측 공통 기준)
        full = load_raw_temperature(region)[[DATE_COL, TEMP_COL]]
        full_clim = climatology_lookup(full)
        clim_by_date = pd.Series(full_clim.to_numpy(), index=pd.DatetimeIndex(full[DATE_COL]))

        fc = run_region(region)
        dates = pd.DatetimeIndex(fc["test_dates"])
        actual = fc["actual"]
        pred = fc["preds"]["linear_regression"]
        clim_ref = clim_by_date.reindex(dates).to_numpy()

        actual_class = classify_series(dates, actual, clim_ref)
        pred_class = classify_series(dates, pred, clim_ref)

        merged = pd.DataFrame({
            DATE_COL: dates,
            REGION_COL: region,
            "actual_temp": actual,
            "predicted_temp": pred,
            "actual_level": actual_class["level_name"],
            "predicted_level": pred_class["level_name"],
        })
        all_rows.append(merged)

        valid = merged.dropna(subset=["actual_level", "predicted_level"])
        match = (valid["actual_level"] == valid["predicted_level"]).mean()
        # 실제로 경보/주의보였던 날 중 예측도 경보/주의보를 냈는지 (재현율 - 놓친 경보가 없는지가 중요)
        real_warn = valid[valid["actual_level"].isin(["주의보", "경보"])]
        caught = (real_warn["predicted_level"].isin(["주의보", "경보"])).mean() if len(real_warn) else np.nan
        confusion_rows.append({"region": region, "n_days": len(valid), "level_match_rate": round(match, 3),
                                "n_actual_warnings": len(real_warn), "warning_recall": round(caught, 3) if caught == caught else None})

    result = pd.concat(all_rows, ignore_index=True)
    result.to_csv(output / "daily_comparison.csv", index=False, encoding="utf-8-sig")
    summary = pd.DataFrame(confusion_rows)
    summary.to_csv(output / "summary.csv", index=False, encoding="utf-8-sig")

    print(summary.to_string(index=False))

    # 2024년 9월 상세 비교 출력
    sep2024 = result[(result[DATE_COL].dt.year == 2024) & (result[DATE_COL].dt.month == 9)]
    print("\n=== 2024년 9월 실제경보 vs 예측경보 (지역별 '경보'/'주의보' 일수) ===")
    print(sep2024.groupby(REGION_COL)[["actual_level", "predicted_level"]]
          .apply(lambda g: pd.Series({
              "actual_경보": (g["actual_level"] == "경보").sum(),
              "예측_경보": (g["predicted_level"] == "경보").sum(),
              "actual_주의보": (g["actual_level"] == "주의보").sum(),
              "예측_주의보": (g["predicted_level"] == "주의보").sum(),
          })).to_string())

    print(f"\n저장 완료: {output}")
    return result, summary


if __name__ == "__main__":
    run()
