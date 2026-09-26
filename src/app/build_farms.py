"""앱 '양식장 찾기'용 어장 목록: 국립해양조사원 어장정보(SHP)에서 남해안 양식어업만 뽑아 app/data/farms.js 로 저장.

출처: 해양수산부 국립해양조사원_어장정보_20250813 (공공데이터포털 15130109, 공공누리 제1유형 - 출처표시)
  - 전국 어장 14,858곳, 면허번호·주소(예: '영덕군 병곡면 영리 지선')·어업종류·방법·품종·면적·면허기간·대표 좌표
  - 원본 zip: data/external/fishery_farms/khoa_fishery_farms.zip (용량이 커서 git 제외, 아래 URL에서 다시 받음)
    https://www.data.go.kr/data/15130109/fileData.do

앱 자료 한 줄: [시군, 주소, 면허번호, 어업종류, 방법, 품종, 위도, 경도, 면적(ha), 면허 끝(YYYYMMDD)]
사용: python src/app/build_farms.py
"""
from pathlib import Path
import io
import json
import re
import sys
import zipfile

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR, DATA_EXTERNAL_DIR  # noqa: E402

SRC = DATA_EXTERNAL_DIR / "fishery_farms" / "khoa_fishery_farms.zip"
OUT = ROOT_DIR / "app" / "data" / "farms.js"
BOX = (125.9, 129.4, 33.9, 35.5)  # 관측소가 있는 남해안 범위


def main():
    import shapefile
    z = zipfile.ZipFile(SRC)
    shp = [i for i in z.namelist() if i.lower().endswith(".shp")][0][:-4]
    r = shapefile.Reader(dbf=io.BytesIO(z.read(shp + ".dbf")), encoding="cp949")
    df = pd.DataFrame([rec.as_dict() for rec in r.iterRecords()])
    df = df[df["fids_se"].str.startswith("양식어업") & df["ycdnt"].between(BOX[2], BOX[3]) & df["xcdnt"].between(BOX[0], BOX[1])]

    def clean(s):
        return re.sub(r"\s+", " ", str(s or "")).strip()

    rows = []
    for x in df.itertuples():
        sgg = clean(x.rgn_nm).split(" ")[-1]  # '전라남도 완도군' → '완도군'
        rows.append([sgg, clean(x.addr), clean(x.lcns_no), clean(x.fids_knd), clean(x.fids_mthd), clean(x.farm_knd),
                     round(float(x.ycdnt), 5), round(float(x.xcdnt), 5), float(x.area or 0), clean(x.lcns_end_y)])
    rows.sort(key=lambda a: (a[0], a[1]))
    meta = {"source": "해양수산부 국립해양조사원 어장정보(2025-08-13), 공공누리 제1유형",
            "fields": ["시군", "주소", "면허번호", "어업종류", "방법", "품종", "위도", "경도", "면적", "면허끝"]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("// build_farms.py 가 생성. " + meta["source"] + "\nwindow.FARMS = "
                   + json.dumps({"meta": meta, "rows": rows}, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    print(f"양식 어장 {len(rows)}곳 → {OUT} ({OUT.stat().st_size / 1e3:.0f}KB)")


if __name__ == "__main__":
    main()
