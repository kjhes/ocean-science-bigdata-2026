# 남해안 수온 변화 예측 AI 및 양식방식별 맞춤 어종 추천 모델

2026 해양수산 빅데이터 공모전 프로젝트. 완도·여수·통영·남해군 4개 지역의 수온을
시계열 예측하고, 예측 결과와 어종별 적정 환경 조건·양식 방식별 위험도를 결합해
지역·양식 방식별 맞춤 어종을 추천한다.

전체 기획 배경/목적/방법은 [`docs/기획서.md`](docs/기획서.md) 참고.
진행 상황은 [`PROGRESS.md`](PROGRESS.md)에 계속 기록한다 (세션이 끊겨도 여기서 이어서 파악 가능).

## 프로젝트 구조

```
├── docs/                       기획서, 데이터 소스 조사 등 문서
├── 수온 데이터/                  팀원이 수집한 실제 원자료 (일별 CSV, 지역별 폴더)
├── data/
│   ├── raw/                    (원자료는 위 '수온 데이터/' 폴더를 그대로 참조, 여기는 예비용)
│   ├── processed/               전처리/파싱된 산출물 (예: regional_yearly_summary.csv)
│   └── external/
│       ├── species_conditions/   어종별 적정 수온·치사수온 (fish_temperature_thresholds.csv)
│       └── farming_methods/      양식방식별(가두리/유수/지수식) 위험도 자료 (예정)
├── src/
│   ├── config.py                 지역명/경로/색상 등 공통 설정
│   ├── data/                     원자료 로딩 (load_data.py, parse_yearly_summary.py)
│   ├── features/                 전처리 (preprocess.py: 결측치/이상치/파생변수)
│   ├── models/                   시계열 예측 모델 (forecast.py)
│   └── visualization/            시각화 (plots.py)
├── notebooks/                   EDA용 주피터 노트북
└── reports/figures/              생성된 차트 이미지
```

## 시작하기

```bash
pip install -r requirements.txt
python src/data/load_data.py          # 원자료 로딩 확인
jupyter notebook notebooks/01_eda_수온데이터.ipynb
```

## 데이터

- **수온 시계열**: `수온 데이터/{지역(관측소)}/*.csv` — 완도(군의)·여수(신월)·통영(학림)·남해(미조) 4개 관측소, 2021-01-01~2025-12-31 일별 표층 수온(`wtemS`). 자세한 내용은 [`docs/data_sources.md`](docs/data_sources.md).
- **어종별 적정 환경조건**: [`data/external/species_conditions/fish_temperature_thresholds.csv`](data/external/species_conditions/fish_temperature_thresholds.csv) — 국립수산과학원 자료 기반, 8개 주요 양식 어종(조피볼락·넙치·참돔·감성돔·숭어·농어·돌돔·방어)의 적정수온 범위 및 치사(고수온 위험) 수온. 염분·용존산소·pH는 아직 미확보.
- **양식방식별 수온 영향 비율**: [`data/external/farming_methods/farming_method_temp_impact.csv`](data/external/farming_methods/farming_method_temp_impact.csv) — 진행 중. 해상 가두리식만 확정(100%, 구조적으로 자명), 육상 유수식·순환여과식(RAS)은 실측 환수율/폐사율은 있으나 0~100% 비율 환산식 미정, 지수식은 자료 미확보. 자세한 내용은 [`docs/data_sources.md`](docs/data_sources.md)

## 팀 (공모전 위탁교육과정)

3인 팀 — 자료조사 / 데이터 전처리·분석 / 모델 구현·시각화 역할 분담 (기획서 참고)
