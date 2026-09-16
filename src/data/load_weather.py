"""기상청 ASOS 시간자료(기온·강수량·풍속·풍향·일사량) 로딩 모듈.

원자료 위치: 프로젝트 루트의 `기상 데이터/{지역}/ASOS_{station}_{code}_{year}_hourly.csv`
    예) 기상 데이터/완도/ASOS_Wando_170_2021_hourly.csv

원자료 컬럼 (기상청 ASOS 시간자료, cp949 인코딩):
    지점, 지점명, 일시, 기온(°C), 기온 QC플래그, 강수량(mm), 강수량 QC플래그,
    풍속(m/s), 풍속 QC플래그, 풍향(16방위), 풍향 QC플래그, 일사(MJ/m2), 일사 QC플래그

2026-09-16 데이터 점검 결과 (수동 검증, scratch 분석):
    - 기온·풍속·풍향: 결측 거의 없음 (연 8760시간 중 0~수백 건) → 사용 가능
    - 강수량: 결측 약 90%. 처음엔 "결측=무강수(0mm)"로 가정했다가, 명시적 0.0도
      따로 기록되어 있어(예: 여수 2021년 329건) 한 번 기각했음. 이후 두 가지로
      재검증해 결론을 뒤집음:
        1) 월별 결측률이 뚜렷한 계절 패턴을 보임 (겨울 95~97% vs 장마·태풍철인
           여름 84~87%) — 비가 잦은 계절일수록 결측이 줄어듦
        2) 실제 기록된 폭우 사건으로 대조 검증: 2023년 7월 전남 집중호우 기간
           (완도 합계 37.6mm, 여수 85.8mm 기록), 2022년 태풍 힌남노 상륙 기간
           (남해 최대 시간당 60.2mm·합계 299.8mm로 상륙지 부산과 가장 가까운
           남해가 제일 크게 기록 - 지리적으로 정합적)
      → **결측 = 무강수(0mm)로 최종 확정.** 아래 집계에서 결측을 0으로 채워 사용.
    - 일사량: 지역별로 관측 시작 시점이 다름 (남해는 5년 내내 전무, 완도는
      2024년부터, 통영은 2023년부터, 여수만 비교적 온전) → 4개 지역 공통
      변수로 사용 불가. 지역별로 가용 여부가 다르다는 점을 반드시 확인하고 써야 함.

이 파일은 기온·풍속·풍향·강수량을 일별로 집계해 반환한다.
"""
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import ROOT_DIR, REGIONS, DATE_COL, REGION_COL  # noqa: E402

WEATHER_DIR = ROOT_DIR / "기상 데이터"

# 표준 지역명 -> 기상 데이터 폴더명 (수온 데이터와 폴더명 표기가 다름에 유의:
# 여기서는 "남해"가 폴더명, 표준 지역명은 "남해군")
WEATHER_FOLDER_MAP = {
    "완도": "완도",
    "여수": "여수",
    "통영": "통영",
    "남해군": "남해",
}

RAW_TIME_COL = "일시"
RAW_TEMP_COL = "기온(°C)"
RAW_RAIN_COL = "강수량(mm)"
RAW_WIND_SPEED_COL = "풍속(m/s)"
RAW_WIND_DIR_COL = "풍향(16방위)"
RAW_SOLAR_COL = "일사(MJ/m2)"

# 결측=무강수(0mm)로 확정됨 (모듈 설명 참고). 명시적으로 상수화해 왜 0으로
# 채우는지 나중에 코드만 봐도 알 수 있게 한다.
RAIN_NA_MEANS_ZERO = True


def load_raw_weather(region: str, weather_dir: Optional[Path] = None) -> pd.DataFrame:
    """지정한 지역의 연도별 시간자료 CSV를 모두 읽어 하나로 합친다 (시간 단위, 원본 그대로)."""
    if region not in REGIONS:
        raise ValueError(f"알 수 없는 지역: {region}. REGIONS={REGIONS} 중에서 선택하세요.")

    weather_dir = weather_dir or WEATHER_DIR
    folder = WEATHER_FOLDER_MAP[region]
    region_dir = weather_dir / folder
    csv_files = sorted(region_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(
            f"{region_dir} 에서 CSV 파일을 찾을 수 없습니다. "
            f"'기상 데이터/{folder}/' 아래에 ASOS 시간자료가 있는지 확인하세요."
        )

    frames = []
    for f in csv_files:
        df = pd.read_csv(f, encoding="cp949")
        frames.append(df)
    raw = pd.concat(frames, ignore_index=True)
    raw[RAW_TIME_COL] = pd.to_datetime(raw[RAW_TIME_COL])
    raw = raw.rename(columns={RAW_TIME_COL: "datetime"})
    raw = raw.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="first")
    return raw.reset_index(drop=True)


def _circular_mean_deg(degrees: pd.Series) -> float:
    """풍향(도) 평균은 산술평균이 아니라 벡터 평균으로 계산해야 한다 (0도와 360도가 붙어있으므로)."""
    rad = np.deg2rad(degrees.dropna().to_numpy())
    if rad.size == 0:
        return np.nan
    mean_rad = np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())
    return float(np.rad2deg(mean_rad) % 360)


def load_daily_weather(region: str, weather_dir: Optional[Path] = None,
                        include_solar: bool = False) -> pd.DataFrame:
    """시간자료를 일별로 집계한다.

    반환 컬럼: date, region, air_temp_mean, air_temp_min, air_temp_max,
               wind_speed_mean, wind_dir_mean_deg, rain_sum
               (+ include_solar=True 시 solar_sum)

    강수량 결측은 무강수(0mm)로 확정되어 0으로 채운 뒤 일별 합계를 낸다
    (위 모듈 설명의 계절 패턴·실제 호우 사건 대조 검증 참고).
    일사량은 지역별 가용 기간이 달라 기본값은 제외(include_solar=False); 필요 시
    해당 지역의 관측 시작 연도를 반드시 확인하고 사용할 것.
    """
    raw = load_raw_weather(region, weather_dir)
    raw["date"] = raw["datetime"].dt.floor("D")
    if RAIN_NA_MEANS_ZERO:
        raw[RAW_RAIN_COL] = raw[RAW_RAIN_COL].fillna(0.0)

    daily = raw.groupby("date").agg(
        air_temp_mean=(RAW_TEMP_COL, "mean"),
        air_temp_min=(RAW_TEMP_COL, "min"),
        air_temp_max=(RAW_TEMP_COL, "max"),
        wind_speed_mean=(RAW_WIND_SPEED_COL, "mean"),
        rain_sum=(RAW_RAIN_COL, "sum"),
    )
    wind_dir = raw.groupby("date")[RAW_WIND_DIR_COL].apply(_circular_mean_deg)
    daily["wind_dir_mean_deg"] = wind_dir

    if include_solar:
        daily["solar_sum"] = raw.groupby("date")[RAW_SOLAR_COL].sum(min_count=1)

    daily = daily.reset_index().rename(columns={"date": DATE_COL})
    daily[REGION_COL] = region
    return daily


def load_all_daily_weather(weather_dir: Optional[Path] = None, include_solar: bool = False) -> pd.DataFrame:
    """REGIONS 전체의 일별 기상자료를 합친다."""
    frames = []
    for region in REGIONS:
        try:
            frames.append(load_daily_weather(region, weather_dir, include_solar=include_solar))
        except FileNotFoundError as e:
            print(f"[경고] {region} 기상자료를 건너뜁니다: {e}")
    if not frames:
        raise FileNotFoundError("로드된 기상자료가 없습니다. '기상 데이터/' 폴더 구성을 확인하세요.")
    return pd.concat(frames, ignore_index=True).sort_values([REGION_COL, DATE_COL]).reset_index(drop=True)


if __name__ == "__main__":
    df = load_all_daily_weather()
    print(df.head())
    print(df.groupby("region")[["air_temp_mean", "wind_speed_mean"]].agg(["count", "mean"]))
    print("결측치:")
    print(df.groupby("region")[["air_temp_mean", "wind_speed_mean", "wind_dir_mean_deg"]].apply(lambda g: g.isna().sum()))
