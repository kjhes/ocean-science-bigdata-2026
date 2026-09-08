"""지역별 미래 수온 예측 모델 모듈 [메인 프로젝트].

기획서 "2. 지역별 미래 수온 예측" 대응.
여러 예측 모델을 동일한 인터페이스로 학습/평가할 수 있도록
간단한 래퍼(wrapper) 함수들을 제공한다.

현재 포함된 후보 모델:
    - naive_seasonal   : 계절성 나이브(작년 같은 날 값을 그대로 예측) - 베이스라인
    - moving_average   : 이동평균 베이스라인
    - sarima_forecast  : statsmodels SARIMA (계절성 있는 수온에 적합)
    - prophet_forecast : Facebook Prophet (연간 계절성 자동 처리)

TODO: 탐색적 분석(EDA) 결과를 바탕으로 실제 사용할 모델 후보를 좁히고,
      MAE/RMSE 비교표를 reports/ 에 정리한다.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import DATE_COL, TEMP_COL  # noqa: E402


def train_test_split_by_date(df: pd.DataFrame, split_date: str):
    """시계열이므로 랜덤 분할이 아닌 날짜 기준 분할 사용."""
    train = df[df[DATE_COL] < split_date]
    test = df[df[DATE_COL] >= split_date]
    return train, test


def evaluate(y_true, y_pred) -> dict:
    """기획서 지정 평가지표(MAE, RMSE) 계산."""
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    return {"MAE": round(mae, 4), "RMSE": round(rmse, 4)}


def naive_seasonal_forecast(train: pd.DataFrame, test: pd.DataFrame, period_days: int = 365) -> np.ndarray:
    """작년 같은 날짜의 수온을 그대로 예측값으로 사용하는 베이스라인."""
    train_idx = train.set_index(DATE_COL)[TEMP_COL]
    preds = []
    for d in test[DATE_COL]:
        ref_date = d - pd.Timedelta(days=period_days)
        nearest = train_idx.index[np.argmin(np.abs((train_idx.index - ref_date).days))]
        preds.append(train_idx.loc[nearest])
    return np.array(preds)


def moving_average_forecast(train: pd.DataFrame, horizon: int, window: int = 7) -> np.ndarray:
    """최근 window일 평균값을 horizon 기간만큼 그대로 예측 (단순 베이스라인)."""
    last_avg = train[TEMP_COL].tail(window).mean()
    return np.full(horizon, last_avg)


def sarima_forecast(train: pd.DataFrame, horizon: int, order=(1, 1, 1), seasonal_order=(1, 1, 1, 365)):
    """statsmodels SARIMA 예측.

    주의: seasonal_order의 계절 주기(365)는 일 단위 데이터 기준 예시이며,
    데이터 주기(시간/일/월)에 맞춰 조정 필요. 연산량이 크므로
    실제 적용 전 데이터 주기를 월 단위 등으로 리샘플링하는 것을 권장.
    """
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    series = train.set_index(DATE_COL)[TEMP_COL]
    model = SARIMAX(series, order=order, seasonal_order=seasonal_order,
                     enforce_stationarity=False, enforce_invertibility=False)
    fit = model.fit(disp=False)
    return fit.forecast(steps=horizon)


def prophet_forecast(train: pd.DataFrame, horizon: int, freq: str = "D"):
    """Facebook Prophet 예측. 연간 계절성이 강한 수온 데이터에 적합."""
    from prophet import Prophet

    prophet_df = train.rename(columns={DATE_COL: "ds", TEMP_COL: "y"})[["ds", "y"]]
    model = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
    model.fit(prophet_df)
    future = model.make_future_dataframe(periods=horizon, freq=freq)
    forecast = model.predict(future)
    return forecast.tail(horizon)[["ds", "yhat", "yhat_lower", "yhat_upper"]]


def compare_models(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    """여러 모델의 MAE/RMSE를 한 표로 비교 (기획서 '모델 성능 비교' 대응).

    TODO: 실제 데이터 확보 후 모델별 결과를 채워 reports/ 에 저장.
    """
    results = []

    y_true = test[TEMP_COL].values

    naive_pred = naive_seasonal_forecast(train, test)
    results.append({"model": "naive_seasonal", **evaluate(y_true, naive_pred)})

    ma_pred = moving_average_forecast(train, horizon=len(test))
    results.append({"model": "moving_average", **evaluate(y_true, ma_pred)})

    # SARIMA, Prophet은 연산량이 크므로 필요 시 주석 해제하여 사용
    # sarima_pred = sarima_forecast(train, horizon=len(test))
    # results.append({"model": "sarima", **evaluate(y_true, sarima_pred)})

    return pd.DataFrame(results).sort_values("RMSE")
