"""수온 데이터 시각화 모듈.

기획서 "지역별 수온 변화 시각화" 대응.
matplotlib/seaborn 기반의 재사용 가능한 플롯 함수 모음.
"""
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import DATE_COL, REGION_COL, TEMP_COL, FIGURES_DIR, REGIONS, REGION_COLORS  # noqa: E402

sns.set_theme(style="whitegrid")
plt.rcParams["axes.unicode_minus"] = False
# 한글 폰트: 환경에 맞는 폰트로 조정 필요 (Windows 기준 'Malgun Gothic')
plt.rcParams["font.family"] = "Malgun Gothic"
# 그리드/축은 은은하게 (recessive grid) - 데이터가 주인공이 되도록
plt.rcParams["grid.color"] = "#e1e0d9"
plt.rcParams["axes.edgecolor"] = "#c3c2b7"


def plot_region_trend(df: pd.DataFrame, save: bool = False, filename: str = "region_trend.png"):
    """지역별 수온 시계열 추이를 한 그래프에 비교.

    색상은 REGIONS 순서에 고정된 REGION_COLORS를 사용한다 (지역이 필터링되어도
    같은 지역은 항상 같은 색을 유지하도록 - 색은 순위가 아닌 '정체성'을 따른다).
    """
    fig, ax = plt.subplots(figsize=(12, 5))
    for region in REGIONS:
        g = df[df[REGION_COL] == region]
        if g.empty:
            continue
        ax.plot(g[DATE_COL], g[TEMP_COL], label=region, linewidth=1.3,
                 color=REGION_COLORS.get(region))
    ax.set_title("지역별 수온 변화 추이")
    ax.set_xlabel("날짜")
    ax.set_ylabel("수온 (℃)")
    ax.legend()
    fig.tight_layout()
    if save:
        fig.savefig(FIGURES_DIR / filename, dpi=150)
    return fig


def plot_monthly_boxplot(df: pd.DataFrame, region: str, save: bool = False):
    """특정 지역의 월별 수온 분포 (계절 변화 확인용)."""
    sub = df[df[REGION_COL] == region].copy()
    sub["month"] = sub[DATE_COL].dt.month
    fig, ax = plt.subplots(figsize=(10, 5))
    sns.boxplot(data=sub, x="month", y=TEMP_COL, ax=ax)
    ax.set_title(f"{region} 월별 수온 분포")
    ax.set_xlabel("월")
    ax.set_ylabel("수온 (℃)")
    fig.tight_layout()
    if save:
        fig.savefig(FIGURES_DIR / f"{region}_monthly_boxplot.png", dpi=150)
    return fig


def plot_region_comparison_bar(summary_df: pd.DataFrame, save: bool = False):
    """지역별 평균/최고 수온 막대그래프 비교 (preprocess.region_summary 결과 사용).

    평균/최고는 같은 지역의 서로 다른 '값'이지 서로 다른 지역이 아니므로,
    지역색이 아닌 명도 대비(진하게=평균, 연하게=최고)로 구분한다.
    """
    fig, ax = plt.subplots(figsize=(8, 5))
    x = range(len(summary_df))
    ax.bar([i - 0.2 for i in x], summary_df["mean"], width=0.4, label="평균", color="#2a78d6")
    ax.bar([i + 0.2 for i in x], summary_df["max"], width=0.4, label="최고", color="#9ec5f4")
    ax.set_xticks(list(x))
    ax.set_xticklabels(summary_df[REGION_COL])
    ax.set_ylabel("수온 (℃)")
    ax.set_title("지역별 평균/최고 수온 비교")
    ax.legend()
    fig.tight_layout()
    if save:
        fig.savefig(FIGURES_DIR / "region_comparison_bar.png", dpi=150)
    return fig


def plot_high_temp_alert_days(yearly_summary_df: pd.DataFrame, save: bool = False):
    """연도별 고수온 경보 일수를 지역별로 비교 (parse_yearly_summary.py 결과 사용).

    '전체' 행(5년 합계)은 연도별 추세와 스케일이 달라 함께 그리면 오독을
    유발하므로 제외한다.
    """
    sub = yearly_summary_df[yearly_summary_df["year"] != "전체"].copy()
    sub["year"] = sub["year"].astype(int)
    years = sorted(sub["year"].unique())

    fig, ax = plt.subplots(figsize=(10, 5))
    n_regions = len(REGIONS)
    width = 0.8 / n_regions
    for i, region in enumerate(REGIONS):
        g = sub[sub[REGION_COL] == region].set_index("year").reindex(years)
        offsets = [y - 0.4 + width * i + width / 2 for y in years]
        ax.bar(offsets, g["high_temp_alert_days"], width=width, label=region,
               color=REGION_COLORS.get(region))
    ax.set_xticks(years)
    ax.set_xlabel("연도")
    ax.set_ylabel("고수온 경보 일수")
    ax.set_title("지역별 연도별 고수온 경보 발생 일수")
    ax.legend()
    fig.tight_layout()
    if save:
        fig.savefig(FIGURES_DIR / "high_temp_alert_days.png", dpi=150)
    return fig


def plot_forecast_vs_actual(dates, y_true, y_pred, title: str = "예측 vs 실제", save: bool = False, filename: str = "forecast_vs_actual.png"):
    """예측 모델 검증용: 실제값과 예측값 비교 플롯."""
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(dates, y_true, label="실제", linewidth=1.5)
    ax.plot(dates, y_pred, label="예측", linewidth=1.5, linestyle="--")
    ax.set_title(title)
    ax.set_xlabel("날짜")
    ax.set_ylabel("수온 (℃)")
    ax.legend()
    fig.tight_layout()
    if save:
        fig.savefig(FIGURES_DIR / filename, dpi=150)
    return fig
