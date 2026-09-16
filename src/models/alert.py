"""고수온 경보 판정 로직 (국립수산과학원 공식 기준 적용).

기준 (data/external/warning_criteria/high_temp_warning_criteria.csv):
    주의보: 수온 28℃ 도달 / 전일 대비 +3℃ / 평년 대비 +2℃ 급변
    경보  : 수온 28℃ 3일 이상 지속 / 전일 대비 +5℃ / 평년 대비 +3℃ 급변

"관심" 단계는 "28도 도달이 예상되는 7~10일 전"이라는 정의상 미래 예측이
필요하다 (관측만으로는 재구성 불가). 이 모듈은 우선 실제 관측치를 그대로
기준에 대입하는 **주의보/경보 재구성**만 다룬다. 예측값을 입력으로 넣으면
그대로 예측 기반 경보 판정에도 쓸 수 있다 (같은 함수, 다른 입력).
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, REGIONS, DATE_COL, REGION_COL, TEMP_COL  # noqa: E402
from data.load_data import load_all_regions  # noqa: E402

TEMP_THRESHOLD = 28.0
WARNING_JUMP = 3.0     # 주의보: 전일 대비
ALERT_JUMP = 5.0       # 경보: 전일 대비
WARNING_ANOMALY = 2.0  # 주의보: 평년 대비
ALERT_ANOMALY = 3.0    # 경보: 평년 대비
ALERT_SUSTAIN_DAYS = 3  # 경보: 28도 이상 지속일수


def _ref_doy(dates: pd.Series) -> np.ndarray:
    s = pd.DatetimeIndex(dates)
    d = s.dayofyear.to_numpy().astype(float)
    d[(s.is_leap_year) & (s.month > 2)] -= 1
    return d


def climatology_lookup(df: pd.DataFrame, window: int = 3) -> pd.Series:
    """day-of-year(±window) 평년값을 각 관측일에 대응시킨다 (전체 연도 통합, 재구성용)."""
    obs = df.dropna(subset=[TEMP_COL])
    doy = _ref_doy(obs[DATE_COL])
    temp = obs[TEMP_COL].to_numpy(dtype=float)
    all_doy = _ref_doy(df[DATE_COL])
    clim = np.full(len(df), np.nan)
    for i, d in enumerate(all_doy):
        diff = np.abs(doy - d)
        diff = np.minimum(diff, 365 - diff)
        near = diff <= window
        if near.any():
            clim[i] = temp[near].mean()
    return pd.Series(clim, index=df.index)


def classify_series(dates: pd.Series, temps: pd.Series, climatology: pd.Series) -> pd.DataFrame:
    """날짜·수온·(외부에서 주어진) 평년값 세 시리즈로 경보 단계를 판정하는 저수준 함수.

    실제 관측치와 예측치를 **같은 평년값 기준선**으로 공정하게 비교할 수 있도록,
    평년값을 이 함수 밖에서 계산해 넣도록 분리했다 (classify_region은 이 함수를
    감싸는 편의 함수).
    """
    out = pd.DataFrame({DATE_COL: dates, TEMP_COL: temps, "climatology": climatology}).reset_index(drop=True)
    out["anomaly"] = out[TEMP_COL] - out["climatology"]
    out["daily_jump"] = out[TEMP_COL].diff()

    ge28 = out[TEMP_COL] >= TEMP_THRESHOLD
    out["sustained_ge28"] = ge28.rolling(ALERT_SUSTAIN_DAYS, min_periods=ALERT_SUSTAIN_DAYS).apply(
        lambda w: bool(np.all(w)), raw=True).fillna(0).astype(bool)

    is_alert = (
        out["sustained_ge28"]
        | (out["daily_jump"] >= ALERT_JUMP)
        | (out["anomaly"] >= ALERT_ANOMALY)
    )
    is_warning = (
        ge28
        | (out["daily_jump"] >= WARNING_JUMP)
        | (out["anomaly"] >= WARNING_ANOMALY)
    )

    out["level"] = 0
    out.loc[is_warning, "level"] = 2
    out.loc[is_alert, "level"] = 3
    out["level_name"] = out["level"].map({0: "평시", 2: "주의보", 3: "경보"})
    out.loc[out[TEMP_COL].isna(), ["level", "level_name"]] = [np.nan, "판정불가"]
    return out


def classify_region(df: pd.DataFrame) -> pd.DataFrame:
    """지역 하나의 일별 수온 df(date, temperature)를 받아 경보 단계를 붙인다.

    반환 컬럼 추가: climatology, anomaly, daily_jump, sustained_ge28,
                    level (0=평시, 2=주의보, 3=경보), level_name
    """
    df = df.sort_values(DATE_COL).reset_index(drop=True).copy()
    clim = climatology_lookup(df)
    return classify_series(df[DATE_COL], df[TEMP_COL], clim)


def run() -> pd.DataFrame:
    raw = load_all_regions()
    frames = []
    for region in REGIONS:
        sub = raw[raw[REGION_COL] == region][[DATE_COL, TEMP_COL]]
        classified = classify_region(sub)
        classified[REGION_COL] = region
        frames.append(classified)
    result = pd.concat(frames, ignore_index=True)

    output = ROOT_DIR / "reports" / "alert_reconstruction"
    output.mkdir(parents=True, exist_ok=True)
    result.to_csv(output / "daily_alert_levels.csv", index=False, encoding="utf-8-sig")

    yearly = (result.assign(year=result[DATE_COL].dt.year)
              .groupby([REGION_COL, "year", "level_name"]).size()
              .unstack(fill_value=0))
    yearly.to_csv(output / "yearly_level_counts.csv", encoding="utf-8-sig")

    print(yearly.to_string())

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams["font.family"] = next((f for f in ["Malgun Gothic", "AppleGothic", "NanumGothic"] if f in fonts), "DejaVu Sans")

    (output / "figures").mkdir(exist_ok=True)
    for region in REGIONS:
        sub = result[result[REGION_COL] == region]
        fig, ax = plt.subplots(figsize=(14, 4))
        ax.plot(sub[DATE_COL], sub[TEMP_COL], color="#c3c2b7", lw=0.8, zorder=1)
        warn = sub[sub["level"] == 2]
        alert = sub[sub["level"] == 3]
        ax.scatter(warn[DATE_COL], warn[TEMP_COL], color="#eda100", s=8, label="주의보", zorder=2)
        ax.scatter(alert[DATE_COL], alert[TEMP_COL], color="#e34948", s=10, label="경보", zorder=3)
        ax.axhline(28, color="#898781", lw=0.7, linestyle=":")
        ax.set_title(f"{region}: 공식 기준 재구성 경보 이력 (2021~2025)")
        ax.set_ylabel("수온 (℃)")
        ax.legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(output / "figures" / f"{region}_alert_timeline.png", dpi=150)
        plt.close(fig)

    print(f"\n저장 완료: {output}")
    return result


if __name__ == "__main__":
    run()
