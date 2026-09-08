"""수온 원자료(일별 CSV) 로딩 모듈.

원자료 위치: 프로젝트 루트의 `수온 데이터/{지역(관측소)}/{지역 연도}~.csv`
    예) 수온 데이터/남해(미조)/남해 2021~.csv

원자료 컬럼 (국립수산과학원 실시간해양환경정보시스템 형식으로 추정):
    obsrvnGroupNm  : 관측소 그룹명 (예: 남해)
    obsvtrCd       : 관측소 코드
    obsvtrKornNm   : 관측소 한글명 (예: 남해 미조)
    staNam         : 관측소명(코드) (예: 남해 미조(fnm5b))
    obsrvnDt       : 관측일자 (YYYY-MM-DD)
    wtemM          : 중층 수온 (일부 지역만 존재)
    wtemS          : 표층 수온 (모든 지역 공통 → 본 프로젝트의 기준 변수로 사용)
    wtemB          : 저층 수온 (일부 지역만 존재, 현재 통영만 보유)

주의: 지역별로 관측 가능한 수심 컬럼 구성이 다르다 (남해=M/S, 여수·완도=S만,
통영=M/S/B). 기획서가 "일별 표층 수온"을 기준으로 하므로, 4개 지역 모두에
공통으로 존재하는 wtemS(표층)를 표준 변수로 사용한다.

연도별 파일은 경계일이 겹친다 (예: 2021년 파일의 마지막 행이 2022-01-01이고
2022년 파일의 첫 행도 2022-01-01) → 병합 시 날짜 기준 중복 제거 필요.
"""
from pathlib import Path
from typing import Optional

import pandas as pd

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import RAW_TEMP_DIR, REGION_FOLDER_MAP, REGIONS, DATE_COL, REGION_COL, TEMP_COL  # noqa: E402

RAW_DATE_COL = "obsrvnDt"
RAW_SURFACE_COL = "wtemS"
RAW_STATION_COL = "obsvtrKornNm"


def load_raw_temperature(region: str, raw_dir: Optional[Path] = None) -> pd.DataFrame:
    """지정한 지역의 연도별 일별 수온 CSV를 모두 읽어 하나로 합친다.

    Parameters
    ----------
    region : str
        REGIONS 중 하나 ("완도", "여수", "통영", "남해군")
    raw_dir : Path, optional
        원자료 최상위 디렉터리. 기본값은 config.RAW_TEMP_DIR ("수온 데이터/")

    Returns
    -------
    pd.DataFrame
        columns = [date, region, temperature, station]
        표층(wtemS) 수온 기준, 연도 경계 중복일자는 제거, 날짜순 정렬됨.
    """
    if region not in REGIONS:
        raise ValueError(f"알 수 없는 지역: {region}. REGIONS={REGIONS} 중에서 선택하세요.")

    raw_dir = raw_dir or RAW_TEMP_DIR
    folder = REGION_FOLDER_MAP[region]
    region_dir = raw_dir / folder
    csv_files = sorted(region_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(
            f"{region_dir} 에서 CSV 파일을 찾을 수 없습니다. "
            f"'수온 데이터/{folder}/' 아래에 연도별 원자료가 있는지 확인하세요."
        )

    frames = []
    for f in csv_files:
        df = pd.read_csv(f, encoding="utf-8-sig")
        if RAW_SURFACE_COL not in df.columns:
            raise ValueError(f"{f} 에 표층 수온 컬럼({RAW_SURFACE_COL})이 없습니다. 컬럼: {list(df.columns)}")
        frames.append(df)

    raw = pd.concat(frames, ignore_index=True)
    raw[RAW_DATE_COL] = pd.to_datetime(raw[RAW_DATE_COL])

    out = pd.DataFrame({
        DATE_COL: raw[RAW_DATE_COL],
        REGION_COL: region,
        TEMP_COL: raw[RAW_SURFACE_COL],
        "station": raw[RAW_STATION_COL] if RAW_STATION_COL in raw.columns else None,
    })

    # 연도 경계 중복 날짜 제거 (같은 날짜가 두 연도 파일에 걸쳐 존재)
    before = len(out)
    out = out.drop_duplicates(subset=[DATE_COL], keep="first")
    dropped = before - len(out)
    if dropped:
        print(f"[{region}] 연도 경계 중복 {dropped}건 제거")

    return out.sort_values(DATE_COL).reset_index(drop=True)


def load_all_regions(raw_dir: Optional[Path] = None) -> pd.DataFrame:
    """REGIONS 전체를 로드하여 하나의 DataFrame으로 합친다."""
    frames = []
    for region in REGIONS:
        try:
            frames.append(load_raw_temperature(region, raw_dir))
        except FileNotFoundError as e:
            print(f"[경고] {region} 데이터를 건너뜁니다: {e}")
    if not frames:
        raise FileNotFoundError(
            "로드된 지역 데이터가 없습니다. '수온 데이터/' 폴더 구성을 확인하세요."
        )
    return pd.concat(frames, ignore_index=True).sort_values([REGION_COL, DATE_COL]).reset_index(drop=True)


if __name__ == "__main__":
    df = load_all_regions()
    print(df.head())
    print(df.groupby("region")[TEMP_COL].agg(["count", "mean", "min", "max"]))
    print("결측치:")
    print(df.groupby("region")[TEMP_COL].apply(lambda s: s.isna().sum()))
