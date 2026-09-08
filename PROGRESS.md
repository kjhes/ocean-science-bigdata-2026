# 진행 상황 기록

> Claude Code 세션이 다른 노트북으로 이어지지 않을 경우를 대비한 기록. 새 세션에서는
> 이 파일 + [`docs/기획서.md`](docs/기획서.md) + [`docs/data_sources.md`](docs/data_sources.md)를
> 먼저 읽으면 맥락을 파악할 수 있다.

## 2026-09-07 ~ 09-08: 프로젝트 초기 세팅

1. `docs/기획서.md`에 공모전 기획서 원문 저장
2. 프로젝트 폴더 구조 생성: `data/{raw,processed,external}`, `src/{data,features,models,visualization}`, `notebooks/`, `reports/figures/`, `docs/`
3. `requirements.txt`, `.gitignore` 작성
4. `docs/data_sources.md`: 수온 시계열 / 어종별 적정조건 / 양식방식 관련 공공데이터 소스 웹 조사 정리
5. 전처리/모델/시각화 파이프라인 뼈대 작성 (`src/config.py`, `src/data/load_data.py`, `src/features/preprocess.py`, `src/models/forecast.py`, `src/visualization/plots.py`)
6. EDA 노트북 템플릿 작성: `notebooks/01_eda_수온데이터.ipynb`

## 2026-09-08: 실제 수온 원자료 반영

팀원이 `수온 데이터/` 폴더에 실제 데이터 추가:
- `[자료 정리] 남해 지역 5년 수온 데이터 분석.txt` — 연도별 요약 통계 (일별 원자료 아님)
- `완도(군의)/`, `여수(신월)/`, `통영(학림)/`, `남해(미조)/` — 각 지역 2021~2025년 **일별** 수온 CSV (연도별 파일)

작업 내용:
- `src/data/parse_yearly_summary.py` 작성: 위 txt를 파싱해 `data/processed/regional_yearly_summary.csv`로 저장 (24행 = 4지역 × (5년+전체))
- 원자료 실제 컬럼 구조 확인 (`obsrvnDt`, `wtemM`/`wtemS`/`wtemB` — 지역별로 보유한 수심 컬럼이 다름). 4개 지역 공통인 **wtemS(표층)**을 표준 변수로 채택
- `src/config.py`에 `RAW_TEMP_DIR`, `REGION_FOLDER_MAP`, `REGION_COLORS`(dataviz 스킬 검증 팔레트) 추가
- `src/data/load_data.py`를 실제 데이터 구조에 맞게 재작성 — 연도별 CSV 병합, 연 경계 중복일자 제거, 표층 수온 컬럼 매핑
- 파이프라인 end-to-end 검증 완료:
  - 4개 지역 로드 → 7,308행 (1,827일 × 4지역), 결측 204건
  - `preprocess_pipeline` 통과 후 결측 0건, 날짜 누락 없음 (2021-01-01~2026-01-01 연속)
  - 이상치(IQR) 제거는 현재 기준으로는 걸러지는 행 없음 (계절성 때문에 전체 IQR이 느슨함 — TODO로 표시해둠, 필요시 월별 IQR로 개선)
- 차트 4종 생성 및 육안 확인 완료 (`reports/figures/`):
  - `region_trend.png`: 지역별 5년 수온 추이 (뚜렷한 계절 패턴 확인됨)
  - `region_comparison_bar.png`: 지역별 평균/최고 수온
  - `완도_monthly_boxplot.png`: 완도 월별 수온 분포
  - `high_temp_alert_days.png`: 지역별 연도별 고수온 경보일수 — **2024년에 전 지역 경보일수 급증**(완도 35일, 여수 37일, 통영 16일, 남해군 35일)이 뚜렷하게 나타남. 기획서의 "2026년 여름 고수온 피해" 배경과 함께 보고서에서 강조할 만한 핵심 발견.
  - 시각화는 `dataviz` 스킬의 고정 카테고리 팔레트(파랑/주황/아쿠아/노랑) 적용 — 지역이 필터링돼도 항상 같은 색 유지

## 2026-09-08 (계속): 팀원 기여 반영 - 어종별 적정 수온

- 팀원(rlqja1322)이 GitHub에 어종별 수온 위험도 분석 스크립트 커밋 (`주요 양식어종별 수온 데이터 코드`)
- 국립수산과학원 자료 기반 8개 어종(조피볼락·넙치·참돔·감성돔·숭어·농어·돌돔·방어) 적정수온/치사수온 수치는 신뢰하고 채택
- 원본 스크립트는 본인 데스크톱 경로에 하드코딩되어 있어 이 저장소에서 바로 실행 불가 → 핵심 수치만 추출해 `data/external/species_conditions/fish_temperature_thresholds.csv`로 분리, README/data_sources.md에 위치 명시
- 아직 안 한 것: 이 기준표를 실제 예측 수온과 비교해 "환경 적합도 점수"를 계산하는 로직 (다음 설계 논의 대상)

## 2026-09-08 (계속): 양식방식별 수온 영향 비율 (초기 추정치)

- 추천 점수 설계 논의: 최종 점수 = 온도 적합도 점수 + (100-온도 적합도) × 양식방식 보정계수 × k 구조로 진행하기로 함
- 양식방식별 보정계수 근거 조사 중 실측 자료 발견: 「해수 순환여과양식시스템 기술 개발」(ScienceON/KISTI, TRKO201900014050, 거제·넙치) — RAS 누적폐사율 9.7% vs 유수식 56.1%
- 가두리식은 정량적 비교자료를 못 찾음 → 사용자가 4개 방식(해상 가두리식/육상 유수식/지수식/순환여과식RAS)에 대해 수온 영향 비율(100%/80%/60%/30%)을 초기 가중치 예시로 직접 제시 → `data/external/farming_methods/farming_method_temp_impact.csv`로 저장 (공식 통계 아님을 명시)
- `src/config.py`의 `FARMING_METHODS`를 기획서의 3분류에서 4분류로 세분화

## 다음 액션 아이템 (우선순위 순)

1. **어종별 적정 환경조건 데이터** 수집 — 아직 미착수. `docs/data_sources.md`의 국립수산과학원 양식기술서 등 참고해 3~5개 주요 어종(강도다리, 조피볼락/우럭, 넙치 등) 선정 후 `data/external/species_conditions/`에 정리
2. **양식 방식별 위험도 근거 자료** 조사 — 미착수. `data/external/farming_methods/`에 정리
3. 계절성 반영한 이상치 탐지 방식 개선 검토 (`src/features/preprocess.py`의 `remove_outliers_iqr` TODO)
4. `src/models/forecast.py`의 SARIMA/Prophet 실제 실행 및 MAE/RMSE 비교 (`compare_models` 함수 확장) — 데이터 주기(일별)에 맞춰 `seasonal_order` 조정 필요
5. EDA 노트북(`01_eda_수온데이터.ipynb`) 실제 실행 및 셀 결과 채우기
6. git 커밋 여부 확인 — 현재까지 작업은 아직 커밋 안 함 (사용자 요청 시 진행)

## 참고: 실행 확인용 커맨드

```bash
python src/data/load_data.py              # 로더 동작 확인
python src/data/parse_yearly_summary.py   # 연도별 요약 텍스트 파싱
```
