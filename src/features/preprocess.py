"""수온 데이터 전처리 모듈.

기획서 "1. 수온 데이터 수집 및 전처리" 항목에 대응:
- 결측치 및 이상치 처리
- 날짜/시간 기준 정렬
- 지역별 기초 통계(평균/최고/계절별) 산출
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import DATE_COL, REGION_COL, TEMP_COL  # noqa: E402


def sort_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """지역별로 날짜 기준 정렬."""
    return df.sort_values([REGION_COL, DATE_COL]).reset_index(drop=True)


def handle_missing_values(df: pd.DataFrame, method: str = "interpolate", max_gap: int = 3) -> pd.DataFrame:
    """결측치 처리.

    method:
        "interpolate" : 양 끝 관측이 있는 최대 max_gap일 구간만 보간 (EDA용)
        "drop"        : 결측 행 제거
        "ffill"       : 직전 값으로 채움
    """
    if max_gap < 1:
        raise ValueError("max_gap은 1 이상이어야 합니다.")
    df = sort_by_date(df)
    if method == "drop":
        return df.dropna(subset=[TEMP_COL])

    filled = []
    for region, g in df.groupby(REGION_COL):
        g = g.set_index(DATE_COL)
        # 날짜 행 자체가 빠진 경우도 결측으로 포함한다.
        g = g.reindex(pd.date_range(g.index.min(), g.index.max(), freq="D"))
        g.index.name = DATE_COL
        if method == "interpolate":
            missing = g[TEMP_COL].isna()
            groups = missing.ne(missing.shift()).cumsum()
            lengths = missing.groupby(groups).transform("sum")
            candidate = g[TEMP_COL].interpolate(method="time", limit_area="inside")
            g.loc[missing & (lengths <= max_gap), TEMP_COL] = candidate
        elif method == "ffill":
            g[TEMP_COL] = g[TEMP_COL].ffill(limit=max_gap)
        else:
            raise ValueError(f"알 수 없는 method: {method}")
        g = g.reset_index()
        g[REGION_COL] = region
        filled.append(g)
    return pd.concat(filled, ignore_index=True)


def remove_outliers_iqr(df: pd.DataFrame, k: float = 1.5) -> pd.DataFrame:
    """지역별 IQR 기준 이상치 제거.

    수온은 계절성이 강해 전체 데이터 기준 IQR은 부적합할 수 있음.
    TODO: 계절/월별 IQR로 개선 검토 (탐색적 분석 결과에 따라 조정).
    """
    cleaned = []
    for region, g in df.groupby(REGION_COL):
        q1, q3 = g[TEMP_COL].quantile([0.25, 0.75])
        iqr = q3 - q1
        lower, upper = q1 - k * iqr, q3 + k * iqr
        g = g[(g[TEMP_COL] >= lower) & (g[TEMP_COL] <= upper)]
        cleaned.append(g)
    return pd.concat(cleaned, ignore_index=True)


def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    """연/월/일/계절 등 시계열 분석에 쓸 파생 변수 추가."""
    df = df.copy()
    df["year"] = df[DATE_COL].dt.year
    df["month"] = df[DATE_COL].dt.month
    df["doy"] = df[DATE_COL].dt.dayofyear

    def season(m):
        if m in (12, 1, 2):
            return "겨울"
        if m in (3, 4, 5):
            return "봄"
        if m in (6, 7, 8):
            return "여름"
        return "가을"

    df["season"] = df["month"].apply(season)
    return df


def region_summary(df: pd.DataFrame) -> pd.DataFrame:
    """지역별 평균/최고/최저 수온 등 기초 통계 (기획서 '기초 분석' 대응)."""
    return (
        df.groupby(REGION_COL)[TEMP_COL]
        .agg(mean="mean", max="max", min="min", std="std", count="count")
        .round(2)
        .reset_index()
    )


def preprocess_pipeline(df: pd.DataFrame) -> pd.DataFrame:
    """EDA 전용: 긴 결측과 극값을 보존한다. 예측 평가에는 사용하지 않는다.

    max_gap=3은 연구용 표시 규칙이며 공식적인 보간 허용 기준이 아니다.
    예측은 run_forecast.py에서 분할 후 관측값만 학습한다.
    """
    df = sort_by_date(df)
    df = handle_missing_values(df, method="interpolate")
    df = add_calendar_features(df)
    return df
