"""앱 지도 바탕용 해안선: Natural Earth 1:10m land + minor islands 중 남해안 범위만 단순화해 app/data/coast.js 로 저장.

지도 타일(OpenStreetMap)을 못 불러오는 환경(오프라인, 게시 페이지)에서도 육지·섬 모양이 보이도록 하기 위함.
사용: python src/app/build_coastline.py
"""
from pathlib import Path
import io
import json
import sys
import zipfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR  # noqa: E402
from models.spatial_interp import COAST_DIR  # noqa: E402

BOX = (125.8, 129.5, 33.8, 35.6)
TOLERANCE = 0.002   # 약 200m 이하 굴곡은 생략
OUT = ROOT_DIR / "app" / "data" / "coast.js"


def simplify(pts: np.ndarray, tol: float) -> np.ndarray:
    """Douglas-Peucker."""
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    ab = b - a
    n = np.hypot(*ab)
    q = pts - a
    d = np.abs(ab[0] * q[:, 1] - ab[1] * q[:, 0]) / n if n > 0 else np.hypot(q[:, 0], q[:, 1])
    i = int(np.argmax(d))
    if d[i] > tol:
        return np.vstack([simplify(pts[:i + 1], tol)[:-1], simplify(pts[i:], tol)])
    return np.vstack([a, b])


def main():
    import shapefile
    rings = []
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
                keep = ((ring[:, 0] > BOX[0] - 0.5) & (ring[:, 0] < BOX[1] + 0.5)
                        & (ring[:, 1] > BOX[2] - 0.5) & (ring[:, 1] < BOX[3] + 0.5))
                if keep.sum() < 3:
                    continue
                # 대륙처럼 범위를 벗어나는 큰 폴리곤은 범위 안(여유 0.5°) 점만 남긴다 - 화면 밖 모양은 필요 없음
                s = simplify(ring[keep], TOLERANCE)
                if len(s) >= 4:
                    rings.append([[round(float(y), 3), round(float(x), 3)] for x, y in s])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("// build_coastline.py 가 생성 (Natural Earth 1:10m, 공개 자료)\nwindow.COAST = "
                   + json.dumps(rings, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"해안선 {len(rings)}개, 점 {sum(len(r) for r in rings)}개, {OUT.stat().st_size / 1e3:.0f}KB → {OUT}")


if __name__ == "__main__":
    main()
