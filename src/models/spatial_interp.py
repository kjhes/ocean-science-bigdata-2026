"""양식장 위치(임의 좌표)의 수온을 주변 수과원 관측소들로 추정하는 공간 보간.

방법
  - 최근접: 가장 가까운 관측소 값
  - IDW(거리 가중 평균): 가까운 k곳을 거리^-p 가중으로 평균
  - 크리깅(정규 크리깅): 관측소 간 수온 차이가 거리에 따라 커지는 정도(변동도, variogram)를 자료로 맞춘 뒤,
    그 구조로 가중치를 정함. 추정 불확실성(크리깅 분산)도 함께 나옴
  - 거리: 직선거리 / 바닷길 거리(육지를 돌아가는 최단 해상 경로, 약 500m 격자)

바닷길 거리용 육지 격자: Natural Earth 1:10m land + minor islands (data/external/coastline)
관측소 좌표: 수과원 실시간 조회 결과의 lat/lot (data/processed/nifs_stations_southsea.csv)
"""
from pathlib import Path
import io
import sys
import zipfile

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATA_EXTERNAL_DIR, DATA_PROCESSED_DIR  # noqa: E402

COAST_DIR = DATA_EXTERNAL_DIR / "coastline"
MASK_PATH = COAST_DIR / "southsea_landmask.npz"
STATIONS_PATH = DATA_PROCESSED_DIR / "nifs_stations_southsea.csv"
BOX = (125.9, 129.4, 33.7, 35.4)   # 경도 min,max, 위도 min,max (제주 제외 남해안)
RES = 0.005                         # 약 0.46km(경도) x 0.56km(위도)
KM_PER_DEG_LAT = 111.0
KM_PER_DEG_LON = 111.0 * np.cos(np.radians(34.5))


def build_landmask():
    """Natural Earth 폴리곤을 격자로 바꿔 육지(True)/바다(False) 배열 저장."""
    import shapefile
    from matplotlib.path import Path as MPath
    lons = np.arange(BOX[0], BOX[1], RES) + RES / 2
    lats = np.arange(BOX[2], BOX[3], RES) + RES / 2
    LO, LA = np.meshgrid(lons, lats)
    pts = np.c_[LO.ravel(), LA.ravel()]
    land = np.zeros(len(pts), bool)
    for f in ["ne_10m_land.zip", "ne_10m_minor_islands.zip"]:
        z = zipfile.ZipFile(COAST_DIR / f)
        n = [x for x in z.namelist() if x.endswith(".shp")][0][:-4]
        r = shapefile.Reader(shp=io.BytesIO(z.read(n + ".shp")), shx=io.BytesIO(z.read(n + ".shx")),
                             dbf=io.BytesIO(z.read(n + ".dbf")))
        for sh in r.shapes():
            b = sh.bbox
            if b[2] < BOX[0] or b[0] > BOX[1] or b[3] < BOX[2] or b[1] > BOX[3]:
                continue
            parts = list(sh.parts) + [len(sh.points)]
            for i in range(len(parts) - 1):
                ring = np.array(sh.points[parts[i]:parts[i + 1]])
                if len(ring) < 3:
                    continue
                m = ((pts[:, 0] >= ring[:, 0].min()) & (pts[:, 0] <= ring[:, 0].max())
                     & (pts[:, 1] >= ring[:, 1].min()) & (pts[:, 1] <= ring[:, 1].max()))
                if m.any():
                    land[m] |= MPath(ring).contains_points(pts[m])
    land = land.reshape(LA.shape)
    np.savez_compressed(MASK_PATH, land=land, lons=lons, lats=lats)
    return land, lons, lats


def load_landmask():
    if not MASK_PATH.exists():
        return build_landmask()
    z = np.load(MASK_PATH)
    return z["land"], z["lons"], z["lats"]


def load_stations(daily: pd.DataFrame = None) -> pd.DataFrame:
    """좌표가 있고 남해안 격자 안에 있는 관측소 (기상청 부이 제외)."""
    st = pd.read_csv(STATIONS_PATH)
    st = st[(st["lon"] > BOX[0]) & (st["lon"] < BOX[1]) & (st["lat"] > 33.9) & (st["lat"] < BOX[3])]
    if daily is not None:
        st = st[st["code"].isin(daily["code"].unique())]
    return st.reset_index(drop=True)


def straight_km(lat1, lon1, lat2, lon2):
    return np.hypot((np.asarray(lon1) - lon2) * KM_PER_DEG_LON, (np.asarray(lat1) - lat2) * KM_PER_DEG_LAT)


class SeaGraph:
    """바다 격자 위 8방향 이동 그래프. 육지에 찍힌 점은 가장 가까운 바다 칸으로 옮긴다(해안선 해상도 한계)."""

    def __init__(self):
        land, self.lons, self.lats = load_landmask()
        self.sea = ~land
        ny, nx = self.sea.shape
        idx = -np.ones((ny, nx), int)
        sy, sx = np.nonzero(self.sea)
        idx[sy, sx] = np.arange(len(sy))
        self.idx, self.sy, self.sx = idx, sy, sx
        dx, dy = RES * KM_PER_DEG_LON, RES * KM_PER_DEG_LAT
        rows, cols, w = [], [], []
        for oy, ox in [(0, 1), (1, 0), (1, 1), (1, -1)]:
            y2, x2 = sy + oy, sx + ox
            ok = (y2 >= 0) & (y2 < ny) & (x2 >= 0) & (x2 < nx)
            a, y2, x2 = np.arange(len(sy))[ok], y2[ok], x2[ok]
            b = idx[y2, x2]
            m = b >= 0
            rows += [a[m]]
            cols += [b[m]]
            w += [np.full(m.sum(), np.hypot(ox * dx, oy * dy))]
        r, c, ww = np.concatenate(rows), np.concatenate(cols), np.concatenate(w)
        self.graph = coo_matrix((np.r_[ww, ww], (np.r_[r, c], np.r_[c, r])), shape=(len(sy), len(sy))).tocsr()

    def node(self, lat, lon):
        """좌표 → 가장 가까운 바다 칸 번호와 옮긴 거리(km)."""
        d = straight_km(self.lats[self.sy], self.lons[self.sx], lat, lon)
        k = int(np.argmin(d))
        return k, float(d[k])

    def distances(self, src_latlon, dst_latlon):
        """src 각 점에서 dst 각 점까지 바닷길 거리(km). 옮긴 거리만큼 더한다."""
        s_nodes = [self.node(*p) for p in src_latlon]
        d_nodes = [self.node(*p) for p in dst_latlon]
        D = dijkstra(self.graph, indices=[n for n, _ in s_nodes])
        out = D[:, [n for n, _ in d_nodes]]
        out += np.array([s for _, s in s_nodes])[:, None] + np.array([s for _, s in d_nodes])[None, :]
        return out


# ---------------- 보간 방법 ----------------
def exp_variogram(h, nugget, sill, rng):
    return nugget + sill * (1.0 - np.exp(-h / rng))


def fit_variogram(values: np.ndarray, dist: np.ndarray, max_km: float = 60.0, bins: int = 15):
    """values: (일수, 관측소) 수온, dist: 관측소 간 거리. 날마다 전체 평균을 뺀 값(공간 편차)으로 경험 변동도 → 지수모형."""
    anom = values - np.nanmean(values, axis=1, keepdims=True)
    iu = np.triu_indices(dist.shape[0], 1)
    h = dist[iu]
    diff2 = (anom[:, iu[0]] - anom[:, iu[1]]) ** 2
    g = 0.5 * np.nanmean(diff2, axis=0)
    ok = np.isfinite(g) & (h <= max_km)
    edges = np.linspace(0, max_km, bins + 1)
    hb, gb = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        m = ok & (h >= a) & (h < b)
        if m.sum() >= 5:
            hb.append(h[m].mean())
            gb.append(g[m].mean())
    p, _ = curve_fit(exp_variogram, np.array(hb), np.array(gb), p0=[0.1, 1.0, 20.0],
                     bounds=([0, 1e-3, 0.5], [10, 50, 500]))
    return {"nugget": float(p[0]), "sill": float(p[1]), "range": float(p[2]), "bins_h": hb, "bins_g": gb}


def predict_point(vals, d_target, D_nb, method, vg=None, k=6, power=2.0):
    """vals: 주변 관측소 값(결측 없는 것만), d_target: 목표점→관측소 거리, D_nb: 관측소 간 거리.
    반환 (추정값, 표준편차 또는 nan)."""
    order = np.argsort(d_target)
    if method == "nearest":
        return float(vals[order[0]]), np.nan
    sel = order[:k]
    v, d = vals[sel], d_target[sel]
    if method == "idw":
        w = 1.0 / np.maximum(d, 0.1) ** power
        return float((w * v).sum() / w.sum()), np.nan
    # 정규 크리깅: 변동도 γ로 [Γ 1; 1ᵀ 0][w; μ] = [γ0; 1]
    G = exp_variogram(D_nb[np.ix_(sel, sel)], vg["nugget"], vg["sill"], vg["range"])
    np.fill_diagonal(G, 0.0)
    n = len(sel)
    A = np.ones((n + 1, n + 1))
    A[:n, :n] = G
    A[n, n] = 0.0
    g0 = exp_variogram(d, vg["nugget"], vg["sill"], vg["range"])
    sol = np.linalg.solve(A, np.r_[g0, 1.0])
    w = sol[:n]
    var = float(w @ g0 + sol[n])
    return float(w @ v), float(np.sqrt(max(var, 0.0)))
