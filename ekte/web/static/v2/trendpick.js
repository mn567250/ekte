/* ekte web UI v2 — the History trend picker's selection rules
 * (window.EkteTrendPick). No metric logic: which trends exist, their order
 * and the maximum come from the server (GET /api/metrics `history_trends`,
 * `max_trends`); this only keeps a selection within them.
 *
 * At least one and at most `max` trends are active:
 *   - with one selected, that button cannot be turned off (disabled);
 *   - with `max` selected, every other button is disabled.
 *
 * EkteTrendPick.clean(value, order, max, fallback) -> ids
 *   a selection from a URL value ("score,latency_p50", or an array): unknown
 *   and repeated ids dropped, at most `max` kept (in the order given), put in
 *   `order`; nothing left -> `fallback` cleaned the same way.
 * EkteTrendPick.toggle(selected, id, order, max) -> ids
 *   the selection after a click on `id`; unchanged when the click is not
 *   allowed (the last one, or a new one beyond the maximum).
 * EkteTrendPick.buttons(selected, order, max) -> [{ id, pressed, disabled }]
 *   each option's state, in `order`.
 */
(function () {
  "use strict";

  function list(value) {
    if (Array.isArray(value)) return value.map(String);
    return String(value == null ? "" : value).split(",");
  }

  function inOrder(ids, order) {
    return order.filter(function (id) { return ids.indexOf(id) >= 0; });
  }

  function clean(value, order, max, fallback) {
    var out = [];
    list(value).forEach(function (raw) {
      var id = raw.trim();
      if (id && order.indexOf(id) >= 0 && out.indexOf(id) < 0 && out.length < max) out.push(id);
    });
    if (!out.length && fallback !== undefined) return clean(fallback, order, max);
    return inOrder(out, order);
  }

  function toggle(selected, id, order, max) {
    var sel = clean(selected, order, max);
    if (order.indexOf(id) < 0) return sel;
    var on = sel.indexOf(id) >= 0;
    if (on) return sel.length > 1 ? sel.filter(function (x) { return x !== id; }) : sel;
    return sel.length < max ? inOrder(sel.concat([id]), order) : sel;
  }

  function buttons(selected, order, max) {
    var sel = clean(selected, order, max), full = sel.length >= max, only = sel.length === 1;
    return order.map(function (id) {
      var on = sel.indexOf(id) >= 0;
      return { id: id, pressed: on, disabled: on ? only : full };
    });
  }

  window.EkteTrendPick = { clean: clean, toggle: toggle, buttons: buttons };
})();
