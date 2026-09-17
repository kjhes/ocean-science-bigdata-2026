"""기상청 단기예보 조회서비스에서 BluePulse AI 연구지역의 미래 기상예보를 수집한다.

공공데이터포털 '기상청 단기예보 조회서비스'의 getVilageFcst 사용.
인증키는 저장소에 올리지 않고 프로젝트 루트 .env의 KMA_FORECAST_API_KEY로 관리한다.

용도:
- 실시간 +1일/+3일 수온예측의 미래 기상 입력
- TMP(기온), WSD(풍속), PCP(강수량)를 받아 일별 변수로 집계

주의:
현재 API로 받은 예보를 과거 2021~2025 검증자료인 것처럼 사용하지 않는다.
과거 검증에는 당시 발표된 예보 아카이브가 확보된 경우에만 사용한다.
"""
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
import os

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

BASE_URL = (
    "https://apis.data.go.kr/1360000/"
    "VilageFcstInfoService_2.0/getVilageFcst"
)
SERVICE_KEY = os.environ.get("KMA_FORECAST_API_KEY", "")
OUTPUT_DIR = ROOT_DIR / "reports" / "weather_forecast_realtime"

REGIONS = {
    "wando": {"name": "완도", "nx": 55, "ny": 57},
    "yeosu": {"name": "여수", "nx": 74, "ny": 65},
    "tongyeong": {"name": "통영", "nx": 86, "ny": 67},
    "namhae": {"name": "남해군", "nx": 80, "ny": 65},
}

BASE_TIMES = [2, 5, 8, 11, 14, 17, 20, 23]
CATEGORIES = {"TMP", "WSD", "PCP"}


def latest_available_base(now: Optional[datetime] = None) -> tuple[str, str]:
    """현재 시각 기준 사용 가능한 가장 최근 단기예보 발표시각을 고른다."""
    now = now or datetime.now()
    available = [
        h for h in BASE_TIMES
        if now >= now.replace(hour=h, minute=15, second=0, microsecond=0)
    ]
    if available:
        base = now.replace(hour=max(available), minute=0, second=0, microsecond=0)
    else:
        yesterday = now - timedelta(days=1)
        base = yesterday.replace(hour=23, minute=0, second=0, microsecond=0)
    return base.strftime("%Y%m%d"), base.strftime("%H%M")


def _pcp_to_float(value) -> float:
    """PCP 문자열을 mm 숫자로 변환한다. 정량 변환이 불가능한 값은 NaN."""
    if value is None:
        return float("nan")
    text = str(value).strip()
    if text in {"강수없음", "없음", "0", "0.0"}:
        return 0.0
    text = text.replace("mm", "").strip()
    try:
        return float(text)
    except ValueError:
        return float("nan")


def request_forecast(
    region_code: str,
    base_date: Optional[str] = None,
    base_time: Optional[str] = None,
) -> pd.DataFrame:
    """한 지역의 단기예보 TMP/WSD/PCP 원자료를 반환한다."""
    if region_code not in REGIONS:
        raise ValueError(f"알 수 없는 지역 코드: {region_code}")
    if not SERVICE_KEY:
        raise RuntimeError("KMA_FORECAST_API_KEY가 .env에 없습니다.")

    if base_date is None or base_time is None:
        base_date, base_time = latest_available_base()

    info = REGIONS[region_code]
    params = {
        "serviceKey": SERVICE_KEY,
        "pageNo": 1,
        "numOfRows": 1000,
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": info["nx"],
        "ny": info["ny"],
    }

    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    header = data.get("response", {}).get("header", {})
    if str(header.get("resultCode")) != "00":
        raise RuntimeError(
            f"기상청 API 오류: {header.get('resultCode')} {header.get('resultMsg')}"
        )

    items = (
        data.get("response", {})
        .get("body", {})
        .get("items", {})
        .get("item", [])
    )

    rows = []
    for item in items:
        category = item.get("category")
        if category not in CATEGORIES:
            continue

        rows.append({
            "region_code": region_code,
            "region": info["name"],
            "base_date": item.get("baseDate", base_date),
            "base_time": item.get("baseTime", base_time),
            "forecast_datetime": pd.to_datetime(
                str(item.get("fcstDate"))
                + str(item.get("fcstTime")).zfill(4),
                format="%Y%m%d%H%M",
                errors="coerce",
            ),
            "category": category,
            "value": item.get("fcstValue"),
            "nx": info["nx"],
            "ny": info["ny"],
        })

    return pd.DataFrame(rows)


def to_daily_forecast(raw: pd.DataFrame) -> pd.DataFrame:
    """시간별 TMP/WSD/PCP를 수온모델용 일별 변수로 집계한다."""
    if raw.empty:
        return pd.DataFrame()

    df = raw.copy()
    df["date"] = df["forecast_datetime"].dt.floor("D")
    df["numeric"] = pd.to_numeric(df["value"], errors="coerce")

    pcp_mask = df["category"] == "PCP"
    df.loc[pcp_mask, "numeric"] = (
        df.loc[pcp_mask, "value"].map(_pcp_to_float)
    )

    records = []
    for (region_code, region, date), group in df.groupby(
        ["region_code", "region", "date"]
    ):
        tmp = group.loc[group["category"] == "TMP", "numeric"]
        wind = group.loc[group["category"] == "WSD", "numeric"]
        rain = group.loc[group["category"] == "PCP", "numeric"]

        records.append({
            "region_code": region_code,
            "region": region,
            "date": date,
            "air_temp_forecast_mean": tmp.mean(),
            "air_temp_forecast_min": tmp.min(),
            "air_temp_forecast_max": tmp.max(),
            "wind_speed_forecast_mean": wind.mean(),
            "rain_forecast_sum": rain.sum(min_count=1),
            "n_tmp": int(tmp.notna().sum()),
            "n_wsd": int(wind.notna().sum()),
            "n_pcp": int(rain.notna().sum()),
        })

    return (
        pd.DataFrame(records)
        .sort_values(["region", "date"])
        .reset_index(drop=True)
    )


def fetch_region(
    region_code: str,
    output_dir: Optional[Path] = None,
) -> tuple[Path, Path]:
    """한 지역 예보의 시간별 원자료와 일별 집계 CSV를 저장한다."""
    raw = request_forecast(region_code)
    daily = to_daily_forecast(raw)

    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    raw_path = output_dir / f"{region_code}_kma_{stamp}_hourly.csv"
    daily_path = output_dir / f"{region_code}_kma_{stamp}_daily.csv"

    raw.to_csv(raw_path, index=False, encoding="utf-8-sig")
    daily.to_csv(daily_path, index=False, encoding="utf-8-sig")
    return raw_path, daily_path


def main():
    for code, info in REGIONS.items():
        try:
            raw_path, daily_path = fetch_region(code)
            print(f"[{info['name']}] 시간별: {raw_path}")
            print(f"[{info['name']}] 일별:   {daily_path}")
        except Exception as exc:
            print(f"[{info['name']}] 실패: {exc}")


if __name__ == "__main__":
    main()
