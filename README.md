# 남해안 수온 단기 예측 및 양식장 고수온 경보

2026 해양과학 AI × 빅데이터 경진대회 중·고등부 데이터 분석 프로젝트.
완도·여수·통영·남해군 4개 지역의 수온을 **단기(며칠 단위)로 예측**하고,
어종별 적정·치사 수온과 결합해 양식장 위치·사육 어종별 **고수온 경보와 대응 방법**을 제공한다.

> **2026-09-10 방향 전환.** 원래 목표는 수년 뒤 수온을 예측해 어종을 추천하는 것이었으나,
> 1차 멘토링에서 장기 예측이 성립하지 않는다는 지적을 받고 단기 예측 + 경보로 전환했다.
> 전환에 이르기까지의 근거는 아래 문서에 순서대로 기록되어 있다.
>
> 1. [`docs/2024_이상값_분석.md`](docs/2024_이상값_분석.md) — 2024년은 평균도 최고값도 정상이었고, 여름이 한 달 늦게 끝났다
> 2. [`docs/2024_고수온_원인_정정.md`](docs/2024_고수온_원인_정정.md) — 초기 추정(라니냐) 철회
> 3. [`docs/장기추세_보정_검토.md`](docs/장기추세_보정_검토.md) — 델타 기법 검토 후 기각
> 4. [`docs/평년값_전제_검증.md`](docs/평년값_전제_검증.md) — 평년값 모델의 숨은 전제가 틀렸음
> 5. [`docs/멘토링_1차.md`](docs/멘토링_1차.md) — 방향 전환 결정과 다음 단계

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
- **어종별 적정 환경조건**: [`data/external/species_conditions/fish_temperature_thresholds.csv`](data/external/species_conditions/fish_temperature_thresholds.csv) — 팀이 국립수산과학원 자료 기반으로 정리한 표이며 수치별 원문 검증 필요. 8개 주요 양식 어종(조피볼락·넙치·참돔·감성돔·숭어·농어·돌돔·방어)의 적정수온 범위 및 치사(고수온 위험) 수온. 염분·용존산소·pH는 아직 미확보.
- **양식방식별 수온 영향 비율**: [`data/external/farming_methods/farming_method_temp_impact.csv`](data/external/farming_methods/farming_method_temp_impact.csv) — 진행 중. 정량 영향 비율 미확정(가두리 100% 확정 표기 철회), 육상 유수식·순환여과식(RAS)은 실측 환수율/폐사율은 있으나 0~100% 비율 환산식 미정, 지수식은 자료 미확보. 자세한 내용은 [`docs/data_sources.md`](docs/data_sources.md)

## 팀 (공모전 위탁교육과정)

3인 팀 — 자료조사 / 데이터 전처리·분석 / 모델 구현·시각화 역할 분담 (기획서 참고)

## 2026-09-10: 첫 예측 파이프라인 실행 완료

현재는 자료 로딩·EDA를 넘어 **2021~2024 학습 → 2025 테스트 → 네 지역 모델 비교**까지 구현·실행했습니다. 어종 추천은 아직 미구현입니다.

주 모델은 **평년값(climatology)** — 각 날짜를 "과거 4년 같은 시기(±3일) 관측치의 평균"으로 예측하는 가장 단순한 방법. 조화회귀(sin/cos 계절 곡선)도 함께 돌려봤으나 성능이 거의 같아, 설명하기 쉬운 평년값을 주 모델로 사용합니다.

```bash
python -m pip install -r requirements-forecast.txt
python src/models/run_forecast.py
python -m unittest discover -s tests -v
```

- 고정 기준일 2024-12-31에서 2025년 전체 예측. 2025년 관측은 평가에만 사용.
- 긴 결측을 보간하지 않으며 실제 관측일 중 공통 평가일로 비교.
- 결과: `reports/forecast_2025/` (CSV, PNG, 설정·원자료 해시).
- 공통일 RMSE (평년값): 완도 1.55℃, 여수 1.52℃, 통영 1.80℃, 남해군 1.74℃. 전년 같은 날 Baseline 대비 약 27~34% 감소. (조화회귀는 1.47/1.40/1.76/1.74℃로 거의 동일)
- **한계**: 평년값이든 조화회귀든 매년 같은 계절 곡선을 반복할 뿐, 그 해의 이상값(갑작스러운 고수온 등)에는 반응하지 못함. 정작 예측하고 싶은 고수온 피크를 못 맞춤 → 다음 단계 핵심 과제.

[파일별 수정 이유·실행 방법·전체 결과·다음 단계](docs/forecast_pipeline.md)를 먼저 읽어 주세요. 조화회귀와 SARIMA/Prophet 래퍼는 코드에 유지. 원자료 경계의 2026-01-01은 이번 분석에서 제외합니다.
