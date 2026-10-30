/* Dimension picker of the custom suite.
 *
 * Markup (translated by lang.js like any other control):
 *   <div class="chips" id="dims" role="group">
 *     <button type="button" aria-pressed="true" data-v="protocol" data-en="Protocol compliance">协议兼容</button>…
 *   </div>
 *
 * window.ZING_DIMPICK.bind(el, onChange) makes the buttons independent
 * toggles and returns { value(), set(list) }: value() is the selected
 * dimension ids in markup order, set() selects exactly the given ids.
 */
(function () {
  "use strict";

  function bind(el, onChange) {
    var buttons = [].slice.call(el.querySelectorAll("button[data-v]"));
    function value() {
      return buttons
        .filter(function (b) {
          return b.getAttribute("aria-pressed") === "true";
        })
        .map(function (b) {
          return b.getAttribute("data-v");
        });
    }
    function set(list) {
      var want = list || [];
      buttons.forEach(function (b) {
        b.setAttribute("aria-pressed", String(want.indexOf(b.getAttribute("data-v")) >= 0));
      });
      if (onChange) onChange(value());
    }
    el.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-v]");
      if (!b || b.disabled || !el.contains(b)) return;
      b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"));
      if (onChange) onChange(value());
    });
    return { value: value, set: set };
  }

  window.ZING_DIMPICK = { bind: bind };
})();
