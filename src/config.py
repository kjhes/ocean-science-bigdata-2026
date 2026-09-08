"""프로젝트 공통 설정값.

지역, 경로 등 여러 모듈에서 공유하는 상수를 모아둔다.
"""
from pathlib import Path

# 프로젝트 루트 (이 파일 기준 한 단계 위)
ROOT_DIR = Path(__file__).resolve().parent.parent

DATA_RAW_DIR = ROOT_DIR / "data" / "raw"
DATA_PROCESSED_DIR = ROOT_DIR / "data" / "processed"
DATA_EXTERNAL_DIR = ROOT_DIR / "data" / "external"
SPECIES_CONDITIONS_DIR = DATA_EXTERNAL_DIR / "species_conditions"
FARMING_METHODS_DIR = DATA_EXTERNAL_DIR / "farming_methods"
FIGURES_DIR = ROOT_DIR / "reports" / "figures"

# 분석 대상 4개 지역 (기획서 기준)
REGIONS = ["완도", "여수", "통영", "남해군"]

# 실제 수온 원자료(일별 CSV) 위치. 팀원이 받아온 파일을 그대로 사용하며,
# data/raw/ 로 옮기지 않고 원래 위치를 참조한다 (지역 폴더명이 표준 지역명과 달라 매핑 필요).
RAW_TEMP_DIR = ROOT_DIR / "수온 데이터"

# 표준 지역명 -> 실제 원자료 폴더명
REGION_FOLDER_MAP = {
    "완도": "완도(군의)",
    "여수": "여수(신월)",
    "통영": "통영(학림)",
    "남해군": "남해(미조)",
}

# 지역별 고정 색상 (dataviz 스킬의 검증된 카테고리 팔레트, 1~4번 슬롯)
# 순서를 고정해야 지역이 빠지거나 필터링돼도 같은 지역은 항상 같은 색을 유지한다.
REGION_COLORS = {
    "완도": "#2a78d6",   # blue
    "여수": "#eb6834",   # orange
    "통영": "#1baf7a",   # aqua
    "남해군": "#eda100",  # yellow
}

# 양식 방식 (기획서 기준)
FARMING_METHODS = ["가두리식", "유수식", "지수식"]

# 평가지표 계산 시 공통으로 사용할 컬럼명 규칙
DATE_COL = "date"
TEMP_COL = "temperature"
REGION_COL = "region"
