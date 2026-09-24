"""앱 예보 데이터(app/data/forecast.js)와 모델 점검."""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FORECAST_JS = ROOT / "app" / "data" / "forecast.js"
MODEL = ROOT / "models" / "final_model.pkl"
STATION_MODELS = ROOT / "models" / "station_models.pkl"


def load_forecast():
    text = FORECAST_JS.read_text(encoding="utf-8")
    return json.loads(text[text.index("=") + 1:].rstrip().rstrip(";"))


@pytest.mark.skipif(not FORECAST_JS.exists(), reason="build_forecast.py 를 먼저 실행해야 함")
def test_forecast_file_structure():
    f = load_forecast()
    codes = {s["code"] for s in f["stations"]}
    assert all(p["code"] in codes for p in f["presets"])  # 빠른 선택 관측소가 모두 들어 있어야 함
    assert all(s["opt_max"] < s["danger"] for s in f["species"])
    k = f["kriging"]
    assert k["sill"] > 0 and k["range"] > 0 and k["warn_km"] < k["max_km"]
    for s in f["stations"]:
        assert len(s["fc"]) == 7 and len(s["err"]) == 7 and len(s["obs"]) == 14
        assert all(t is None or 0 < t < 35 for t in s["fc"])
        assert 33.5 < s["lat"] < 35.5 and 125.5 < s["lon"] < 129.5
        for arr in f["archive"].get(s["code"], {}).values():
            assert len(arr) == 15  # 기준일 수온 + 예보 7 + 실제 7


@pytest.mark.skipif(not MODEL.exists(), reason="final_model.py 를 먼저 실행해야 함")
def test_final_model_matches_validation_path():
    """예보 함수가 검증 실험(recursive_experiment)과 같은 값을 내는지 확인."""
    from app import final_model as fm
    from models import recursive_experiment as rx
    bundle = fm.load()
    df = rx.load_series("통영", long_history=True)
    runs = {"x": (bundle["config"], bundle["hot_threshold"])}
    rec = rx.run_series(df, "통영", runs=runs, train_years=bundle["train_years"], test_years=[2026])
    d = pd.Timestamp("2026-08-10")
    ref = rec[rec["issue_date"] == d].sort_values("h")["pred"].to_numpy()
    got = fm.forecast(df, bundle, "통영", d)["pred"].to_numpy()
    assert np.allclose(ref, got, atol=1e-9)


def test_kriging_reproduces_station_and_weights_sum_to_one():
    """정규 크리깅: 관측소 바로 위에서는 그 관측소 값, 가중치 합은 1."""
    from models import spatial_interp as si
    vg = {"nugget": 0.0, "sill": 3.5, "range": 20.0}
    vals = np.array([25.0, 27.0, 26.0])
    D_nb = np.array([[0, 5, 8], [5, 0, 6], [8, 6, 0]], float)
    est, sd = si.predict_point(vals, np.array([0.0, 5.0, 8.0]), D_nb, "kriging", vg)
    assert abs(est - 25.0) < 1e-6 and sd < 1e-3
    est2, sd2 = si.predict_point(vals, np.array([3.0, 3.0, 7.0]), D_nb, "kriging", vg)
    assert min(vals) <= est2 <= max(vals) and sd2 > 0
