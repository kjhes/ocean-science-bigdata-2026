"""최종 모델 개선 실험: '예보일 이후 날씨를 무엇으로 채우나' + '계절(날짜) 변수 유무'.

관찰: 앱의 지난 예보(남해 2026-08-10)에서 실제 수온은 27℃ 부근을 유지했는데 모델은 7일 뒤 25℃까지
떨어진다고 예측. 원인 후보
  1) 예보일 이후 기상을 '예보일 값 그대로'로 채움 → 예보일이 우연히 서늘하면 7일 내내 서늘하다고 계산
  2) 계절(doy sin/cos) 변수가 수온을 평년 수준으로 끌어당김
비교
  날씨 채우기: 예보일값(현재) / 최근7일평균 / 평년값(학습기간 같은 날짜 ±7일 평균)
  계절 변수: 있음(현재) / 없음
평가: [A] 2012~2023 학습 → 2024~2025 여름, [B] 2012~2025 학습 → 2026 여름(모델 선택에 안 쓴 자료)
"""
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, REGIONS  # noqa: E402
from models.pattern_experiment import SUMMER_MONTHS, HORIZONS  # noqa: E402
from models import recursive_experiment as rx  # noqa: E402

PERIODS = {"A:2024~25": (list(range(2012, 2024)), [2024, 2025]), "B:2026": (list(range(2012, 2026)), [2026])}
BASE_COLS = rx.CONFIGS["기존+기간평균패턴"]
COLSETS = {"계절O": BASE_COLS, "계절X": [c for c in BASE_COLS if c not in ("doy_sin", "doy_cos")]}
FILLS = ["예보일값", "최근7일평균", "평년값"]
HOT = 20.0
DANGER, MARGINS = 28.0, [0.5, 0.75, 1.0]


def weather_normals(df: pd.DataFrame, years) -> pd.DataFrame:
    """학습기간 기상의 날짜별 평년값 (같은 날짜 ±7일 창 평균)."""
    w = df.loc[df.index.year.isin(years), rx.WX_COLS]
    doy = w.index.dayofyear.where(w.index.dayofyear < 366, 365)
    daily = w.groupby(doy).mean().reindex(range(1, 366))
    ext = pd.concat([daily.iloc[-7:], daily, daily.iloc[:7]])
    smooth = ext.rolling(15, center=True, min_periods=5).mean().iloc[7:-7]
    smooth.index = range(1, 366)
    return smooth


def run():
    rows_err, rows_cross = [], []
    for pname, (train_years, test_years) in PERIODS.items():
        for region in REGIONS:
            df = rx.load_series(region, long_history=True)
            a_all, feats, target, summer_train, calm_cut = rx.build_features(df, train_years)
            normals = weather_normals(df, train_years)
            dates = df.index
            for cname, cols in COLSETS.items():
                ok = summer_train & target.notna().to_numpy() & feats[cols].notna().all(axis=1).to_numpy()
                hot = ok & (feats["sea_lag1"] >= HOT).to_numpy()
                base = LinearRegression().fit(feats.loc[ok, cols].to_numpy(), target[ok].to_numpy())
                hotm = LinearRegression().fit(feats.loc[hot, cols].to_numpy(), target[hot].to_numpy())
                issue_idx = [i for i in range(rx.LOOKBACK, len(df) - 7)
                             if dates[i].year in test_years and np.isfinite(a_all["sea"][i])
                             and all(dates[i + h].month in SUMMER_MONTHS for h in HORIZONS)]
                for fill in FILLS:
                    name = f"{fill}|{cname}"
                    for i in issue_idx:
                        lo = i - rx.LOOKBACK
                        w = {k: v[lo:i + 8].copy() for k, v in a_all.items()}
                        t = rx.LOOKBACK
                        w["sea"][t + 1:] = np.nan
                        for c in rx.WX_COLS:
                            if fill == "예보일값":
                                w[c][t + 1:] = w[c][t]
                            elif fill == "최근7일평균":
                                w[c][t + 1:] = np.nanmean(w[c][t - 6:t + 1])
                            elif fill == "혼합":  # 예보일값과 최근7일평균을 반씩
                                w[c][t + 1:] = 0.5 * w[c][t] + 0.5 * np.nanmean(w[c][t - 6:t + 1])
                            else:
                                doys = [min(dates[i + h].dayofyear, 365) for h in HORIZONS]
                                w[c][t + 1:] = normals.loc[doys, c].to_numpy()
                        preds = []
                        for h in HORIZONS:
                            x = rx.day_features(w, t + h, dates[i + h].dayofyear, calm_cut)
                            xv = np.array([[x[c] for c in cols]], dtype=float)
                            m = hotm if x["sea_lag1"] >= HOT else base
                            p = float(m.predict(xv)[0]) if np.isfinite(xv).all() else np.nan
                            w["sea"][t + h] = p
                            preds.append(p)
                        actual = a_all["sea"][i + 1:i + 8]
                        for h, (p, y) in enumerate(zip(preds, actual), start=1):
                            if np.isfinite(p) and np.isfinite(y):
                                rows_err.append({"period": pname, "model": name, "region": region, "h": h, "err": p - y})
                        today = a_all["sea"][i]
                        if today < DANGER and np.isfinite(preds).all() and np.isfinite(actual).all():
                            av = actual >= DANGER
                            af = av.argmax() + 1 if av.any() else 0
                            for mg in MARGINS:
                                pv = np.array(preds) >= DANGER - mg
                                pf = pv.argmax() + 1 if pv.any() else 0
                                rows_cross.append({"period": pname, "model": name, "margin": mg, "af": af, "pf": pf})
            print(f"  {pname} {region} 완료", flush=True)
    return pd.DataFrame(rows_err), pd.DataFrame(rows_cross)


def main():
    warnings.filterwarnings("ignore", category=UserWarning)
    out = ROOT_DIR / "reports" / "improve_experiment"
    out.mkdir(parents=True, exist_ok=True)
    err, cross = run()
    err.to_csv(out / "errors.csv", index=False, encoding="utf-8-sig")
    cross.to_csv(out / "crossing.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 220)

    g = err.groupby(["period", "model", "h"])["err"]
    tab = pd.DataFrame({"RMSE": g.apply(lambda e: np.sqrt((e ** 2).mean())), "1℃이내": g.apply(lambda e: (e.abs() <= 1).mean()),
                        "편향": g.mean()}).unstack("h")
    show = tab.loc[:, [("RMSE", 1), ("RMSE", 3), ("RMSE", 7), ("1℃이내", 3), ("1℃이내", 7), ("편향", 7)]]
    print("\n=== 수온 정확도 (4개 지점 합산) ===")
    print(show.round(3).to_string())

    c = cross.assign(hit=(cross.af > 0) & (cross.pf > 0), fa=(cross.af == 0) & (cross.pf > 0), ev=cross.af > 0,
                     derr=np.where((cross.af > 0) & (cross.pf > 0), (cross.pf - cross.af).abs(), np.nan))
    s = c.groupby(["period", "model", "margin"]).agg(ev=("ev", "sum"), hit=("hit", "sum"), fa=("fa", "sum"), day_err=("derr", "mean"))
    s["recall"] = s.hit / s.ev
    s["precision"] = s.hit / (s.hit + s.fa)
    s["F1"] = 2 * s.hit / (s.hit + s.fa + s.ev)
    s.to_csv(out / "crossing_summary.csv", encoding="utf-8-sig")
    print("\n=== 28℃ 도달일 (F1 = 잡은 비율·정확도 균형) ===")
    print(s[["ev", "recall", "precision", "F1", "day_err"]].unstack("margin").round(2).to_string())
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
