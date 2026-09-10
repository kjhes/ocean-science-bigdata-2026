"""2024년 수온 이상값의 원인을 분해하는 분석.

배경
----
평년값 모델이 2025년 테스트에서는 RMSE 1.5~1.8℃로 무난했지만,
2024년을 학습에서 빼고 예측하면 크게 빗나갔다. 원인을 찾기 위해
"2024년이 정확히 무엇이 달랐는가"를 네 가지 각도에서 분해한다.

  1) 여름(7~9월) 평균 수온      -> 평균이 올라갔나?
  2) 여름 최고 수온              -> 정점이 더 높아졌나?
  3) 임계값 초과일수             -> 위험 구간에 머문 날이 늘었나?
  4) 월별 평년 편차              -> 어느 달이 튀었나?

결론(요약)
----------
평균도 최고값도 평년 수준이었다. 튄 것은 **9월**이고,
2024년은 9월 월평균이 8월보다 높았다. 즉 정점이 높아진 것이 아니라
**여름이 늦게까지 끝나지 않았다**. 그래서 28℃ 초과일수만 폭증했다.

실행
----
    python src/analysis/anomaly_2024.py
    python src/analysis/anomaly_2024.py --threshold 28 --output reports/anomaly_2024

주의
----
결측을 보간하지 않는다. 월평균과 초과일수는 **실제 관측일만** 사용하므로
결측이 많은 지역·연도(예: 여수 2023년 8~9월)는 값이 편향될 수 있다.
각 표와 함께 저장되는 `observation_counts.csv`로 관측일 수를 반드시 확인할 것.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import DATE_COL, REGION_COL, TEMP_COL  # noqa: E402
from src.data.load_data import load_all_regions  # noqa: E402

SUMMER_MONTHS = (7, 8, 9)
ANALYSIS_YEARS = (2021, 2025)


def load_analysis_frame(raw_dir: Path | None = None) -> pd.DataFrame:
    """원자료를 읽어 분석 기간(2021~2025)으로 자른다. 보간하지 않는다."""
    df = load_all_regions(raw_dir)
    df = df.copy()
    df[DATE_COL] = pd.to_datetime(df[DATE_COL])
    df["year"] = df[DATE_COL].dt.year
    df["month"] = df[DATE_COL].dt.month
    lo, hi = ANALYSIS_YEARS
    df = df[df["year"].between(lo, hi)]
    # 원자료 경계(2026-01-01 등)와 결측 관측일은 통계에서 제외한다.
    return df.dropna(subset=[TEMP_COL]).reset_index(drop=True)


def summer_table(df: pd.DataFrame, how: str) -> pd.DataFrame:
    """여름(7~9월) 평균 또는 최고 수온을 연도×지역 표로 만든다."""
    summer = df[df["month"].isin(SUMMER_MONTHS)]
    return summer.pivot_table(
        index="year", columns=REGION_COL, values=TEMP_COL, aggfunc=how
    ).round(2)


def exceedance_table(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """여름 중 임계값을 넘은 관측일 수를 연도×지역 표로 만든다."""
    summer = df[df["month"].isin(SUMMER_MONTHS)].copy()
    summer["over"] = summer[TEMP_COL] > threshold
    return summer.pivot_table(
        index="year", columns=REGION_COL, values="over", aggfunc="sum"
    ).astype(int)


def longest_run_table(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """임계값을 연속으로 넘은 최장 구간 길이(일)를 연도×지역 표로 만든다.

    폐사는 순간 최고 온도보다 '얼마나 오래 버텼는가'에 좌우되므로
    단순 초과일수와 별도로 연속 길이를 본다. 결측일은 연속을 끊는다.
    """
    rows = []
    for (region, year), grp in df.groupby([REGION_COL, "year"]):
        grp = grp.sort_values(DATE_COL)
        best = run = 0
        prev_date = None
        for date, temp in zip(grp[DATE_COL], grp[TEMP_COL]):
            contiguous = prev_date is not None and (date - prev_date).days == 1
            if temp > threshold and contiguous:
                run += 1
            elif temp > threshold:
                run = 1
            else:
                run = 0
            best = max(best, run)
            prev_date = date
        rows.append({"year": year, REGION_COL: region, "longest_run": best})
    return (
        pd.DataFrame(rows)
        .pivot_table(index="year", columns=REGION_COL, values="longest_run")
        .astype(int)
    )


def monthly_mean_table(df: pd.DataFrame) -> pd.DataFrame:
    """4개 지역을 평균한 월별 수온을 연도×월 표로 만든다."""
    return df.pivot_table(
        index="year", columns="month", values=TEMP_COL, aggfunc="mean"
    ).round(2)


def monthly_anomaly(df: pd.DataFrame, target_year: int) -> pd.Series:
    """대상 연도의 월평균에서 전체 기간 월평년값을 뺀 편차."""
    normal = df.groupby("month")[TEMP_COL].mean()
    target = df[df["year"] == target_year].groupby("month")[TEMP_COL].mean()
    return (target - normal).round(2)


def observation_counts(df: pd.DataFrame) -> pd.DataFrame:
    """연도×지역 관측일 수. 결측 편향을 확인하는 용도."""
    return df.pivot_table(
        index="year", columns=REGION_COL, values=TEMP_COL, aggfunc="count"
    ).astype(int)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "anomaly_2024")
    parser.add_argument("--threshold", type=float, default=28.0,
                        help="고수온 임계값(℃). 공식 경보 기준으로 교체할 것.")
    parser.add_argument("--target-year", type=int, default=2024)
    args = parser.parse_args()

    df = load_analysis_frame(args.raw_dir)
    args.output.mkdir(parents=True, exist_ok=True)

    tables = {
        "summer_mean": summer_table(df, "mean"),
        "summer_max": summer_table(df, "max"),
        "exceedance_days": exceedance_table(df, args.threshold),
        "longest_run": longest_run_table(df, args.threshold),
        "monthly_mean": monthly_mean_table(df),
        "observation_counts": observation_counts(df),
    }
    anomaly = monthly_anomaly(df, args.target_year)
    anomaly.name = f"{args.target_year}_minus_normal"

    for name, table in tables.items():
        table.to_csv(args.output / f"{name}.csv", encoding="utf-8-sig")
        print(f"\n=== {name} ===")
        print(table.to_string())

    anomaly.to_csv(args.output / "monthly_anomaly.csv", encoding="utf-8-sig")
    print(f"\n=== monthly_anomaly ({args.target_year} - 평년) ===")
    print(anomaly.to_string())

    print(f"\n결과 저장: {args.output}")
    print("주의: 결측을 보간하지 않았다. observation_counts.csv로 관측일 수를 확인할 것.")


if __name__ == "__main__":
    main()
