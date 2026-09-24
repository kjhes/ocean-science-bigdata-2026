"""국립수산과학원 '과거 관측정보 다운로드'(남해, 연도별 zip) → 관측소별 일평균 표층수온.

출처: https://www.nifs.go.kr/risa/risa/risaD/actionRisaPastDown.do
  파일: https://www.nifs.go.kr/risa/cmmn/pastRisaInfoDown/ss_{연도}.zip (ss=남해, 2011~2025, 인증키 불필요)
  내용: 월별 CSV, 관측소별 1시간 간격 표층·중층·저층 수온/염분/DO

2026-09-24 검증: 2021년 파일의 일평균이 기존 `수온 데이터/`(완도 군외·여수 신월·통영 학림·남해 미조)의
일별 값과 4개 지점 모두 |차이| ≤ 0.05℃(반올림 차이)로 일치 → 기존 자료는 이 시간자료의 일평균.
월별 CSV 인코딩이 UTF-8/CP949로 섞여 있어 둘 다 시도한다.

사용: python src/data/fetch_nifs_past.py 로 zip을 받은 뒤 python src/data/nifs_past.py
출력: data/processed/nifs_daily_southsea.csv (date, station, code, temperature, n_hours)
"""
from pathlib import Path
import io
import re
import sys
import zipfile

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import ROOT_DIR, DATA_RAW_DIR, DATA_PROCESSED_DIR  # noqa: E402

PAST_DIR = DATA_RAW_DIR / "nifs_past"
OUT_PATH = DATA_PROCESSED_DIR / "nifs_daily_southsea.csv"
MIN_HOURS = 12  # 하루 24시간 중 이 이상 관측된 날만 일평균 인정


def read_month(raw: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc, usecols=[0, 1, 2])
        except UnicodeDecodeError:
            continue
    raise ValueError("인코딩 판별 실패")


def daily_from_zip(path: Path) -> pd.DataFrame:
    z = zipfile.ZipFile(path)
    h = pd.concat([read_month(z.read(i)) for i in z.infolist() if i.filename.lower().endswith(".csv")],
                  ignore_index=True)
    h.columns = ["station", "tm", "temperature"]
    h["tm"] = pd.to_datetime(h["tm"], errors="coerce")
    h["temperature"] = pd.to_numeric(h["temperature"], errors="coerce")
    h = h.dropna(subset=["tm", "temperature"])
    h["date"] = h["tm"].dt.floor("D")
    d = h.groupby(["station", "date"])["temperature"].agg(["mean", "size"]).reset_index()
    d.columns = ["station", "date", "temperature", "n_hours"]
    return d[d["n_hours"] >= MIN_HOURS]


def build():
    frames = [daily_from_zip(p) for p in sorted(PAST_DIR.glob("ss_*.zip"))]
    d = pd.concat(frames, ignore_index=True)
    d["code"] = d["station"].str.extract(r"\(([^()]+)\)\s*$")[0]
    d["temperature"] = d["temperature"].round(2)
    d = d.drop_duplicates(["code", "date"]).sort_values(["code", "date"])
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    d[["date", "station", "code", "temperature", "n_hours"]].to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"저장: {OUT_PATH} ({len(d)}행, 관측소 {d['code'].nunique()}곳, {d['date'].min().date()}~{d['date'].max().date()})")
    return d


def load_nifs_daily() -> pd.DataFrame:
    return pd.read_csv(OUT_PATH, parse_dates=["date"])


# 표준 지역명 -> 기존 `수온 데이터/`와 같은 관측소 코드
STATION_CODES = {"완도": "fwgk5", "여수": "km001", "통영": "fth59", "남해군": "fnm5b"}


def load_code_series(code: str, daily: pd.DataFrame = None, recent: pd.DataFrame = None) -> pd.Series:
    """관측소 코드의 일평균 표층수온 (과거자료 다운로드 + 최근 실시간 조회). 여러 관측소를 돌 때는
    daily/recent 표를 미리 읽어 넘기면 빠르다."""
    d = load_nifs_daily() if daily is None else daily
    s = d[d["code"] == code].set_index("date")["temperature"]
    if recent is None:
        p = DATA_PROCESSED_DIR / "nifs_daily_recent.csv"
        recent = pd.read_csv(p, parse_dates=["date"]) if p.exists() else pd.DataFrame(columns=["code", "date", "temperature"])
    last = s.index.max() if len(s) else pd.Timestamp("1900-01-01")
    r = recent[(recent["code"] == code) & (recent["date"] > last)].set_index("date")["temperature"]
    return pd.concat([s, r]).sort_index().rename("sea")


def load_station_series(region: str) -> pd.Series:
    """지역 관측소의 장기(2012~) 일평균 표층수온. 완도 군외는 2020년 설치라 2020~."""
    d = load_nifs_daily()
    s = d[d["code"] == STATION_CODES[region]].set_index("date")["temperature"]
    # 과거자료 다운로드에 아직 없는 최근 기간(src/data/fetch_nifs_recent.py로 받은 것)을 이어 붙임
    recent_path = DATA_PROCESSED_DIR / "nifs_daily_recent.csv"
    if recent_path.exists():
        r = pd.read_csv(recent_path, parse_dates=["date"])
        r = r[(r["code"] == STATION_CODES[region]) & (r["date"] > s.index.max())].set_index("date")["temperature"]
        s = pd.concat([s, r])
    return s.rename("sea")


if __name__ == "__main__":
    build()
