"""달력으로 연간 계절 곡선을 학습하는 설명 가능한 선형회귀.

학습 수온이 없는 행은 제외하며 보간하지 않는다. 예측 시에는 날짜만 사용한다.
2025년 관측이나 미래 실제 기상값을 입력받지 않는다.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


def calendar_matrix(dates, harmonics=2, trend=False):
    dates = pd.DatetimeIndex(dates)
    # 같은 달/일은 같은 위상. 윤일은 2/28과 3/1의 중간으로 둔다.
    day = dates.dayofyear.to_numpy(dtype=float) - 1
    day -= (dates.is_leap_year & (dates.month > 2)).astype(int)
    day[(dates.month == 2) & (dates.day == 29)] = 58.5
    phase = 2 * np.pi * day / 365
    columns = [f(k * phase) for k in range(1, harmonics + 1) for f in (np.sin, np.cos)]
    if trend:
        columns.append(np.asarray((dates - pd.Timestamp('2021-01-01')).days) / 365.2425)
    return np.column_stack(columns)


class HarmonicRegression:
    def __init__(self, harmonics=2, trend=False):
        self.harmonics = harmonics
        self.trend = trend
        self.model = LinearRegression()

    def fit(self, dates, temperatures):
        y = np.asarray(temperatures, dtype=float)
        valid = np.isfinite(y)
        x = calendar_matrix(dates, self.harmonics, self.trend)
        if valid.sum() <= x.shape[1] + 1:
            raise ValueError('조화회귀에 필요한 관측값이 부족합니다.')
        self.model.fit(x[valid], y[valid])
        return self

    def predict(self, dates):
        return self.model.predict(calendar_matrix(dates, self.harmonics, self.trend))
