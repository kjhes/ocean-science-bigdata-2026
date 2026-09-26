"""앱 데이터 생성: 최신 관측을 받아 관측소별 7일 예보를 계산하고 app/data/forecast.js 로 저장한다.

매일 한 번 실행 (예: 오전 6시):  python src/app/build_forecast.py   (또는 app/update_forecast.bat)
  1) 수과원 실시간 조회로 남해 전체 관측소 최근 40일 수온 갱신 (어제까지)
  2) 기상청 ASOS 12개 지점 최근 45일 갱신
  3) 관측소별 모델(src/app/station_models.py, 2026 검증 기준 통과한 곳)로 +1~+7일 예보
  4) 앱은 양식장 위치를 받으면 주변 관측소 예보를 크리깅으로 섞어 그 위치의 예보를 만든다
     (방법 근거: reports/spatial_experiment — 관측소 빼고 맞히기에서 최근접보다 오차 11% 적음)
네트워크 오류로 갱신에 실패하면 이미 받아둔 자료로 예보를 만들고, 기준일을 화면에 그대로 표시한다.
"""
from pathlib import Path
import json
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, SPECIES_CONDITIONS_DIR, DATA_PROCESSED_DIR  # noqa: E402
from data.nifs_past import load_nifs_daily  # noqa: E402
from app import final_model as fm  # noqa: E402
from app import station_models as sm  # noqa: E402

APP_DATA = ROOT_DIR / "app" / "data" / "forecast.js"
OFFICIAL_ALERT_TEMP = 28.0
ALERT_MARGIN = 0.75
ARCHIVE_FROM_MONTH = 6
# 앱의 빠른 선택 버튼: 기존 4개 대표 관측소
PRESETS = [("완도", "fwgk5"), ("여수", "km001"), ("통영", "fth59"), ("남해", "fnm5b")]
VARIOGRAM_PATH = ROOT_DIR / "reports" / "spatial_experiment" / "variogram.csv"


def refresh_data() -> list:
    notes = []
    today = pd.Timestamp.today().normalize()
    try:
        from data.fetch_nifs_recent import fetch_all_stations, update_recent_file
        update_recent_file(fetch_all_stations((today - pd.Timedelta(days=40)).strftime("%Y-%m-%d"),
                                              (today - pd.Timedelta(days=1)).strftime("%Y-%m-%d")))
    except Exception as e:  # 갱신 실패해도 기존 자료로 계속
        notes.append(f"수온 갱신 실패: {e}")
    try:
        from data.fetch_asos import fetch_station
        for stn in sorted(set(sm.load()["report"]["asos"])):
            fetch_station(int(stn), [today.year], refresh_recent_days=45)
    except Exception as e:
        notes.append(f"기상 갱신 실패: {e}")
    return notes


def load_species() -> list:
    sp = pd.read_csv(SPECIES_CONDITIONS_DIR / "fish_temperature_thresholds.csv")
    return [{"name": r.species, "opt_min": float(r.temp_opt_min), "opt_max": float(r.temp_opt_max),
             "danger": float(r.temp_lethal), "src": str(r.source)} for r in sp.itertuples()]


def r1(v):
    return None if v is None or not np.isfinite(v) else round(float(v), 1)


def build(refresh: bool = True) -> dict:
    notes = refresh_data() if refresh else []
    store = sm.load()
    rep = store["report"]
    rep = rep[rep["app_ok"]].reset_index(drop=True)
    daily = load_nifs_daily()
    recent = pd.read_csv(DATA_PROCESSED_DIR / "nifs_daily_recent.csv", parse_dates=["date"])
    cache, stations, archive = {}, [], {}
    for r in rep.itertuples():
        df = sm.station_frame(r.code, int(r.asos), cache, daily, recent)
        ok = df["sea"].notna() & df["air_mean"].notna()
        issue = df.index[ok].max()
        bundle = sm.bundle_for(store["models"][r.code])
        f = fm.forecast(df, bundle, "x", issue)
        obs = df.loc[issue - pd.Timedelta(days=13):issue, "sea"]
        stations.append({
            "code": r.code, "name": r.name, "lat": round(float(r.lat), 5), "lon": round(float(r.lon), 5),
            "issue": issue.strftime("%Y-%m-%d"), "today": r1(df.at[issue, "sea"]),
            "obs": [r1(v) for v in obs.reindex(pd.date_range(issue - pd.Timedelta(days=13), issue)).to_numpy()],
            "fc": [r1(v) for v in f["pred"]],
            "err": [round(float(getattr(r, f"rmse_h{h}")), 2) for h in range(1, 8)],
            "acc3": round(float(r.within1_h3), 2),
        })
        # 지난 예보: 올해 6월 1일부터 어제까지 매일 냈을 예보 + 실제 (모델은 전년도까지 학습 → 본 적 없는 기간)
        arc = {}
        for d in pd.date_range(pd.Timestamp(issue.year, ARCHIVE_FROM_MONTH, 1), issue - pd.Timedelta(days=1)):
            if not ok.get(d, False):
                continue
            fa = fm.forecast(df, bundle, "x", d)
            arc[d.strftime("%Y-%m-%d")] = [r1(df.at[d, "sea"])] + [r1(v) for v in fa["pred"]] + \
                                          [r1(df["sea"].get(x, np.nan)) for x in fa["date"]]
        archive[r.code] = arc

    vg = pd.read_csv(VARIOGRAM_PATH, index_col=0)["직선"]
    data = {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "alert_margin": ALERT_MARGIN,
        "official_alert_temp": OFFICIAL_ALERT_TEMP,
        "validation": fm.VALIDATION,
        "kriging": {"nugget": float(vg["nugget"]), "sill": float(vg["sill"]), "range": float(vg["range"]),
                    "neighbors": 6, "warn_km": 10, "max_km": 20},
        "presets": [{"label": lab, "code": code} for lab, code in PRESETS],
        "species": load_species(),
        "stations": stations,
        "archive": archive,
        "notes": notes,
    }
    APP_DATA.parent.mkdir(parents=True, exist_ok=True)
    APP_DATA.write_text("// build_forecast.py 가 생성한 파일입니다. 직접 수정하지 마세요.\nwindow.FORECAST = "
                        + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    return data


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    d = build(refresh="--no-refresh" not in sys.argv)
    print(f"관측소 {len(d['stations'])}곳 예보 생성")
    for s in d["stations"]:
        if s["code"] in {c for _, c in PRESETS}:
            print(f"  {s['name']}: 기준일 {s['issue']} {s['today']}℃ → {s['fc']}")
    for n in d["notes"]:
        print("주의:", n)
    print(f"저장: {APP_DATA} ({APP_DATA.stat().st_size / 1e6:.1f}MB)")
