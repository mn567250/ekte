/* ekte web UI v2 — the Disclosure's behaviour (styles: .disclosure in
 * ekte.css, issue 227). A button and a region:
 *
 *   <button type="button" class="disclosure" data-disclosure
 *           aria-expanded="false" aria-controls="x-body">… <span class="cv">…</span></button>
 *   <div class="disclosure-body" id="x-body" hidden>…</div>
 *
 * A click (Enter, Space) on a [data-disclosure] button flips aria-expanded
 * and the region's hidden, then fires "ekte:disclosure" on the button
 * (detail: { open }) so a page can remember the state. Pages that already
 * drive a disclosure themselves (Analytics' tables, the filter panel, the
 * audit's baseline) leave data-disclosure off. No native <details>: its
 * looks and screen-reader output differ between browsers.
 */
(function () {
  "use strict";

  function toggle(btn, open) {
    var region = document.getElementById(btn.getAttribute("aria-controls"));
    if (open == null) open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(open));
    if (region) region.hidden = !open;
    btn.dispatchEvent(new CustomEvent("ekte:disclosure", { bubbles: true, detail: { open: open } }));
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("button[data-disclosure]");
    if (btn && !btn.disabled) toggle(btn);
  });

  // The markup of one disclosure (button + region), for pages that build it:
  //   EkteDisclosure.html({ id, label, body, open, lead, cls, bodyCls })
  // label and body are markup; id names the region; lead: chevron first (a
  // row or group in a list); cls: extra classes on the button.
  function html(o) {
    var open = !!o.open;
    var cv = window.ekteIcon ? window.ekteIcon("chevronDown") : "";
    return '<button type="button" class="disclosure' + (o.lead ? " lead" : "") + (o.cls ? " " + o.cls : "") +
      '" data-disclosure aria-expanded="' + open + '" aria-controls="' + o.id + '">' +
      '<span class="t">' + o.label + '</span><span class="cv" aria-hidden="true">' + cv + "</span></button>" +
      '<div class="disclosure-body' + (o.bodyCls ? " " + o.bodyCls : "") + '" id="' + o.id + '"' + (open ? "" : " hidden") + ">" +
      o.body + "</div>";
  }
  function isOpen(btn) { return !!btn && btn.getAttribute("aria-expanded") === "true"; }

  window.EkteDisclosure = { toggle: toggle, html: html, isOpen: isOpen };
})();
