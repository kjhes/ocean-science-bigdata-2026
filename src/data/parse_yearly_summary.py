"""'수온 데이터/[자료 정리] ... .txt' 형태의 연도별 요약 통계 텍스트를 파싱하는 모듈.

주의: 이 파일은 일별 원자료가 아니라, 지역(관측소)별 연도 단위 요약
(평균/최저/최고 수온, 고수온 경보 일수)이다. 시계열 예측 모델 학습에는
결국 일별 원자료가 필요하므로, 이 모듈은 어디까지나
1) 지역별 기초 통계 파악 2) 고수온 경보 특성 비교
용도로 사용하고, 예측 모델용 데이터가 아님에 유의한다.

기대 입력 포맷 (블록 단위, '='로만 이루어진 구분선으로 분리):
    1. 개요 및 수집 데이터
     - 지역/관측소: 남해 미조
     - 데이터 기간: 2021년 01월 01일 ~ 2025년 12월 31일 (5년)
     - 주요 변수: 일별 표층 수온(℃)
     - 데이터 수: 총 1,826일 (...)

    2. 연도별 주요 수온 지표
     - 2021년: 평균 17.5℃ / 최저  7.8℃ / 최고 28.7℃ (고수온 경보 5일)
     ...
     - 5년 전체: 평균 17.2℃ / 최저  7.5℃ / 최고 29.8℃
"""
import re
from pathlib import Path
import sys

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import DATA_PROCESSED_DIR  # noqa: E402

# 텍스트에 등장하는 지역명(관측소 기준 첫 단어) -> 기획서 표준 지역명 매핑
REGION_NAME_MAP = {
    "남해": "남해군",
    "여수": "여수",
    "완도": "완도",
    "통영": "통영",
}

STATION_RE = re.compile(r"지역/관측소:\s*(\S+)\s+(\S+)")
PERIOD_RE = re.compile(r"데이터 기간:\s*([^()]+)\(")
COUNT_RE = re.compile(r"데이터 수:\s*총\s*([\d,]+)\s*일")
YEAR_LINE_RE = re.compile(
    r"-\s*(\d{4})년:\s*평균\s*([\d.]+)\s*℃\s*/\s*최저\s*([\d.]+)\s*℃\s*/\s*최고\s*([\d.]+)\s*℃"
    r"(?:\s*\(고수온\s*경보\s*(\d+)\s*일\))?"
)
TOTAL_LINE_RE = re.compile(
    r"5년\s*전체:\s*평균\s*([\d.]+)\s*℃\s*/\s*최저\s*([\d.]+)\s*℃\s*/\s*최고\s*([\d.]+)\s*℃"
)


def parse_yearly_summary(txt_path: Path) -> pd.DataFrame:
    """텍스트 파일을 파싱하여 (지역, 관측소, 연도, 평균/최저/최고수온, 고수온경보일수) 표로 반환.

    '5년 전체' 행은 year="전체"로 별도 표기한다.
    """
    text = Path(txt_path).read_text(encoding="utf-8")
    # '=' 로만 이루어진 구분선을 기준으로 지역별 블록 분리
    blocks = re.split(r"^=+$", text, flags=re.MULTILINE)

    rows = []
    for block in blocks:
        station_match = STATION_RE.search(block)
        if not station_match:
            continue
        raw_region, station = station_match.groups()
        region = REGION_NAME_MAP.get(raw_region, raw_region)

        period_match = PERIOD_RE.search(block)
        period = period_match.group(1).strip() if period_match else None

        count_match = COUNT_RE.search(block)
        n_days = int(count_match.group(1).replace(",", "")) if count_match else None

        for year, mean_t, min_t, max_t, alert_days in YEAR_LINE_RE.findall(block):
            rows.append({
                "region": region,
                "station": station,
                "period": period,
                "n_days": n_days,
                "year": year,
                "mean_temp": float(mean_t),
                "min_temp": float(min_t),
                "max_temp": float(max_t),
                "high_temp_alert_days": int(alert_days) if alert_days else 0,
            })

        total_match = TOTAL_LINE_RE.search(block)
        if total_match:
            mean_t, min_t, max_t = total_match.groups()
            rows.append({
                "region": region,
                "station": station,
                "period": period,
                "n_days": n_days,
                "year": "전체",
                "mean_temp": float(mean_t),
                "min_temp": float(min_t),
                "max_temp": float(max_t),
                "high_temp_alert_days": None,
            })

    return pd.DataFrame(rows)


def save_parsed(txt_path: Path, out_path: Path = None) -> pd.DataFrame:
    df = parse_yearly_summary(txt_path)
    out_path = out_path or (DATA_PROCESSED_DIR / "regional_yearly_summary.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {out_path} ({len(df)} rows)")
    return df


if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parent.parent.parent
    txt_path = ROOT / "수온 데이터" / "[자료 정리] 남해 지역 5년 수온 데이터 분석.txt"
    df = save_parsed(txt_path)
    print(df)
