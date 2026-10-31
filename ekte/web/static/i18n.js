/* ekte web UI — Simplified-Chinese localization of audit findings.
 *
 * Plain browser global, no modules. Exposes window.EKTE_I18N with:
 *   - FINDINGS:   catalog id -> { title, tpl }
 *   - localizeFinding(id, fallbackSummary, evidence) -> { title, summary }
 *   - RISK_LEVEL, STATUS, SEVERITY, CONFIDENCE: enum -> zh label
 *   - DIMENSIONS: dimension id -> [zhName, zhDesc]
 *   - EN:         the same enum/dimension maps in English
 *   - label(kind, key) -> label in the current UI language (see lang.js);
 *                 kind is one of RISK_LEVEL / STATUS / SEVERITY / CONFIDENCE
 *   - exportReport(report) -> a copy of an audit report for download, with
 *                 every human-readable text value in the current UI language
 *                 (CN included) and the JSON keys, enum values, ids, evidence
 *                 and raw error messages untouched
 *
 * Outside CN, localizeFinding uses the FINDINGS_L10N catalog of the current
 * language (see /locales.js) and otherwise the backend's own English text.
 *
 * Template rule: `tpl` may contain {placeholders} naming keys from THAT finding's
 * evidence dict. Placeholders are only used for keys confirmed to exist in the
 * detector source. If any referenced key is missing/undefined at fill time, the
 * English fallbackSummary is kept instead of emitting a broken template.
 *
 * Technical terms (token, JSON, HTTPS, finish_reason, TTFT, p95, CV, usage) are
 * intentionally left as-is.
 */
(function () {
  "use strict";

  // ---- Enum label maps ------------------------------------------------- //
  var RISK_LEVEL = {
    clean: "一致（疑似真货）",
    low: "基本可信",
    medium: "存在偏离",
    high: "货不对板",
    inconclusive: "信号不足",
  };

  var STATUS = {
    pass: "通过",
    warn: "警告",
    fail: "失败",
    info: "信息",
    inconclusive: "不确定",
    not_run: "未运行",
    error: "错误",
  };

  var SEVERITY = {
    info: "提示",
    low: "低",
    medium: "中",
    high: "高",
    critical: "严重",
  };

  var CONFIDENCE = { low: "低", medium: "中", high: "高" };

  // dimension id -> [zh 名称, zh 一句话说明]
  var DIMENSIONS = {
    connectivity: ["连通性", "端点是否可达、基础对话是否正常"],
    protocol: ["协议兼容", "是否符合 OpenAI 接口规范"],
    context_window: ["上下文窗口", "长文是否真能记住、有无静默截断"],
    model_identity: ["模型身份", "它是不是它自称的那个模型"],
    capability: ["能力声明", "工具调用 / JSON 模式是否真支持"],
    streaming: ["流式真实", "是真流式还是缓冲后伪装"],
    billing: ["计费用量", "token 用量有没有虚报"],
    reliability: ["并发可靠", "压力下的成功率与延迟"],
    security: ["传输安全", "传输加密与密钥处理"],
    performance: ["性能表现", "延迟、首字与吞吐是否稳定"],
  };

  // English counterparts, used when the UI language is EN.
  var EN = {
    RISK_LEVEL: {
      clean: "Consistent (likely genuine)",
      low: "Mostly trustworthy",
      medium: "Deviations found",
      high: "Bait-and-switch",
      inconclusive: "Insufficient signal",
    },
    STATUS: {
      pass: "Pass",
      warn: "Warning",
      fail: "Fail",
      info: "Info",
      inconclusive: "Inconclusive",
      not_run: "Not run",
      error: "Error",
    },
    SEVERITY: { info: "Info", low: "Low", medium: "Medium", high: "High", critical: "Critical" },
    CONFIDENCE: { low: "Low", medium: "Medium", high: "High" },
    DIMENSIONS: {
      connectivity: ["Connectivity", "Is the endpoint reachable and does basic chat work?"],
      protocol: ["Protocol compliance", "Does it follow the OpenAI API spec?"],
      context_window: ["Context window", "Does it really remember long input, or truncate silently?"],
      model_identity: ["Model identity", "Is it really the model it claims to be?"],
      capability: ["Capability claims", "Are tool calling / JSON mode really supported?"],
      streaming: ["Streaming authenticity", "Real streaming, or buffered and faked?"],
      billing: ["Billing & usage", "Is token usage over-reported?"],
      reliability: ["Concurrency reliability", "Success rate and latency under load"],
      security: ["Transport security", "Transport encryption and key handling"],
      performance: ["Performance", "Are latency, time to first token and throughput consistent?"],
    },
  };
  var ZH = {
    RISK_LEVEL: RISK_LEVEL,
    STATUS: STATUS,
    SEVERITY: SEVERITY,
    CONFIDENCE: CONFIDENCE,
    DIMENSIONS: DIMENSIONS,
  };

  function isZh() {
    return !window.EKTE_LANG || window.EKTE_LANG.isZh();
  }

  function label(kind, key) {
    var map = (isZh() ? ZH : EN)[kind] || {};
    if (!Object.prototype.hasOwnProperty.call(map, key)) return key;
    return isZh() ? map[key] : window.EKTE_LANG.tr(map[key]);
  }

  // ---- Finding catalog -------------------------------------------------- //
  // id -> { title, tpl } in Chinese, from ekte/i18n/locales/zh.json (served in
  // /locales.js). Placeholders reference keys verified in the finding's
  // evidence dict in ekte/detectors/*.py; the dynamic model_identity.fp.<probe>
  // family is stored under "model_identity.fp.*".
  var FINDINGS = ((window.EKTE_LOCALES || {}).findings || {}).zh || {};

  // Generic fallback title for unknown finding ids.
  var GENERIC_TITLE = "检测项";

  // ---- Template filling ------------------------------------------------- //
  // Replace {key} from evidence. If ANY referenced key is missing/undefined,
  // signal failure so the caller keeps the English fallback summary.
  function fillTemplate(tpl, evidence, yesNo) {
    if (!tpl) return null;
    var ev = evidence || {};
    var ok = true;
    // {key}, {key|list} (an array / object keys as "a, b") or {key|server}
    // (backend English text, e.g. a KB fingerprint's signal, translated).
    var out = tpl.replace(/\{([a-zA-Z0-9_]+)(?:\|(list|server))?\}/g, function (_m, key, mod) {
      var asList = mod === "list";
      if (!Object.prototype.hasOwnProperty.call(ev, key)) {
        ok = false;
        return "";
      }
      var v = ev[key];
      if (v === undefined || v === null) {
        ok = false;
        return "";
      }
      if (mod === "server" && typeof v === "string") return window.EKTE_LANG ? window.EKTE_LANG.server(v) : v;
      if (typeof v === "boolean") return (yesNo || ["是", "否"])[v ? 0 : 1];
      if (typeof v === "number") {
        // Trim noisy floats; keep ints intact.
        return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
      }
      if (asList && typeof v === "object") {
        return (Array.isArray(v) ? v : Object.keys(v)).join(", ");
      }
      if (typeof v === "object") {
        try {
          return JSON.stringify(v);
        } catch (e) {
          ok = false;
          return "";
        }
      }
      return String(v);
    });
    return ok ? out : null;
  }

  // ---- Branch-specific and generic summary templates ------------------- //
  // One finding id can come from several detector branches (pass / warn /
  // fail / inconclusive) whose evidence differs, so one template can't fit
  // them all. ALT lists [status or null, English template] tried first for
  // that id; GENERIC covers the request-failure branches that only carry
  // status_code / error_type. The English template is the lookup key into
  // EKTE_LOCALES (strings.<lang>, including "zh"), like every other UI string.
  var ALT = {
    "billing.partial-usage": [
      [null, "usage only gives total={reported_total} (prompt={reported_prompt}, completion={reported_completion}); the breakdown per-token billing relies on is missing and cannot be verified."],
    ],
    "capability.json_mode": [["pass", "JSON mode honored; parsed keys: {parsed_keys|list}."]],
    "capability.tools": [["pass", "Tool call delivered ({tool_name}); arguments returned as {arguments_type}."]],
    "connectivity.models": [["warn", "/v1/models is not available (HTTP {status_code})."]],
    "reliability.success_rate": [
      ["inconclusive", "At concurrency {concurrency}, all {requests} requests were rate-limited ({rate_limited} × HTTP 429)."],
    ],
    "security.headers": [
      ["info", "Revealing response headers: {revealing_headers|list}. Informational — can corroborate the upstream identity, not a failure."],
      ["pass", "Inspected {header_count} response headers; none expose upstream identity."],
    ],
    "model_identity.self_id": [
      ["fail", "Self-identifies as a rival brand ({forbidden_hits|list}) without naming the genuine brand."],
      ["warn", "Self-id names the genuine brand but also a rival ({forbidden_hits|list}); usually a benign contrast rather than a swap — corroborate before treating it as substitution."],
      ["warn", "Self-id names neither the genuine brand nor a rival; treat as weak/evasive evidence."],
      ["pass", "Self-id names the genuine brand."],
    ],
    "performance.latency_consistency": [["info", "{samples} clean samples; too few to judge consistency."]],
    "performance.ttft_consistency": [["info", "{samples} clean samples; too few to judge consistency."]],
    "performance.throughput_consistency": [["info", "{samples} clean samples; too few to judge consistency."]],
    "embed.dimension": [
      ["info", "Returned {returned}-d vectors; no known dimension for the claimed model to compare against."],
    ],
    "embed.connectivity": [
      ["error", "POST /embeddings failed (HTTP {status_code})."],
      ["error", "Expected 4 non-empty vectors, got {returned_vectors}."],
    ],
    "rerank.connectivity": [["error", "POST /rerank failed (HTTP {status_code})."]],
    // front_truncated_at is only in the evidence when the window ended on front
    // truncation, so these never shadow the ids' own templates.
    "context_window.truncation": [
      [null, "Real context window ~{effective_window} << declared {declared} (ratio {ratio}, silent truncation suspected). The start of a ~{front_truncated_at}-token prompt was dropped while its end was still recalled (front truncation)."],
    ],
    "context_window.short": [
      [null, "Real context window ~{effective_window} is below the declared {declared} (ratio {ratio}, recall degrades before the advertised limit). The start of a ~{front_truncated_at}-token prompt was dropped while its end was still recalled (front truncation)."],
    ],
    "context_window.no_recall": [
      [null, "Even a ~{smallest_probed}-token prompt failed recall; the usable window appears far below the declared {declared}. The start of a ~{front_truncated_at}-token prompt was dropped while its end was still recalled (front truncation)."],
    ],
    "context_window.measured": [
      [null, "No declared context window to compare against; measured effective window ~{effective_window} tokens. The start of a ~{front_truncated_at}-token prompt was dropped while its end was still recalled (front truncation)."],
    ],
    // error_type is only in the evidence when no HTTP response came back, so
    // this never shadows the generic HTTP-status template.
    "protocol.error_schema": [
      ["warn", "Invalid request got no HTTP response ({error_type}); could not confirm OpenAI-style client-error handling."],
    ],
  };
  var GENERIC = [
    "Request failed (HTTP {status_code}, type {error_type}).",
    "Request failed (HTTP {status_code}).",
    "Request failed (type {error_type}).",
  ];

  // Fill the first English template in `list` that resolves, translated into
  // the current language; null when none does.
  function fillFirst(list, evidence, yesNo) {
    var L = window.EKTE_LANG;
    var lang = L ? L.get() : "zh";
    for (var i = 0; i < list.length; i++) {
      var tpl = L ? L.trFor(lang, list[i]) : list[i];
      var s = fillTemplate(tpl, evidence, yesNo);
      if (s != null) return s;
    }
    return null;
  }
  function altTemplates(id, status) {
    return (ALT[id] || [])
      .filter(function (a) {
        return !a[0] || a[0] === status;
      })
      .map(function (a) {
        return a[1];
      });
  }
  // Summary for any non-EN language: branch template, then the id's own
  // template, then a generic request-failure template; null if none fits.
  function summaryFor(id, status, evidence, ownTpl, yesNo) {
    var s = fillFirst(altTemplates(id, status), evidence, yesNo);
    if (s == null && ownTpl) s = fillTemplate(ownTpl, evidence, yesNo);
    if (s == null) s = fillFirst(GENERIC, evidence, yesNo);
    return s;
  }

  // Resolve an id in a catalog, including dynamic id families stored under a
  // "<prefix>.*" key — per-fingerprint identity findings
  // (model_identity.fp.<probe>) and per-attribute protocol findings
  // (protocol_response.core.<attribute>, …). The longest matching prefix wins.
  function lookupIn(cat, id) {
    if (!id || !cat) return null;
    if (Object.prototype.hasOwnProperty.call(cat, id)) return cat[id];
    var parts = String(id).split(".");
    for (var i = parts.length - 1; i > 0; i--) {
      var key = parts.slice(0, i).join(".") + ".*";
      if (Object.prototype.hasOwnProperty.call(cat, key)) return cat[key];
    }
    return null;
  }

  // A catalog entry's title filled from the evidence. A title naming its
  // subject (model_identity.fp.*: "…: {signal|server}") falls back to the
  // entry's generic title when the evidence lacks it (older reports).
  function titleOf(entry, evidence) {
    if (!entry) return null;
    return (entry.title && fillTemplate(entry.title, evidence)) || entry.generic || null;
  }

  // The backend's English result title (one per outcome of a check, e.g.
  // "Endpoint is not HTTPS" vs "Endpoint uses HTTPS") in language `lang`,
  // keyed by the English text like other backend text (EKTE_LOCALES strings,
  // zh included), plus the few titles built around a subject (titlePatterns:
  // "Fingerprint divergence: {1}", the subject translated on its own). Null
  // when unknown, so the caller falls back to the check's catalog title.
  function resultTitle(lang, en) {
    var LOC = window.EKTE_LOCALES || {};
    var d = (LOC.strings || {})[lang];
    if (!d || !en || lang === "en") return null;
    var has = function (k) {
      return Object.prototype.hasOwnProperty.call(d, k);
    };
    en = String(en);
    if (has(en)) return d[en];
    var pats = LOC.titlePatterns || [];
    for (var i = 0; i < pats.length; i++) {
      var t = pats[i], at = t.indexOf("{1}");
      var pre = t.slice(0, at), post = t.slice(at + 3);
      if (!has(t) || en.length <= pre.length + post.length) continue;
      if (en.slice(0, pre.length) !== pre || en.slice(en.length - post.length) !== post) continue;
      var subject = en.slice(pre.length, en.length - post.length);
      return d[t].replace("{1}", has(subject) ? d[subject] : subject);
    }
    return null;
  }

  // Resolve a Chinese catalog entry.
  function lookup(id) {
    return lookupIn(FINDINGS, id);
  }

  /**
   * localizeFinding(id, fallbackSummary, evidence, fallbackTitle) -> { title, summary }
   *  - EN UI:   the backend's English fallbackTitle / fallbackSummary.
   *  - title:   the translated result title (resultTitle), else the check's
   *             title from the catalog, else a generic zh title.
   *  - summary: filled zh template; if the id is unknown OR a template
   *             placeholder is missing, the original English fallbackSummary
   *             is returned instead of a broken string.
   */
  function localizeFinding(id, fallbackSummary, evidence, fallbackTitle, status) {
    if (!isZh()) {
      var L = window.EKTE_LANG;
      if (L.get() === "en") {
        // The backend's own English text is authoritative for EN.
        return { title: L.server(fallbackTitle || id || "Check"), summary: L.server(fallbackSummary || "") };
      }
      var cat = ((window.EKTE_LOCALES || {}).findings || {})[L.get()];
      var le = cat && lookupIn(cat, id);
      var ls = summaryFor(id, status, evidence, le && le.tpl, [L.tr("yes"), L.tr("no")]);
      var lt = resultTitle(L.get(), fallbackTitle) || titleOf(le, evidence);
      return {
        title: lt || L.server(fallbackTitle || id || "Check"),
        summary: ls != null ? ls : L.server(fallbackSummary || ""),
      };
    }
    var entry = lookup(id);
    var summary = summaryFor(id, status, evidence, entry && entry.tpl);
    return {
      title: resultTitle("zh", fallbackTitle) || titleOf(entry, evidence) || GENERIC_TITLE,
      summary: summary != null ? summary : fallbackSummary || "",
    };
  }

  // ---- Downloadable report ---------------------------------------------- //
  // Same keys and schema as the server's report (it stays valid against
  // ekte's AuditReport model); only human-readable values are translated.
  function exportFinding(f) {
    var L = window.EKTE_LANG;
    var out = Object.assign({}, f);
    if (isZh()) {
      var entry = lookup(f.id);
      var s = summaryFor(f.id, f.status, f.evidence, entry && entry.tpl);
      out.title = resultTitle("zh", f.title) || titleOf(entry, f.evidence) || L.exportText(f.title);
      out.summary = s != null ? s : L.exportText(f.summary || "");
    } else {
      var loc = localizeFinding(f.id, f.summary, f.evidence, f.title, f.status);
      out.title = loc.title;
      out.summary = loc.summary;
    }
    if (f.recommendation != null) out.recommendation = L.exportText(f.recommendation);
    return out;
  }

  function exportReport(report) {
    var L = window.EKTE_LANG;
    if (!report || !L) return report;
    var r = JSON.parse(JSON.stringify(report));
    var titles = {}; // English finding title -> exported title
    ["detectors", "baseline_detectors"].forEach(function (k) {
      (r[k] || []).forEach(function (det) {
        if (det.name != null) det.name = L.exportText(det.name);
        det.findings = (det.findings || []).map(function (f) {
          var e = exportFinding(f);
          if (f.title && !(f.title in titles)) titles[f.title] = e.title;
          return e;
        });
        // the published scoring scale: one fixed backend sentence per outcome
        ((det.scoring && det.scoring.outcomes) || []).forEach(function (o) {
          if (o.label) o.label = L.exportText(o.label);
        });
        // titles of parametrized checks
        var st = det.scoring && det.scoring.titles;
        if (st) Object.keys(st).forEach(function (k) {
          st[k] = L.exportText(st[k]);
        });
      });
    });
    var title = function (t) {
      // "<title> (+N more)": several subjects of one parametrized check
      var m = /^(.*) \(\+(\d+) more\)$/.exec(t);
      if (m) return title(m[1]) + " " + L.exportText("(+{n} more)").replace("{n}", m[2]);
      return Object.prototype.hasOwnProperty.call(titles, t) ? titles[t] : L.exportText(t);
    };
    var v = r.verdict;
    if (v) {
      if (v.headline != null) v.headline = L.exportText(v.headline);
      if (v.summary != null) v.summary = L.exportText(v.summary);
      v.key_findings = (v.key_findings || []).map(title);
    }
    // A reason is a fixed sentence or the "; "-joined titles of the
    // dimension's failing findings (see ekte/scoring.py).
    (r.dimensions || []).forEach(function (d) {
      if (!d.reason) return;
      var fixed = L.exportText(d.reason);
      d.reason =
        fixed !== d.reason || L.get() === "en"
          ? fixed
          : d.reason.split("; ").map(title).join(isZh() ? "；" : "; ");
    });
    r.notes = (r.notes || []).map(function (n) {
      return L.exportText(n);
    });
    if (r.performance && r.performance.notes)
      r.performance.notes = r.performance.notes.map(function (n) {
        return L.exportText(n);
      });
    return r;
  }

  window.EKTE_I18N = {
    FINDINGS: FINDINGS,
    localizeFinding: localizeFinding,
    RISK_LEVEL: RISK_LEVEL,
    STATUS: STATUS,
    SEVERITY: SEVERITY,
    CONFIDENCE: CONFIDENCE,
    DIMENSIONS: DIMENSIONS,
    EN: EN,
    label: label,
    exportReport: exportReport,
    // English templates that every language (CN included) must translate.
    TEMPLATES: Object.keys(ALT)
      .reduce(function (all, id) {
        return all.concat(ALT[id].map(function (a) {
          return a[1];
        }));
      }, [])
      .concat(GENERIC),
  };
})();
