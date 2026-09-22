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
├── docs/                       기획서, 방향전환 근거 문서, 데이터 소스 조사, reference/(공식 PDF)
├── 수온 데이터/                  일별 원자료 (완도·여수·통영·남해군, 2021~2025)
├── 기상 데이터/                  ASOS 시간자료 (기온·풍속·강수, 4지점, 2021~2025)
├── data/
│   ├── raw/                    (원자료는 위 '수온 데이터/' 폴더를 그대로 참조, 여기는 예비용)
│   ├── processed/               전처리/파싱된 산출물 (예: regional_yearly_summary.csv)
│   └── external/
│       ├── species_conditions/   어종별 적정 수온·치사수온 (fish_temperature_thresholds.csv)
│       ├── farming_methods/      양식방식별(가두리/유수/지수식) 위험도 자료 — 대부분 미확정
│       ├── warning_criteria/     국립수산과학원 공식 고수온 경보 3단계 기준
│       └── khoa_station/         KHOA 조위관측소 실측(좌표 확인용, 3개월 샘플)
├── src/
│   ├── config.py                 지역명/경로/색상 등 공통 설정
│   ├── data/                     원자료 로딩 (load_data.py, load_weather.py, load_weather_forecast.py, load_roms.py)
│   ├── features/                 전처리 (preprocess.py)
│   ├── models/                   forecast.py(평년값/조화회귀, baseline), short_term_forecast.py(현재 주 모델),
│   │                              alert.py(경보 판정), forecast_alert.py(예측→경보 연결)
│   ├── analysis/                 anomaly_2024.py(이상값 분해)
│   └── visualization/            시각화 (plots.py)
├── notebooks/                   EDA용 주피터 노트북
└── reports/                     forecast_2025/(baseline), short_term_forecast/, alert_reconstruction/,
                                  forecast_alert/, anomaly_2024/, weather_forecast_realtime/, figures/
```

## 시작하기

```bash
pip install -r requirements.txt
python -m pip install python-dotenv     # .env의 API 키 로딩용 (requirements.txt에도 포함)
python src/data/load_data.py            # 원자료 로딩 확인
python src/models/short_term_forecast.py  # 현재 주 모델(단기 선형회귀) 실행
```

ROMS·기상청 단기예보 API를 쓰는 스크립트(`load_roms.py`, `load_weather_forecast.py`)는 저장소 루트에
`.env` 파일로 `ROMS_API_KEY`, `KMA_FORECAST_API_KEY`를 넣어야 한다 (`.env`는 git에 포함되지 않음).

## 데이터

- **수온 시계열**: `수온 데이터/{지역(관측소)}/*.csv` — 완도(군의)·여수(신월)·통영(학림)·남해(미조) 4개 관측소, 2021-01-01~2025-12-31 일별 표층 수온(`wtemS`). 자세한 내용은 [`docs/data_sources.md`](docs/data_sources.md).
- **기상 시계열**: `기상 데이터/{지역}/ASOS_*_hourly.csv` — 기상청 ASOS 4지점(완도170·여수168·통영162·남해295) 시간자료, 기온·풍속·강수. 기상청 API허브 실측값과 대조해 정합성 검증 완료(불일치 0건).
- **어종별 적정 환경조건**: [`data/external/species_conditions/fish_temperature_thresholds.csv`](data/external/species_conditions/fish_temperature_thresholds.csv) — 팀이 국립수산과학원 자료 기반으로 정리한 표이며 수치별 원문 검증 필요. 8개 주요 양식 어종의 적정수온 범위 및 치사(고수온 위험) 수온. 염분·용존산소·pH는 아직 미확보.
- **고수온 경보 공식 기준**: [`data/external/warning_criteria/high_temp_warning_criteria.csv`](data/external/warning_criteria/high_temp_warning_criteria.csv) — 국립수산과학원 「자연재해 대비 양식장 관리요령」의 관심/주의보/경보 3단계 4조건(28℃ / 3일지속 / 전일대비3~5℃ / 평년대비2~3℃).
- **양식방식별 수온 영향 비율**: [`data/external/farming_methods/farming_method_temp_impact.csv`](data/external/farming_methods/farming_method_temp_impact.csv) — **아직 미해결.** 4개 방식(가두리/유수식/지수식/RAS) 모두 0~100% 정량 비율 미확정. 유수식·RAS는 실측 환수율/폐사율은 있으나 환산 공식이 없고, 지수식은 자료 자체가 없음. 어종 추천 로직이 이 때문에 막혀 있음.

## 팀 (공모전 위탁교육과정)

3인 팀 — 자료조사 / 데이터 전처리·분석 / 모델 구현·시각화 역할 분담 (기획서 참고)

## 현재 상태 (2026-09-22 기준)

> **2026-09-10 1차 멘토링에서 방향 전환**: 장기(수년) 수온 예측 → **단기(1일) 예측 + 고수온 경보**.
> 전환 근거는 위 배너의 문서 5개, 이후 실제 구현·검증 경과는 [`PROGRESS.md`](PROGRESS.md)에 시간순으로 있다.

### 1단계 — 장기 예측 시도 (현재는 baseline으로만 사용)

평년값(climatology)·조화회귀를 2021~2024 학습 → 2025 테스트로 검증. 공통일 RMSE 완도 1.55℃ /
여수 1.52℃ / 통영 1.80℃ / 남해군 1.74℃. 그러나 **2024년(고수온 피해가 실제 발생한 해)만
크게 놓쳤고**, 원인 분해 결과 "정점이 8월에서 9월로 밀렸다"는 사실과 "평년값의 숨은 전제(같은
시기면 환경도 비슷하다)가 틀렸다"는 결론에 도달해 폐기 → 단기 예측으로 전환.
상세: [`docs/forecast_pipeline.md`](docs/forecast_pipeline.md), 결과 `reports/forecast_2025/`.

### 2단계 — 단기(1일) 예측 + 경보 (현재 주 모델)

기상청 ASOS 4지점 기온·풍속·강수를 결합한 **선형회귀** 모델 채택 (지속성/평년값/랜덤포레스트보다
우수). 학습 2021~2023, 검증 2024~2025.

- **예측 성능(RMSE)**: 완도 0.26℃ / 여수 0.25℃ / 통영 0.27℃ / 남해군 0.36℃ (`reports/short_term_forecast/metrics.csv`)
- **경보 재현율**: 국립수산과학원 공식 4조건을 실측에 적용해 2021~2025 경보 이력을 재구성한 뒤,
  예측값을 같은 기준에 대입해 검증 — 완도 80% / 여수 90% / 통영 78% / 남해군 87%
  (`reports/forecast_alert/summary.csv`, `reports/alert_reconstruction/`)
- **한계**: 급등일(전일 대비 큰 폭 상승) 과소예측 경향이 남아 있음(완화됐으나 완전 해소는 아님).
  ROMS 해양수치모델 도입은 3가지 경로(실시간 API 8일치만 제공·직접계산 불가·재분석자료 기간
  안 겹침)를 확인 후 보류.
- 미착수: **어종별·양식방식별 경보 연결** — 원래 목적(지역·양식방식별 어종 추천)인데
  양식방식 위험도 자료(위 참고)가 막혀 있어 아직 못 붙였음.

상세 실험 로그: [`docs/단기예측_환경변수_검증.md`](docs/단기예측_환경변수_검증.md), 압축 요약:
[`docs/현재_상태_요약.md`](docs/현재_상태_요약.md), 경보 기준·대응요령: [`docs/고수온_경보_및_대응요령.md`](docs/고수온_경보_및_대응요령.md),
2차 멘토링 발표 총정리: [`docs/2차_멘토링_준비.md`](docs/2차_멘토링_준비.md).
