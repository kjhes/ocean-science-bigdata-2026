"""기상청 API허브 '해양기상월보 - 일별(파고부이)기상자료조회'로 파고부이 일평균 수온을 받는다.

목적: 수과원 수온(2021~2025)만으로는 여름 표본이 부족해(고수온 구간 학습 시 통영 26℃ 이상 44일),
각 지역 근처 기상청 파고부이의 과거 수온(2016-09~)으로 학습 기간을 늘릴 수 있는지 검토.
파고부이는 수과원 양식장 관측소와 위치가 다르므로(10~24km), 2021~2025 겹치는 기간 비교 후 사용 여부 결정.

- 월보 발간 기간: 2016-09부터 (그 이전은 "발간되지 않은 기간" 응답)
- 수온센서 수심 0.3m (지점일람표 ht_tw=-0.3) - 수과원 표층(wtemS)과 같은 표층
- 값 뒤의 기호(>, ], ) 등)는 월보 품질기호로 보이며 의미 미확인 - tw_flag 열에 원문 그대로 보관

인증키: 저장소 루트 `.env`의 KMA_APIHUB_KEY
사용: python src/data/fetch_wave_buoy.py
"""
from pathlib import Path
import os
import re
import sys
import time

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import ROOT_DIR, DATA_EXTERNAL_DIR  # noqa: E402

load_dotenv(ROOT_DIR / ".env")
AUTH_KEY = os.environ.get("KMA_APIHUB_KEY", "")
BASE_URL = "https://apihub.kma.go.kr/api/typ02/openApi/SeaMtlyInfoService/getDailyWaveBuoy"
OUT_DIR = DATA_EXTERNAL_DIR / "kma_wave_buoy"

# 지역 -> 가까운 파고부이 (2016-09 지점일람표 기준, 수과원 관측소와의 거리는 대략 추정 좌표 기준)
BUOYS = {
    "22477": ("노화도", "완도"),    # 약 21km
    "22456": ("청산도", "완도"),    # 약 24km
    "22466": ("금오도", "여수"),    # 약 20km
    "22467": ("한산도", "통영"),    # 약 10.5km
    "22450": ("두미도", "남해군"),  # 약 12.9km
}
START = (2016, 9)


def parse_value(raw: str):
    """'   27.9)' -> (27.9, ')') / 빈 값 -> (NaN, '')"""
    s = (raw or "").strip()
    m = re.match(r"^(-?\d+(?:\.\d+)?)(.*)$", s)
    if not m:
        return float("nan"), s
    return float(m.group(1)), m.group(2).strip()


def fetch_month(stn: str, year: int, month: int) -> pd.DataFrame:
    params = {"pageNo": 1, "numOfRows": 40, "dataType": "JSON", "year": year,
              "month": f"{month:02d}", "station": stn, "authKey": AUTH_KEY}
    for attempt in range(3):
        try:
            r = requests.get(BASE_URL, params=params, timeout=60)
            body = r.json()["response"]
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(2 * (attempt + 1))
            continue
        code = body["header"]["resultCode"]
        if code != "00":  # 99 = 발간되지 않은 기간
            return pd.DataFrame()
        rows = []
        for item in body["body"]["items"]["item"]:
            for d in item["day"]["info"]:
                if not str(d.get("tm", "")).strip().isdigit():  # 상순/중순/하순/월 요약 행 제외
                    continue
                tw, flag = parse_value(d.get("tw"))
                rows.append({"date": pd.Timestamp(year, month, int(d["tm"])), "tw": tw, "tw_flag": flag})
        return pd.DataFrame(rows)
    raise RuntimeError(f"{stn} {year}-{month:02d} 요청 실패")


def main():
    if not AUTH_KEY:
        raise SystemExit(".env에 KMA_APIHUB_KEY가 없습니다.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = pd.Timestamp.today()
    months = pd.period_range(f"{START[0]}-{START[1]:02d}", today.to_period("M"), freq="M")
    for stn, (name, region) in BUOYS.items():
        frames = [fetch_month(stn, p.year, p.month) for p in months]
        df = pd.concat([f for f in frames if not f.empty], ignore_index=True)
        out = OUT_DIR / f"{stn}_{name}.csv"
        df.to_csv(out, index=False, encoding="utf-8-sig")
        print(f"[{region}] {name}({stn}): {df['date'].min().date()}~{df['date'].max().date()}, "
              f"{len(df)}일, 수온 결측 {df['tw'].isna().sum()}일", flush=True)


if __name__ == "__main__":
    main()
