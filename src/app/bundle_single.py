"""앱(app/index.html + style.css + app.js + data/*.js)을 파일 하나로 묶는다.

용도: 파일 하나로 전달하거나, 외부 파일을 따로 못 불러오는 곳에 게시할 때.
묶은 페이지는 위치 권한(내 위치)과 외부 지도 타일을 쓰지 않는다(APP_OPTIONS) - 지도 바탕은 해안선 자료로 그림.
지도 라이브러리(Leaflet) 스크립트만 cdnjs에서 불러오고, 스타일은 안에 넣는다.

사용: python src/app/bundle_single.py [출력경로]     (기본: app/dist/남해안_고수온_예보.html)
     --fragment : <html>/<head>/<body> 없이 본문 조각만 출력 (게시 도구가 뼈대를 씌우는 경우)
"""
from pathlib import Path
import re
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT_DIR  # noqa: E402

APP = ROOT_DIR / "app"
LEAFLET_JS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"
LEAFLET_CSS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"
TITLE = "남해안 고수온 예보"


def build(out: Path, fragment: bool = False) -> Path:
    html = (APP / "index.html").read_text(encoding="utf-8")
    body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
    body = re.sub(r"<script[^>]*></script>\s*", "", body)  # 외부 스크립트 태그는 아래에서 다시 넣음
    with urllib.request.urlopen(LEAFLET_CSS, timeout=60) as r:
        leaflet_css = r.read().decode("utf-8")
    css = (APP / "style.css").read_text(encoding="utf-8")
    scripts = "".join(f"<script>\n{(APP / p).read_text(encoding='utf-8')}\n</script>\n"
                      for p in ["data/coast.js", "data/farms.js", "data/forecast.js", "app.js"])
    content = (f"<title>{TITLE}</title>\n<style>\n{leaflet_css}\n</style>\n<style>\n{css}\n</style>\n{body}\n"
               f'<script src="{LEAFLET_JS}"></script>\n'
               "<script>window.APP_OPTIONS = { noGps: true, noTiles: true };</script>\n" + scripts)
    if not fragment:
        content = ('<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
                   '<meta name="viewport" content="width=device-width, initial-scale=1">\n</head>\n<body>\n'
                   + content + "</body>\n</html>\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    print(f"저장: {out} ({out.stat().st_size / 1e6:.2f}MB)")
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    build(Path(args[0]) if args else APP / "dist" / "남해안_고수온_예보.html", fragment="--fragment" in sys.argv)
