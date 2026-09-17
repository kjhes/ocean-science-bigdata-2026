"""ROMS 수치예측모델 API에서 연구지역 주변 실시간(향후) 해양 예측자료를 받아온다.

원작성: 김예린 (roms_download.py). 인증키를 .env로 분리하고 완도 좌표
소수점 정밀도 문제(아래 참고)를 수정해 src/data/ 구조에 맞춰 정리함.

⚠️ 중요한 한계 (docs/단기예측_환경변수_검증.md 7-2절 참고):
    이 API는 "호출 시점 기준 향후 8일"의 예보만 제공하고 과거 데이터
    조회는 지원하지 않는다. 그래서 2021~2023 학습 데이터에 ROMS 값을
    넣는 용도로는 쓸 수 없고, 실행 시점 이후 매일 수집해 우리 자체
    예측·실측과 비교하는 "실시간 벤치마크" 용도로만 활용 가능하다.

버그 수정 메모: ROMS API는 위경도 소수점 자릿수가 너무 많으면
(예: 34.315556) INVALID_REQUEST_PARAMETER_ERROR를 반환한다. 소수 2자리로
반올림하면 정상 동작함을 확인함(2026-09-17). 아래 REGIONS는 전부 2자리로
통일해 이 문제를 피한다.
"""
from pathlib import Path
from typing import Optional
import csv
import math
import os
from datetime import datetime

import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

BASE_URL = os.environ.get("ROMS_API_ENDPOINT", "https://apis.data.go.kr/1192136/roms") + "/GetRomsApiService"
SERVICE_KEY = os.environ.get("ROMS_API_KEY", "")

OUTPUT_DIR = ROOT_DIR / "reports" / "roms_realtime"

# ROMS API가 소수점 자릿수 많은 좌표를 거부하는 문제 때문에 2자리로 통일
REGIONS = {
    "wando": {"name": "완도", "lat": 34.32, "lon": 126.76},
    "yeosu": {"name": "여수", "lat": 34.74, "lon": 127.73},
    "tongyeong": {"name": "통영", "lat": 34.83, "lon": 128.43},
    "namhae": {"name": "남해", "lat": 34.71, "lon": 128.05},
}


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _find_items(data):
    if isinstance(data, dict):
        if "items" in data:
            items = data["items"]
            if isinstance(items, list):
                return items
            if isinstance(items, dict) and "item" in items:
                item = items["item"]
                return item if isinstance(item, list) else [item]
        for value in data.values():
            result = _find_items(value)
            if result:
                return result
    elif isinstance(data, list):
        if data and isinstance(data[0], dict) and ("predcDt" in data[0] or "wtem" in data[0]):
            return data
        for value in data:
            result = _find_items(value)
            if result:
                return result
    return []


def request_roms(lat: float, lon: float, delta: float = 0.1) -> list:
    """ROMS API에 좌표 주변(±delta도) 예측자료를 요청한다."""
    if not SERVICE_KEY:
        raise RuntimeError("ROMS_API_KEY가 .env에 없습니다.")
    params = {
        "serviceKey": SERVICE_KEY, "type": "json",
        "ymin": round(lat - delta, 2), "ymax": round(lat + delta, 2),
        "xmin": round(lon - delta, 2), "xmax": round(lon + delta, 2),
        "pageNo": 1, "numOfRows": 300,
    }
    r = requests.get(BASE_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    header = data.get("header", {}) if isinstance(data, dict) else {}
    if str(header.get("resultCode")) not in ("00", "None"):
        raise RuntimeError(f"ROMS API 오류: {header.get('resultCode')} {header.get('resultMsg')}")
    return _find_items(data)


def find_nearest_grid(rows: list, target_lat: float, target_lon: float) -> Optional[dict]:
    grids = {}
    for row in rows:
        try:
            lat, lon = float(row["lat"]), float(row["lot"])
        except (KeyError, TypeError, ValueError):
            continue
        grids.setdefault((lat, lon), haversine(target_lat, target_lon, lat, lon))
    if not grids:
        return None
    nearest = min(grids, key=grids.get)
    return {"lat": nearest[0], "lon": nearest[1], "distance": grids[nearest]}


def fetch_region(region_code: str, output_dir: Optional[Path] = None) -> Path:
    """한 지역의 ROMS 예보자료를 받아 가장 가까운 격자를 골라 CSV로 저장한다.

    완도처럼 격자가 촘촘한(다도해) 지역은 ±0.1도 범위 요청 시 서버가 504
    Gateway Timeout을 반환하는 경우가 있어(2026-09-17 확인), 범위를 점점
    좁혀가며 재시도한다.
    """
    info = REGIONS[region_code]
    rows = None
    last_error = None
    for delta in (0.1, 0.05, 0.02):
        try:
            rows = request_roms(info["lat"], info["lon"], delta=delta)
            break
        except Exception as e:
            last_error = e
    if not rows:
        raise RuntimeError(f"{info['name']}: ROMS 자료를 받지 못했습니다. ({last_error})")

    grid = find_nearest_grid(rows, info["lat"], info["lon"])
    selected = sorted(
        (row for row in rows if abs(float(row["lat"]) - grid["lat"]) < 1e-6
         and abs(float(row["lot"]) - grid["lon"]) < 1e-6),
        key=lambda x: x.get("predcDt", ""),
    )

    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    filename = output_dir / f"{region_code}_roms_{today}.csv"

    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["지역", "기준위도", "기준경도", "ROMS위도", "ROMS경도",
                          "거리_km", "예측일시", "예측수온_C", "유향_deg", "유속_m_s"])
        for row in selected:
            writer.writerow([info["name"], info["lat"], info["lon"], grid["lat"], grid["lon"],
                              round(grid["distance"], 3), row.get("predcDt"), row.get("wtem"),
                              row.get("crdir"), row.get("crsp")])
    return filename


def main():
    for region_code in REGIONS:
        info = REGIONS[region_code]
        try:
            path = fetch_region(region_code)
            print(f"[{info['name']}] 저장 완료: {path}")
        except Exception as e:
            print(f"[{info['name']}] 실패: {e}")


if __name__ == "__main__":
    main()
