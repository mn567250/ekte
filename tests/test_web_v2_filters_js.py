"""The shared filter component (ekte/web/static/v2/filters.js), evaluated
under node: the URL query string as the view state (parsing and writing every
key of the #121 schema, defaults left out, widget namespaces), the
localStorage fallback, and widget fetching (superseded requests aborted, ETag
/ 304 reuse) against a stubbed fetch (#125)."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests._helpers import run_subprocess

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")

STATIC = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static" / "v2"

# no DOM: the pure helpers and the fetch layer only; the body is an async
# function of F (window.EkteFilters) whose result is printed as JSON
_JS = r"""
const path = require("path");
global.window = {};
require(path.join(process.argv[1], "filters.js"));
const F = window.EkteFilters;
const body = new Function("F", "return (async () => {" + process.argv[2] + "})();");
body(F).then((out) => console.log(JSON.stringify(out === undefined ? null : out)),
  (err) => { console.error(err && err.stack || err); process.exit(1); });
"""

ALL = ["q", "range", "surface", "relay", "model", "suite", "mode", "api", "stream", "detect", "risk",
       "min_score", "exec", "group"]


def run(body: str, tz: str | None = None) -> Any:
    env = None if tz is None else {**os.environ, "TZ": tz}
    out = run_subprocess(
        ["node", "-e", _JS, str(STATIC), body],
        capture_output=True, text=True, encoding="utf-8", check=True, env=env,
    ).stdout
    return json.loads(out)


def js(value: Any) -> str:
    return json.dumps(value)


def parse(search: str, fields: list[str] | None = None) -> dict[str, Any]:
    return run(f"return F.parse({js(search)}, {js(fields or ALL)});")


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("search", "want"), [
    ("q=gpt%204o", {"q": "gpt 4o"}),
    ("range=7d", {"range": "7d"}),
    ("range=24h", {"range": "24h"}),
    ("range=12d", {}),  # not a preset
    # from / to without range: a custom range, not the 30d default over them
    ("from=2026-01-01&to=2026-02-01T12:30:00Z", {"from": "2026-01-01", "to": "2026-02-01T12:30:00Z", "range": ""}),
    ("from=yesterday", {}),
    ("range=30d&from=2026-01-01", {"range": "30d"}),  # range wins over from / to
    ("surface=embedding", {"surface": "embedding"}),
    ("surface=video", {}),
    ("surface=-", {}),  # surface has no "(unknown)"
    ("relay=a&relay=b&relay=a", {"relay": ["a", "b"]}),
    ("relay=-", {"relay": ["-"]}),
    ("relay=", {"relay": []}),
    ("model=gpt-4o&model=claude", {"model": ["gpt-4o", "claude"]}),
    ("suite=standard", {"suite": "standard"}),
    ("suite=-", {"suite": "-"}),
    ("mode=check", {"mode": "check"}),
    ("api=openai", {"api": "openai"}),
    ("api=-", {"api": "-"}),
    ("stream=non_stream", {"stream": "non_stream"}),
    ("stream=-", {"stream": "-"}),
    ("stream=sometimes", {}),
    ("detect=auto", {"detect": "auto"}),
    ("detect=-", {"detect": "-"}),
    ("risk=high", {"risk": "high"}),
    ("risk=inconclusive", {"risk": "inconclusive"}),
    ("risk=-", {}),
    ("risk=huge", {}),
    ("min_score=70", {"min_score": "70"}),
    ("min_score=101", {}),
    ("min_score=abc", {}),
    ("exec=monitor", {"exec": "monitor"}),
    ("exec=adhoc", {}),  # the old value
    ("group=model", {"group": "model"}),
    ("group=relay_model", {"group": "relay_model"}),
    ("group=", {}),  # the default, never "none"
    ("suite=a&suite=b", {"suite": "a"}),  # a non-repeatable key: the first
    ("suite=", {"suite": ""}),  # explicitly "All" (over a non-empty default)
])
def test_parse_every_key(search, want):
    assert parse(search) == want


def test_parse_keeps_widget_and_view_keys_and_drops_the_rest():
    got = parse("trend.metric=latency_p50&runs.after=abc&trend.keys=a&trend.keys=b&tab=trends"
                "&days=30&min=50&stream_mode=stream&source=manual&exec=manual")
    assert got == {"trend.metric": "latency_p50", "runs.after": "abc", "trend.keys": ["a", "b"],
                   "tab": "trends", "exec": "manual"}


def test_parse_drops_keys_the_page_does_not_show():
    # a filter never applies without its field on screen
    assert parse("risk=high&relay=a&q=x", ["relay"]) == {"relay": ["a"]}
    # from / to come with range
    assert parse("from=2026-01-01", ["relay"]) == {}
    assert parse("from=2026-01-01", ["range"]) == {"from": "2026-01-01", "range": ""}


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #
FULL = {
    "q": "relay x", "range": "", "from": "2026-01-01", "to": "2026-02-01", "surface": "rerank",
    "relay": ["a", "-"], "model": ["m1"], "suite": "-", "mode": "check", "api": "anthropic", "stream": "both",
    "detect": "manual", "risk": "clean", "min_score": "55", "exec": "manual", "group": "all",
}


def test_every_key_round_trips():
    qs = run(f"return F.serialise({js(FULL)}, {{}}, {js(ALL)});")
    # range "" (all time, custom from / to) differs from the schema's 30d: "range="
    assert qs == ("q=relay+x&range=&from=2026-01-01&to=2026-02-01&surface=rerank&relay=a&relay=-&model=m1&suite=-"
                  "&mode=check&api=anthropic&stream=both&detect=manual&risk=clean&min_score=55&exec=manual&group=all")
    back = parse(qs)
    assert back == FULL


def test_defaults_are_left_out():
    state = {"q": "", "range": "30d", "relay": [], "suite": "", "group": "relay", "trend.metric": "score", "tab": "overview"}
    defaults = {"range": "30d", "trend.metric": "score", "tab": "overview"}
    assert run(f"return F.serialise({js(state)}, {js(defaults)}, {js(ALL)});") == ""
    # a filter set back to empty over a non-empty default stays in the link
    state |= {"range": "", "trend.metric": "error_rate", "tab": "trends", "relay": ["r"]}
    qs = run(f"return F.serialise({js(state)}, {js(defaults)}, {js(ALL)});")
    assert qs == "range=&relay=r&tab=trends&trend.metric=error_rate"
    assert parse(qs) == {"range": "", "relay": ["r"], "tab": "trends", "trend.metric": "error_rate"}
    # an empty list over a non-empty default
    assert run(f"return F.serialise({{relay: []}}, {{relay: ['a']}}, {js(ALL)});") == "relay="


def test_widget_params_are_the_shared_filters_and_one_namespace():
    state = {"range": "7d", "from": "", "to": "", "relay": ["a", "b"], "suite": "", "group": "model",
             "trend.metric": "latency_p50", "trend.bucket": "day", "kpi.compare": "1", "runs.after": "",
             "trends.x": "1", "tab": "trends"}
    fields = ["range", "relay", "suite", "group"]
    p = lambda ns: run(f"return F.params({js(state)}, {js(fields)}, {js(ns)});")  # noqa: E731
    assert p(None) == "range=7d&relay=a&relay=b&group=model"
    # its own keys only: not another widget's, not "trends.*" for "trend", not the tab, not empty ones
    assert p("trend") == "range=7d&relay=a&relay=b&group=model&trend.bucket=day&trend.metric=latency_p50"
    assert p("runs") == "range=7d&relay=a&relay=b&group=model"
    assert p(["kpi", "trend"]) == ("range=7d&relay=a&relay=b&group=model&kpi.compare=1"
                                   "&trend.bucket=day&trend.metric=latency_p50")


# --------------------------------------------------------------------------- #
# the localStorage fallback
# --------------------------------------------------------------------------- #
_STORE = """
const mem = (init) => { const m = Object.assign({}, init); return {
  getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); } }; };
const throwing = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
const o = (storage) => ({ fields: ["range", "relay", "risk"], defaults: { range: "30d", "trend.metric": "score" },
  page: "history", storage });
"""


def test_storage_applies_only_without_filter_keys_in_the_url():
    got = run(_STORE + """
      const saved = mem({ "ekte.v2.filters.history": "relay=a&risk=high" });
      return [
        F.initial("", o(saved)),
        F.initial("?tab=runs&trend.metric=ttft_p50", o(saved)),   // widget / view keys only: storage
        F.initial("?risk=low", o(saved)),                         // a filter key: the URL alone
        F.initial("?range=", o(saved)),
        F.initial("", o(mem({}))),
        F.initial("", o(mem({ "ekte.v2.filters.history": "days=7&bogus=1" }))),  // nothing usable
        F.initial("", o(mem({ "ekte.v2.filters.analytics": "risk=high" }))),     // another page's
      ];
    """)
    base = {"range": "30d", "from": "", "to": "", "relay": [], "risk": "", "trend.metric": "score"}
    assert got[0] == {"state": base | {"relay": ["a"], "risk": "high"}, "source": "storage"}
    assert got[1] == {"state": base | {"relay": ["a"], "risk": "high", "trend.metric": "ttft_p50", "tab": "runs"},
                      "source": "storage"}
    assert got[2] == {"state": base | {"risk": "low"}, "source": "url"}
    assert got[3] == {"state": base | {"range": ""}, "source": "url"}
    assert got[4] == {"state": base, "source": "defaults"}
    assert got[5] == {"state": base, "source": "defaults"}
    assert got[6] == {"state": base, "source": "defaults"}


def test_storage_that_throws_or_is_missing_falls_back_to_the_defaults():
    got = run(_STORE + """
      return [F.initial("", o(throwing)), F.initial("", o(null)), F.initial("?relay=x", o(throwing))];
    """)
    base = {"range": "30d", "from": "", "to": "", "relay": [], "risk": "", "trend.metric": "score"}
    assert got[0] == got[1] == {"state": base, "source": "defaults"}
    assert got[2] == {"state": base | {"relay": ["x"]}, "source": "url"}


# --------------------------------------------------------------------------- #
# remembered filters: shared across pages (default) or per page (#154)
# --------------------------------------------------------------------------- #
_PAGES = _STORE + """
const HIST = ["q", "surface", "relay", "model", "suite", "mode", "api", "detect", "stream", "risk", "min_score",
              "range", "exec"];
const ANA = ["range", "surface", "relay", "model", "suite", "api", "stream", "exec", "group"];
const page = (name, fields, defaults) => ({ page: name, fields, defaults: defaults || {} });
const hist = page("history", HIST), ana = page("analytics", ANA, { range: "30d" });
const mon = page("monitors", ["q", "surface", "relay", "model", "suite", "api", "stream"]);
// a page's filter change, as create().set() records it
const use = (p, search, store) => F.remember(p.page, F.initial(search, Object.assign({ storage: store }, p)).state,
                                              p.fields, p.defaults, store);
const open = (p, search, store) => F.initial(search, Object.assign({ storage: store }, p));
"""


def test_shared_mode_is_the_default_and_carries_relay_between_pages():
    got = run(_PAGES + """
      const s = mem({});
      const before = F.scope(s);
      use(hist, "?relay=a&risk=high&range=7d", s);
      return [before, open(ana, "", s), JSON.parse(s.getItem("ekte.v2.filters.shared"))];
    """)
    assert got[0] == "shared"
    assert got[1]["source"] == "storage"
    st = got[1]["state"]
    assert st["relay"] == ["a"] and st["range"] == "7d" and st["group"] == "relay"
    assert "risk" not in st  # Analytics does not show risk
    # every shared key History shows, as shown; never the search text
    assert got[2]["relay"] == ["a"] and got[2]["risk"] == "high" and got[2]["range"] == "7d"
    assert got[2]["surface"] == "" and got[2]["model"] == [] and "q" not in got[2]


def test_per_page_mode_keeps_pages_apart():
    got = run(_PAGES + """
      const s = mem({});
      F.setScope("page", s);
      use(ana, "?relay=b", s);
      use(hist, "?relay=a", s);
      return [F.scope(s), open(ana, "", s), open(hist, "", s), s.getItem("ekte.v2.filters.shared")];
    """)
    assert got[0] == "page"
    assert got[1]["state"]["relay"] == ["b"] and got[1]["source"] == "storage"
    assert got[2]["state"]["relay"] == ["a"]
    assert got[3] is None  # per page writes no shared memory


def test_a_page_with_a_subset_of_fields_leaves_the_other_shared_keys_untouched():
    got = run(_PAGES + """
      const s = mem({});
      use(hist, "?relay=a&range=90d&risk=low", s);
      use(mon, "?relay=c&stream=both", s);     // no range, no risk on this page
      return [JSON.parse(s.getItem("ekte.v2.filters.shared")), open(hist, "", s).state];
    """)
    assert got[0]["relay"] == ["c"] and got[0]["stream"] == "both"
    assert got[0]["range"] == "90d" and got[0]["risk"] == "low"
    assert got[1]["range"] == "90d" and got[1]["risk"] == "low" and got[1]["relay"] == ["c"]


def test_values_cross_as_shown_whatever_each_pages_default():
    got = run(_PAGES + """
      const s = mem({});
      use(hist, "?range=", s);                                   // all time: History's default
      const allTime = open(ana, "", s).state;
      use(hist, "?from=2026-01-01&to=2026-02-01", s);            // a custom range
      const custom = open(ana, "", s).state;
      use(ana, "?range=30d&surface=chat", s);                    // Analytics' default range
      return [allTime, custom, open(hist, "", s).state];
    """)
    assert got[0]["range"] == ""
    assert (got[1]["range"], got[1]["from"], got[1]["to"]) == ("", "2026-01-01", "2026-02-01")
    assert got[2]["range"] == "30d" and got[2]["surface"] == "chat"


def test_search_text_never_crosses_pages():
    got = run(_PAGES + """
      const s = mem({});
      use(hist, "?q=gpt&relay=a", s);
      const shared = JSON.parse(s.getItem("ekte.v2.filters.shared"));
      const m = open(mon, "", s).state;
      use(mon, "?q=claude&relay=a", s);
      return [shared, m, open(hist, "", s).state.q, open(mon, "", s).state.q];
    """)
    assert "q" not in got[0]
    assert got[1]["q"] == "" and got[1]["relay"] == ["a"]
    assert got[2] == "gpt" and got[3] == "claude"


def test_the_url_wins_in_both_modes():
    got = run(_PAGES + """
      const out = [];
      for (const mode of ["shared", "page"]) {
        const s = mem({});
        F.setScope(mode, s);
        use(hist, "?relay=a", s);
        use(ana, "?relay=a", s);
        out.push(open(ana, "?stream=both", s));
      }
      return out;
    """)
    for one in got:
        assert one["source"] == "url"
        assert one["state"]["relay"] == [] and one["state"]["stream"] == "both"


def test_turning_sharing_on_writes_the_view_and_off_copies_nothing():
    got = run(_PAGES + """
      const s = mem({});
      use(hist, "?relay=a", s);
      F.setScope("page", s);
      const shared = s.getItem("ekte.v2.filters.shared");
      use(hist, "?relay=b", s);                                  // per page: shared memory untouched
      const off = s.getItem("ekte.v2.filters.shared");
      const st = open(ana, "?relay=z&range=7d", s).state;
      F.setScope("shared", s, { state: st, fields: ana.fields });
      return [shared === off, JSON.parse(off).relay, JSON.parse(s.getItem("ekte.v2.filters.shared")),
              open(hist, "", s).state];
    """)
    assert got[0] is True and got[1] == ["a"]  # turning it off copied nothing
    assert got[2]["relay"] == ["z"] and got[2]["range"] == "7d" and got[2]["group"] == "relay"
    assert got[2]["mode"] == ""  # a key Analytics does not show: History's, unchanged
    assert got[3]["relay"] == ["z"] and got[3]["range"] == "7d"


def test_shared_mode_without_a_shared_memory_reads_the_pages_own():
    got = run(_PAGES + """
      const s = mem({ "ekte.v2.filters.analytics": "relay=old" });
      return open(ana, "", s);
    """)
    assert got["source"] == "storage" and got["state"]["relay"] == ["old"]


def test_invalid_or_foreign_shared_memory_is_dropped():
    got = run(_PAGES + """
      return [
        open(ana, "", mem({ "ekte.v2.filters.shared": "{not json" })),
        open(ana, "", mem({ "ekte.v2.filters.shared": '{"range":"12d","surface":"video","group":"model","q":"x"}' })),
        open(ana, "", mem({ "ekte.v2.filters.shared": "[1,2]", "ekte.v2.filters.scope": "bogus" })),
      ];
    """)
    assert got[0]["source"] == got[2]["source"] == "defaults"
    # the valid key applies, the invalid ones and the page-specific q do not
    assert got[1]["source"] == "storage"
    for g in got:
        assert g["state"]["range"] == "30d" and g["state"]["surface"] == ""
    assert got[1]["state"]["group"] == "model" and "q" not in got[1]["state"]


def test_throwing_storage_is_harmless_for_every_helper():
    got = run(_PAGES + """
      const partly = { getItem: (k) => { if (k === "ekte.v2.filters.shared") throw new Error("x"); return null; },
                       setItem() { throw new Error("full"); } };
      F.remember("history", { relay: ["a"] }, ["relay"], {}, throwing);
      F.remember("history", { relay: ["a"] }, ["relay"], {}, partly);
      return [F.scope(throwing), F.setScope("page", throwing, { state: {}, fields: [] }),
              F.setScope("shared", throwing, { state: { relay: ["a"] }, fields: ["relay"] }),
              open(ana, "", throwing).source, open(ana, "", partly).source, open(hist, "?relay=x", throwing).state.relay];
    """)
    assert got == ["shared", "page", "shared", "defaults", "defaults", ["x"]]


# --------------------------------------------------------------------------- #
# fetching
# --------------------------------------------------------------------------- #
# a fetch stub: each call is recorded; `respond(url, init)` decides, and a
# pending request rejects with an AbortError when its signal fires
_FETCH = """
const calls = [];
let respond = null;
const res = (status, body, etag) => ({ status, ok: status >= 200 && status < 300,
  headers: { get: (h) => (h === "ETag" ? etag || null : null) }, json: async () => body });
global.fetch = (url, init) => {
  calls.push({ url, inm: (init.headers || {})["If-None-Match"] || null });
  return new Promise((resolve, reject) => {
    const abort = () => { const e = new Error("aborted"); e.name = "AbortError"; reject(e); };
    if (init.signal) { if (init.signal.aborted) return abort(); init.signal.addEventListener("abort", abort); }
    const r = respond(url, init);
    if (r) Promise.resolve(r).then(resolve);
  });
};
const tick = () => new Promise((r) => setTimeout(r, 5));
"""


def test_etag_is_sent_and_a_304_reuses_the_copy():
    got = run(_FETCH + """
      let n = 0;
      respond = (url, init) => {
        n += 1;
        if (init.headers["If-None-Match"] === '"v1"') return res(304, null, '"v1"');
        return res(200, { url, n }, url.includes("nocache") ? null : '"v1"');
      };
      const a = await F.fetchWidget("/api/x?range=7d");
      const b = await F.fetchWidget("/api/x?range=7d");      // 304: the same data
      const c = await F.fetchWidget("/api/x?range=30d");     // another URL: no ETag of its own yet
      const d = await F.fetchWidget("/api/nocache");
      const e = await F.fetchWidget("/api/nocache");         // no ETag given: never conditional
      return { a, b, c, d, e, calls };
    """)
    assert got["a"] == got["b"] == {"url": "/api/x?range=7d", "n": 1}
    assert got["c"] == {"url": "/api/x?range=30d", "n": 3}
    assert [c["inm"] for c in got["calls"]] == [None, '"v1"', None, None, None]
    assert got["e"]["n"] == 5


def test_an_error_status_rejects_with_the_server_message():
    got = run(_FETCH + """
      respond = () => res(400, { error: "unknown parameter: days" });
      try { await F.fetchWidget("/api/x?days=7"); return "resolved"; }
      catch (e) { return { message: e.message, status: e.status }; }
    """)
    assert got == {"message": "unknown parameter: days", "status": 400}


def test_a_newer_load_aborts_the_one_in_flight_and_errors_stay_per_widget():
    got = run(_FETCH + """
      const log = [];
      const widget = (ns) => ({ url: "/api/" + ns, done: (d) => log.push(["done", ns, d.v]),
        fail: (e) => log.push(["fail", ns, e.status, e.message]) });
      // the first state: never answered (superseded); the second answers
      respond = (url) => url.includes("range=7d") ? null
        : url.startsWith("/api/bad") ? res(500, { error: "boom" }) : res(200, { v: url });
      const load = F.loader();
      let qs = "range=7d";
      const first = load.run({ kpi: widget("kpi"), trend: widget("trend") }, (ns) => qs + "&" + ns + ".x=1");
      await tick();
      const firstAborted = load.signal().aborted;
      qs = "range=30d";
      const second = load.run({ kpi: widget("kpi"), bad: widget("bad") }, (ns) => qs);
      await Promise.all([first, second]);
      // abort() (a change of filters) stops the current run too
      respond = () => null;
      const third = load.run({ kpi: widget("kpi") }, () => "range=90d");
      await tick();
      load.abort();
      await third;
      return { log, firstAborted, urls: calls.map((c) => c.url) };
    """)
    assert got["firstAborted"] is False
    assert got["urls"] == ["/api/kpi?range=7d&kpi.x=1", "/api/trend?range=7d&trend.x=1",
                           "/api/kpi?range=30d", "/api/bad?range=30d", "/api/kpi?range=90d"]
    # the superseded and the aborted run deliver nothing, not even an error;
    # one widget's failure leaves the other's result
    assert sorted(got["log"]) == [["done", "kpi", "/api/kpi?range=30d"], ["fail", "bad", 500, "boom"]]


def test_keyed_labels_fall_back_to_the_servers_english_text():
    got = run("""
      const labels = { "metric.score": "Score" };
      const out = [F.keyed("metric.score", labels), F.keyed("metric.x", labels), F.keyed("metric.score")];
      // a language whose bundle translates the key
      window.EKTE_LANG = { tr: (k) => (k === "metric.score" ? "Punktzahl" : k) };
      out.push(F.keyed("metric.score", labels), F.keyed("metric.grade", { "metric.grade": "Grade" }));
      return out;
    """)
    assert got == ["Score", "metric.x", "metric.score", "Punktzahl", "Grade"]


def test_no_metric_logic_in_the_module():
    # values are passed through: nothing is computed, graded or classified
    import re

    src = (STATIC / "filters.js").read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/|^\s*//.*$", "", src, flags=re.S | re.M)  # the code, not its comments
    for word in ("median", "percentile", "grade", "score >", "Math.round", "success_rate", "error_rate"):
        assert word not in src, word


# --------------------------------------------------------------------------- #
# the viewer's time zone and the shared default range (#152)
# --------------------------------------------------------------------------- #
def test_the_default_range_is_30d_once_in_the_schema():
    assert run("return F.FIELDS.range.def;") == "30d"
    # every page starts on it without a page default, and "range=" is all time
    o = '{ fields: ["range", "relay"], defaults: {}, page: "history", storage: null }'
    got = run(f"return [F.initial('', {o}), F.initial('?range=', {o})];")
    assert got[0]["state"]["range"] == "30d" and got[1]["state"]["range"] == ""
    assert run(f"return F.serialise({{range: '30d', relay: []}}, {{}}, {js(['range', 'relay'])});") == ""
    assert run(f"return F.serialise({{range: '', relay: []}}, {{}}, {js(['range', 'relay'])});") == "range="
    # all time sends no range to the widgets
    assert run(f"return F.params({{range: '', from: '', to: ''}}, {js(['range'])}, null);") == ""


def test_widget_params_carry_the_viewers_zone_and_links_do_not():
    state = {"range": "30d", "from": "", "to": "", "relay": ["a"], "trend.metric": "score"}
    fields = ["range", "relay"]
    got = run(f"""
      const zone = F.viewerZone();
      return {{ zone, widget: F.params({js(state)}, {js(fields)}, "trend", zone),
                plain: F.params({js(state)}, {js(fields)}, "trend"),
                link: F.serialise({js(state)}, {{}}, {js(fields)}),
                parsed: F.parse("?range=7d&tz=Asia/Tokyo&trend.tz=x", {js(fields)}) }};
    """, tz="Europe/Berlin")
    assert got["zone"] == "Europe/Berlin"
    assert got["widget"] == "range=30d&relay=a&trend.metric=score&tz=Europe%2FBerlin"
    assert "tz=" not in got["plain"] and "tz" not in got["link"]
    # a tz in a page URL is not a filter of the page: dropped, never written back
    assert "tz" not in got["parsed"] and got["parsed"]["range"] == "7d"
    assert run("return F.viewerZone();", tz="America/Los_Angeles") == "America/Los_Angeles"
    # the page instance's widgetParams() is params() with the viewer's zone
    src = (STATIC / "filters.js").read_text(encoding="utf-8")
    assert "function widgetParams(ns) { return params(st, fields, ns, viewerZone()); }" in src


def test_a_change_on_history_keeps_the_common_default_range():
    """Both pages default to 30d (#152): sharing History's default range as
    shown leaves Analytics on 30d, not on all time."""
    got = run(_PAGES + """
      const s = mem({});
      use(hist, "?relay=a", s);
      return [JSON.parse(s.getItem("ekte.v2.filters.shared")).range, open(ana, "", s).state.range];
    """)
    assert got == ["30d", "30d"]
