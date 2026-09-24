"""관측소 하나 빼고 맞히기(leave-one-station-out)로 공간 보간 방법 비교.

목적: 양식장 주소(임의 위치)의 수온을 '가장 가까운 관측소 값'보다 잘 추정하는 방법이 있는지.
양식장 실측이 없으므로, 수과원 관측소 하나를 숨기고 나머지로 그 자리 수온을 추정해 실제와 비교한다.

- 자료: 수과원 남해 관측소 일평균 표층수온 (좌표 있는 관측소, 제주 제외)
- 변동도(거리에 따른 수온 차이 구조): 2021~2022 여름으로 맞춤 / 평가: 2023~2025 여름(6~9월)
- 비교: 최근접·IDW·크리깅 × 직선거리·바닷길거리
"""
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR  # noqa: E402
from data.nifs_past import load_nifs_daily  # noqa: E402
from models import spatial_interp as si  # noqa: E402

SUMMER = [6, 7, 8, 9]
FIT_YEARS, EVAL_YEARS = [2021, 2022], [2023, 2024, 2025]
MIN_DAYS = 150
METHODS = [("최근접", "nearest", "직선"), ("IDW", "idw", "직선"), ("크리깅", "kriging", "직선"),
           ("최근접", "nearest", "바닷길"), ("IDW", "idw", "바닷길"), ("크리깅", "kriging", "바닷길")]


def main():
    warnings.filterwarnings("ignore")
    out = ROOT_DIR / "reports" / "spatial_experiment"
    out.mkdir(parents=True, exist_ok=True)

    d = load_nifs_daily()
    d = d[d["date"].dt.month.isin(SUMMER) & d["date"].dt.year.isin(FIT_YEARS + EVAL_YEARS)]
    st = si.load_stations(d)
    wide = d[d["code"].isin(st["code"])].pivot_table(index="date", columns="code", values="temperature")
    keep = wide.columns[wide.notna().sum() >= MIN_DAYS]
    st = st[st["code"].isin(keep)].set_index("code").loc[keep].reset_index()
    wide = wide[keep]
    print(f"관측소 {len(st)}곳, 여름 {len(wide)}일")

    lat, lon = st["lat"].to_numpy(), st["lon"].to_numpy()
    D = {"직선": si.straight_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])}
    sg = si.SeaGraph()
    pts = list(zip(lat, lon))
    D["바닷길"] = sg.distances(pts, pts)
    snap = np.array([sg.node(a, b)[1] for a, b in pts])
    print(f"바닷길: 육지 칸에 찍혀 바다로 옮긴 관측소 {int((snap > 0.3).sum())}곳 (최대 {snap.max():.1f}km)")
    ratio = D["바닷길"] / np.maximum(D["직선"], 0.1)
    iu = np.triu_indices(len(st), 1)
    print(f"바닷길/직선 거리 비율: 중앙값 {np.median(ratio[iu]):.2f}, 1.5배 이상인 쌍 {np.mean(ratio[iu] > 1.5):.0%}")

    fit = wide[wide.index.year.isin(FIT_YEARS)].to_numpy()
    vg = {k: si.fit_variogram(fit, D[k]) for k in D}
    for k, v in vg.items():
        print(f"변동도({k}): 너겟 {v['nugget']:.3f}, 문턱 {v['sill']:.3f}, 범위 {v['range']:.1f}km")

    ev = wide[wide.index.year.isin(EVAL_YEARS)]
    X = ev.to_numpy()
    rows = []
    for j in range(len(st)):
        others = np.r_[0:j, j + 1:len(st)]
        nn_km = D["직선"][j, others].min()
        for t in range(len(ev)):
            y = X[t, j]
            if not np.isfinite(y):
                continue
            avail = others[np.isfinite(X[t, others])]
            if len(avail) < 3:
                continue
            rec = {"code": st.at[j, "code"], "name": st.at[j, "name"], "date": ev.index[t], "actual": y, "nn_km": nn_km}
            for label, m, dk in METHODS:
                est, sd = si.predict_point(X[t, avail], D[dk][j, avail], D[dk][np.ix_(avail, avail)], m, vg[dk])
                rec[f"{label}|{dk}"] = est
                if m == "kriging":
                    rec[f"sd|{dk}"] = sd
            rows.append(rec)
        if (j + 1) % 20 == 0:
            print(f"  {j + 1}/{len(st)} 관측소 완료", flush=True)
    r = pd.DataFrame(rows)
    r.to_csv(out / "loso_predictions.csv", index=False, encoding="utf-8-sig")

    names = [f"{a}|{c}" for a, _, c in METHODS]
    pd.set_option("display.width", 200)

    def summary(g):
        o = {}
        for n in names:
            e = g[n] - g["actual"]
            o[(n, "RMSE")] = np.sqrt((e ** 2).mean())
            o[(n, "1℃이내")] = (e.abs() <= 1).mean()
        return pd.Series(o)

    print(f"\n=== 전체 (관측소 {r['code'].nunique()}곳 × 2023~2025 여름, {len(r)}건) ===")
    s = summary(r).unstack()
    print(s.round(3).to_string())

    r["거리구간"] = pd.cut(r["nn_km"], [0, 3, 6, 10, 20, 100], labels=["~3km", "3~6km", "6~10km", "10~20km", "20km~"])
    print("\n=== 가장 가까운 다른 관측소까지 거리별 RMSE ===")
    by = r.groupby("거리구간", observed=True).apply(lambda g: pd.Series({n: np.sqrt(((g[n] - g["actual"]) ** 2).mean()) for n in names} | {"관측소수": g["code"].nunique()}))
    print(by.round(3).to_string())

    print("\n=== 28℃ 이상인 날 맞히기 (실제 28℃ 이상 vs 추정 28℃ 이상) ===")
    hot = r["actual"] >= 28
    for n in names:
        p = r[n] >= 28
        rec_ = (p & hot).sum() / max(hot.sum(), 1)
        pre = (p & hot).sum() / max(p.sum(), 1)
        print(f"  {n:12s} 포착 {rec_:.2f} 정확도 {pre:.2f}")

    for dk in D:
        z = (r[f"크리깅|{dk}"] - r["actual"]) / r[f"sd|{dk}"]
        print(f"크리깅({dk}) 불확실성 검증: 실제값이 ±1.96σ 안에 든 비율 {np.mean(np.abs(z) <= 1.96):.0%} (95%에 가까울수록 정직한 범위)")

    per = r.groupby(["code", "name"]).apply(lambda g: pd.Series({n: np.sqrt(((g[n] - g["actual"]) ** 2).mean()) for n in names})).reset_index()
    per.to_csv(out / "per_station_rmse.csv", index=False, encoding="utf-8-sig")
    best = per[names].idxmin(axis=1).value_counts()
    print("\n관측소별로 가장 잘 맞은 방법:", best.to_dict())
    pd.DataFrame({k: {x: v[x] for x in ("nugget", "sill", "range")} for k, v in vg.items()}).to_csv(out / "variogram.csv", encoding="utf-8-sig")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
