# CLAUDE.md

## 언어 규칙 (가장 중요)

- **모든 답변은 한국어로 한다.** 결과 보고, 중간 진행 메시지, 표, 오류 설명까지 전부 한국어.
- 코드 식별자·파일명·명령어만 원문 유지. 코드 주석과 문서도 한국어로 쓴다(기존 코드 스타일과 동일).

## 프로젝트 한 줄 요약

2026 해양과학 AI × 빅데이터 경진대회(중·고등부). 남해안 양식장 수온을 +1~7일 예측하고,
어종별 고수온 위험(정상/주의/위험)과 위험 수온 도달 예상일을 알려주는 앱을 만든다.

## 처음 읽을 것

1. [`PROGRESS.md`](PROGRESS.md) — 시간순 작업 기록. 맨 아래(2026-09-24, 09-25)가 최신 상태
2. [`README.md`](README.md) — 프로젝트 구조, 단계별 결과
3. [`app/README.md`](app/README.md) — 앱 사용법, 판정 규칙, 매일 갱신 방법
4. [`docs/연구_과정_서사.md`](docs/연구_과정_서사.md) — 발표용 시행착오 서사

## 현재 상태 (2026-09-25)

- **예측 모델**: 관측소별 선형회귀(`src/app/station_models.py`). 입력 = 수온 1~3일 전 + 전날·새벽 기상 +
  3·7·14일 기상 흐름 + 계절, 전날 수온 20℃ 이상이면 고수온 전용 모델. 하루씩 굴려 7일 예측.
  남해 수과원 관측소 96곳 학습 → 2026년 여름 검증 통과 89곳
- **양식장 위치 예보**: 주변 관측소 6곳 예보를 정규 크리깅으로 섞음 (`src/models/spatial_interp.py`)
- **경보**: 예상 수온 ≥ 어종 위험 수온 − 0.75℃ 이면 '위험' (모델의 급상승 과소예측 보정)
- **검증(2026 여름, 학습 미사용)**: ±1℃ 이내 +1일 98% / +3일 82% / +7일 65%, 28℃ 도달 71% 사전 포착
- **알려진 한계**: 여름 7일 수온 상승량은 과거 기상으로 약 15%, 미래 날씨·해양을 완벽히 알아도 약 30%만
  설명됨(양식장 앞바다 급상승은 국지적 현상). 데이터를 늘려도 도달일 예측은 더 좋아지지 않았음

## 자주 쓰는 명령

```bash
# 환경: Python 3.11 가상환경 (.venv). 기본 python(3.7)은 pandas 2를 못 씀
.venv/Scripts/python.exe -m pytest -q tests          # 테스트
.venv/Scripts/python.exe src/app/build_forecast.py    # 최신 자료 받아 앱 예보 생성 (app\update_forecast.bat 과 같음)
.venv/Scripts/python.exe src/app/station_models.py    # 관측소별 모델 재학습·검증
```

- Windows 콘솔에서 한글이 깨지면 `PYTHONIOENCODING=utf-8` 설정
- 앱 확인: `app/index.html` 더블클릭 (서버 불필요). 주소 예: `index.html?place=완도&species=넙치&date=2026-08-01`

## 데이터·키

- API 키는 저장소 루트 `.env` (git 제외): `DATA_GO_KR_API_KEY`(공공데이터포털 ASOS·ROMS),
  `KMA_FORECAST_API_KEY`(단기예보), `KMA_APIHUB_KEY`(기상청 API허브), `ROMS_API_KEY`.
  **키 값을 명령어·코드·문서에 직접 쓰지 않는다** — 항상 `.env`에서 읽는다
- 수과원 수온: 과거자료 다운로드(키 불필요, `src/data/nifs_past.py`) + 최근은 실시간 조회(`src/data/fetch_nifs_recent.py`)
- 기상: ASOS 12개 지점, 관측소마다 가장 가까운 지점 연결(`data/processed/nifs_station_catalog.csv`)

## 작업 규칙

- 새 실험·결정은 `PROGRESS.md`에 날짜별로 기록 (세션이 끊겨도 이어서 파악할 수 있게)
- 성능 수치는 학습에 쓰지 않은 기간으로 검증한 값만 발표용으로 쓴다
- 앱 화면: 대상이 중장년 양식업 종사자. 본문 18px 이상, 버튼 56px, 상태는 색+글자 병기,
  둥근 모서리·그림자·그라데이션 없이 각진 공공서비스 스타일 (AI가 만든 티 나지 않게)
- git: 이 폴더는 `kjhes/ocean-science-bigdata-2026`에 연결됨. 작업 브랜치에 커밋 후 푸시는 사용자가
  VS Code 소스 제어로 하거나 요청 시 진행
