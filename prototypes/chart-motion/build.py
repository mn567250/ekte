"""Build the standalone chart-motion prototype (index.html) from these sources
and the app's own, unchanged zing.css, charts.css, charts.js, perf.css and
perf.js. Run: python prototypes/chart-motion/build.py"""
import sys, pathlib
here = pathlib.Path(__file__).resolve().parent
v2 = here.parents[1] / "zing" / "web" / "static" / "v2"
t = (here / "page.tpl.html").read_text()
measured = sys.argv[1] if len(sys.argv) > 1 else ("under 3 ms of script to start the motion on all four charts; no dropped frames at normal "
            "CPU speed, a few 24–48 ms frames at 4× CPU slowdown when all four animate at once")
for k, v in {
    "/*@@ZING_CSS@@*/": (v2 / "zing.css").read_text(),
    "/*@@CHARTS_CSS@@*/": (v2 / "charts.css").read_text(),
    "/*@@MOTION_CSS@@*/": (here / "chartmotion.css").read_text(),
    "/*@@PERF_JS@@*/": (v2.parent / "perf.js").read_text(),
    "/*@@PERFTREND_JS@@*/": (here / "perftrend.js").read_text(),
    "/*@@PERF_CSS@@*/": (v2 / "perf.css").read_text(),
    "/*@@CHARTS_JS@@*/": (v2 / "charts.js").read_text(),
    "/*@@HEATGRID_JS@@*/": (here / "heatgrid.js").read_text(),
    "/*@@MOTION_JS@@*/": (here / "chartmotion.js").read_text(),
    "@@MEASURED@@": measured,
}.items():
    assert k in t, k
    t = t.replace(k, v)
# a standalone page: a doctype and metas (the head and body are implied)
t = '<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n' + t
(here / "index.html").write_text(t)
print(len(t))
