"""국립수산과학원 '실시간 관측정보 검색'에서 최근 기간(과거자료 다운로드에 아직 없는 해) 수온을 받는다.

과거 관측정보 다운로드(src/data/nifs_past.py)는 2025년까지만 있어, 2026년 여름을 '한 번도 안 쓴
검증 데이터'로 쓰기 위해 추가. 웹 화면이 쓰는 조회 주소(searchRisaInfoList.do, form POST)를 그대로
호출한다. 화면 제약과 같게 한 번에 30일 이내로 나눠 요청.
기존 `수온 데이터/` CSV의 컬럼명(obsrvnGroupNm, obsvtrCd 등)이 이 조회 결과와 같아, 팀이 원자료를
받은 곳도 이 화면으로 보인다.

사용: python src/data/fetch_nifs_recent.py 2026-05-01 2026-09-23
출력: data/processed/nifs_daily_recent.csv (date, code, temperature, n_hours, lat, lon)
"""
from pathlib import Path
import sys
import time

import pandas as pd
import requests

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import DATA_PROCESSED_DIR  # noqa: E402
from data.nifs_past import STATION_CODES, MIN_HOURS  # noqa: E402

PAGE_URL = "https://www.nifs.go.kr/risa/risa/risaA/actionRisaInfo.do"
SEARCH_URL = "https://www.nifs.go.kr/risa/risa/risaA/searchRisaInfoList.do"
OUT_PATH = DATA_PROCESSED_DIR / "nifs_daily_recent.csv"


def fetch_range(session: requests.Session, code: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    params = {"obsrvnGroupNm": "S", "obsvtrCd": code, "obsFrom": start.strftime("%Y-%m-%d"),
              "obsTo": end.strftime("%Y-%m-%d"), "obsTimeFrom": "0000", "obsTimeTo": "2330",
              "ord": "2", "ordType": "A", "selectPage": 1, "rowCountPage": 5000}
    headers = {"X-Requested-With": "XMLHttpRequest", "Referer": PAGE_URL}
    for attempt in range(3):
        try:
            r = session.post(SEARCH_URL, data=params, headers=headers, timeout=60)
            rows = r.json().get("retList", [])
            return pd.DataFrame(rows)
        except (requests.RequestException, ValueError):
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{code} {start.date()}~{end.date()} 요청 실패")


def fetch(start: str, end: str) -> pd.DataFrame:
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    s.get(PAGE_URL, timeout=60)
    frames = []
    for region, code in STATION_CODES.items():
        cur = pd.Timestamp(start)
        while cur <= pd.Timestamp(end):
            stop = min(cur + pd.Timedelta(days=29), pd.Timestamp(end))
            h = fetch_range(s, code, cur, stop)
            if not h.empty:
                frames.append(h.assign(region=region))
            cur = stop + pd.Timedelta(days=1)
            time.sleep(0.5)
    h = pd.concat(frames, ignore_index=True)
    h["tm"] = pd.to_datetime(h["obsrvnDt"])
    h["t"] = pd.to_numeric(h["wtrTempS"], errors="coerce")
    h = h.dropna(subset=["t"]).drop_duplicates(["obsvtrCd", "tm"])
    h["date"] = h["tm"].dt.floor("D")
    d = h.groupby(["obsvtrCd", "date"]).agg(temperature=("t", "mean"), n_hours=("t", "size"),
                                              lat=("lat", "first"), lon=("lot", "first")).reset_index()
    d = d.rename(columns={"obsvtrCd": "code"})
    d["temperature"] = d["temperature"].round(2)
    return d[d["n_hours"] >= MIN_HOURS]


if __name__ == "__main__":
    a, b = (sys.argv[1], sys.argv[2]) if len(sys.argv) == 3 else ("2026-05-01", "2026-09-23")
    d = fetch(a, b)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"저장: {OUT_PATH} ({len(d)}행)")
    print(d.groupby("code")["date"].agg(["min", "max", "count"]))


def fetch_all_stations(start: str, end: str) -> pd.DataFrame:
    """남해 전체 관측소를 하루 단위로 한꺼번에 받는다(관측소 코드를 비우면 전체 반환). 양식장 위치별 예보용."""
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    s.get(PAGE_URL, timeout=60)
    headers = {"X-Requested-With": "XMLHttpRequest", "Referer": PAGE_URL}
    frames = []
    for day in pd.date_range(start, end, freq="D"):
        params = {"obsrvnGroupNm": "S", "obsvtrCd": "", "obsFrom": day.strftime("%Y-%m-%d"),
                  "obsTo": day.strftime("%Y-%m-%d"), "obsTimeFrom": "0000", "obsTimeTo": "2330",
                  "ord": "1", "ordType": "A", "selectPage": 1, "rowCountPage": 20000}
        for attempt in range(3):
            try:
                rows = s.post(SEARCH_URL, data=params, headers=headers, timeout=90).json().get("retList", [])
                break
            except (requests.RequestException, ValueError):
                time.sleep(3 * (attempt + 1))
        else:
            raise RuntimeError(f"{day.date()} 요청 실패")
        if len(rows) >= 20000:
            raise RuntimeError(f"{day.date()} 결과가 한 페이지(20000행)를 넘음 - 페이지 나눔 필요")
        if rows:
            frames.append(pd.DataFrame(rows))
        time.sleep(0.3)
    h = pd.concat(frames, ignore_index=True)
    h["tm"] = pd.to_datetime(h["obsrvnDt"])
    h["t"] = pd.to_numeric(h["wtrTempS"], errors="coerce")
    h = h.dropna(subset=["t"]).drop_duplicates(["obsvtrCd", "tm"])
    h["date"] = h["tm"].dt.floor("D")
    d = h.groupby(["obsvtrCd", "date"]).agg(temperature=("t", "mean"), n_hours=("t", "size"),
                                              lat=("lat", "first"), lon=("lot", "first")).reset_index()
    d = d.rename(columns={"obsvtrCd": "code"})
    d["temperature"] = d["temperature"].round(2)
    return d[d["n_hours"] >= MIN_HOURS]


def update_recent_file(new: pd.DataFrame) -> pd.DataFrame:
    if OUT_PATH.exists():
        old = pd.read_csv(OUT_PATH, parse_dates=["date"])
        new = pd.concat([old, new], ignore_index=True).drop_duplicates(["code", "date"], keep="last")
    new = new.sort_values(["code", "date"])
    new.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    return new
