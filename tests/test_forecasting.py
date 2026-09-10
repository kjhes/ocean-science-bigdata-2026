"""윤년·결측·미래 정보 누수를 검증하는 회귀 테스트. unittest만 사용."""
import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from models.forecast import naive_seasonal_forecast
from models.run_forecast import fit_predict, gap_table
from features.preprocess import handle_missing_values


class ForecastTests(unittest.TestCase):
    def test_calendar_year_and_missing_reference(self):
        train = pd.DataFrame({'date':pd.to_datetime(['2024-01-01','2024-01-02','2024-03-01']),
                              'temperature':[10.,11.,15.]})
        test = pd.DataFrame({'date':pd.to_datetime(['2025-01-01','2025-03-01','2025-03-02'])})
        np.testing.assert_allclose(naive_seasonal_forecast(train,test), [10.,15.,np.nan], equal_nan=True)

    def test_test_values_and_2026_do_not_change_predictions(self):
        idx = pd.date_range('2021-01-01','2026-01-01')
        s = pd.Series(17 + 8*np.sin(2*np.pi*idx.dayofyear/365.2425), index=idx)
        s.loc['2022-03-01':'2022-04-15'] = np.nan
        _, first, settings, validation = fit_predict(s)
        changed = s.copy()
        changed.loc['2025':] = 9999.0
        _, second, settings2, validation2 = fit_predict(changed)
        self.assertEqual(settings, settings2)
        pd.testing.assert_frame_equal(validation, validation2)
        for name in first:
            np.testing.assert_allclose(first[name], second[name], equal_nan=True)

    def test_long_gap_not_partially_filled_and_edges_preserved(self):
        idx = pd.date_range('2023-01-01', periods=12)
        values = [np.nan,10,np.nan,12,np.nan,np.nan,np.nan,np.nan,17,np.nan,19,np.nan]
        frame = pd.DataFrame({'date':idx, 'region':'완도', 'temperature':values})
        result = handle_missing_values(frame, max_gap=3).temperature
        self.assertEqual(result.iloc[2],11)
        self.assertTrue(result.iloc[4:8].isna().all())
        self.assertTrue(pd.isna(result.iloc[0]) and pd.isna(result.iloc[-1]))
        self.assertEqual(max(x['days'] for x in gap_table(pd.Series(values,index=idx),'완도')),4)


if __name__ == '__main__':
    unittest.main()
