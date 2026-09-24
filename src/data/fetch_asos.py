"""공공데이터포털 '기상청_지상(종관, ASOS) 시간자료 조회서비스'로 과거 기상 시간자료를 받아
기존 원자료와 같은 형식(`기상 데이터/{지역}/ASOS_{이름}_{지점}_{연도}_hourly.csv`, cp949)으로 저장한다.

2차 멘토링 후속: 고수온 구간만으로 학습하면 표본이 너무 적어(통영 26℃ 이상 44일) 학습 기간을
2016~2020년으로 늘리기 위해 추가. 같은 폴더에 저장하므로 load_weather.py가 그대로 읽는다.

인증키: 저장소 루트 `.env`의 DATA_GO_KR_API_KEY (없으면 KMA_FORECAST_API_KEY 사용 - 같은
공공데이터포털 계정 키). 해당 서비스에 활용신청이 되어 있어야 함.

사용: python src/data/fetch_asos.py 2016 2020
"""
from pathlib import Path
import os
import sys
import time
from urllib.parse import unquote

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import ROOT_DIR  # noqa: E402
from data.load_weather import WEATHER_DIR, WEATHER_FOLDER_MAP  # noqa: E402

load_dotenv(ROOT_DIR / ".env")
SERVICE_KEY = unquote(os.environ.get("DATA_GO_KR_API_KEY") or os.environ.get("KMA_FORECAST_API_KEY", ""))
BASE_URL = "https://apis.data.go.kr/1360000/AsosHourlyInfoService/getWthrDataList"

# 표준 지역명 -> (파일명용 영문, 지점번호) : 기존 원자료 파일명 규칙과 동일
STATIONS = {"완도": ("Wando", 170), "여수": ("Yeosu", 168), "통영": ("Tongyeong", 162), "남해군": ("Namhae", 295)}

# API 필드 -> 기존 원자료 컬럼
COLUMN_MAP = {
    "stnId": "지점", "stnNm": "지점명", "tm": "일시",
    "ta": "기온(°C)", "taQcflg": "기온 QC플래그",
    "rn": "강수량(mm)", "rnQcflg": "강수량 QC플래그",
    "ws": "풍속(m/s)", "wsQcflg": "풍속 QC플래그",
    "wd": "풍향(16방위)", "wdQcflg": "풍향 QC플래그",
    "icsr": "일사(MJ/m2)", "icsrQcflg": "일사 QC플래그",
}
NUMERIC = ["기온(°C)", "강수량(mm)", "풍속(m/s)", "풍향(16방위)", "일사(MJ/m2)"]


def fetch_month(stn: int, year: int, month: int) -> pd.DataFrame:
    start = pd.Timestamp(year, month, 1)
    yesterday = pd.Timestamp.today().normalize() - pd.Timedelta(days=1)  # API는 전일(D-1)까지만 제공
    if start > yesterday:
        return pd.DataFrame()
    end = min(start + pd.offsets.MonthEnd(0), yesterday)
    params = {"serviceKey": SERVICE_KEY, "pageNo": 1, "numOfRows": 999, "dataType": "JSON",
              "dataCd": "ASOS", "dateCd": "HR", "stnIds": stn,
              "startDt": start.strftime("%Y%m%d"), "startHh": "00",
              "endDt": end.strftime("%Y%m%d"), "endHh": "23"}
    for attempt in range(5):
        try:
            r = requests.get(BASE_URL, params=params, timeout=60)
        except requests.RequestException:  # 연결 끊김 등 일시 오류는 잠시 후 재시도
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 200 and r.text.lstrip().startswith("{"):
            body = r.json()["response"]
            code = body["header"]["resultCode"]
            if code == "00":
                return pd.DataFrame(body["body"]["items"]["item"])
            if code == "03":  # NO_DATA
                return pd.DataFrame()
            raise RuntimeError(f"API 오류 {code}: {body['header']['resultMsg']}")
        if "SERVICE_KEY_IS_NOT_REGISTERED" in r.text:
            raise RuntimeError("서비스키가 ASOS 시간자료 서비스에 등록되지 않음 - 공공데이터포털에서 활용신청 필요")
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"요청 실패 ({r.status_code}): {r.text[:300]}")


def fetch_year(region: str, year: int) -> Path:
    name, stn = STATIONS[region]
    out = WEATHER_DIR / WEATHER_FOLDER_MAP[region] / f"ASOS_{name}_{stn}_{year}_hourly.csv"
    if out.exists():
        print(f"  건너뜀 (이미 있음): {out.name}")
        return out
    frames = [fetch_month(stn, year, m) for m in range(1, 13)]
    raw = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    df = raw.reindex(columns=list(COLUMN_MAP)).rename(columns=COLUMN_MAP)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c].replace("", pd.NA), errors="coerce")
    df = df.drop_duplicates(subset=["일시"]).sort_values("일시")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="cp949")
    print(f"  저장: {out.name} ({len(df)}행, 기온 결측 {df['기온(°C)'].isna().sum()}건)")
    return out


def _to_file_format(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.reindex(columns=list(COLUMN_MAP)).rename(columns=COLUMN_MAP)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c].replace("", pd.NA), errors="coerce")
    return df


def refresh_recent(region: str, days: int = 45) -> None:
    """최근 days일이 걸친 달을 다시 받아 연도별 파일에 덮어쓴다 (앱의 매일 갱신용)."""
    name, stn = STATIONS[region]
    today = pd.Timestamp.today().normalize()
    months = pd.period_range((today - pd.Timedelta(days=days)).to_period("M"), today.to_period("M"), freq="M")
    new = pd.concat([f for f in (fetch_month(stn, p.year, p.month) for p in months) if not f.empty], ignore_index=True)
    new = _to_file_format(new)
    new["year"] = new["일시"].str[:4].astype(int)
    for year, part in new.groupby("year"):
        out = WEATHER_DIR / WEATHER_FOLDER_MAP[region] / f"ASOS_{name}_{stn}_{year}_hourly.csv"
        part = part.drop(columns="year")
        if out.exists():
            old = pd.read_csv(out, encoding="cp949")
            part = pd.concat([old, part], ignore_index=True)
        part = part.drop_duplicates(subset=["일시"], keep="last").sort_values("일시")
        part.to_csv(out, index=False, encoding="cp949")


def main(start_year: int, end_year: int):
    if not SERVICE_KEY:
        raise SystemExit(".env에 DATA_GO_KR_API_KEY(또는 KMA_FORECAST_API_KEY)가 없습니다.")
    for region in STATIONS:
        print(f"[{region}]")
        for year in range(start_year, end_year + 1):
            fetch_year(region, year)


if __name__ == "__main__":
    s, e = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) == 3 else (2016, 2020)
    main(s, e)


# ---------------- 지점번호 기준 수집 (양식장 위치별 예보용, 2026-09-25) ----------------
def fetch_station(stn: int, years, refresh_recent_days: int = 0) -> None:
    """ASOS 지점 stn의 연도별 시간자료를 '기상 데이터/지점별/{stn}/' (기존 4개 지점은 지역 폴더)에 저장.
    이미 있는 연도는 건너뛰되, refresh_recent_days>0이면 최근 그 기간이 걸친 달은 다시 받아 덮어쓴다."""
    from data.load_weather import station_dir
    out_dir = station_dir(stn)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = pd.Timestamp.today().normalize()
    recent = set()
    if refresh_recent_days:
        recent = {(p.year, p.month) for p in pd.period_range((today - pd.Timedelta(days=refresh_recent_days)).to_period("M"),
                                                            today.to_period("M"), freq="M")}
    for year in years:
        existing = sorted(out_dir.glob(f"*_{year}_hourly.csv"))
        path = existing[0] if existing else out_dir / f"ASOS_{stn}_{year}_hourly.csv"
        months = range(1, 13) if not path.exists() else sorted(m for (y, m) in recent if y == year)
        if not months:
            continue
        frames = [fetch_month(stn, year, m) for m in months]
        frames = [f for f in frames if not f.empty]
        if not frames:
            continue
        new = _to_file_format(pd.concat(frames, ignore_index=True))
        if path.exists():
            new = pd.concat([pd.read_csv(path, encoding="cp949"), new], ignore_index=True)
        new.drop_duplicates(subset=["일시"], keep="last").sort_values("일시").to_csv(path, index=False, encoding="cp949")
