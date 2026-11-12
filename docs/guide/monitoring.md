# Monitoring

> **🇬🇧 English** · [🇨🇳 中文](../i18n/zh-CN/guide/monitoring.md) · [🇫🇷 Français](../i18n/fr/guide/monitoring.md) · [🇪🇸 Español](../i18n/es/guide/monitoring.md) · [🇵🇹 Português](../i18n/pt/guide/monitoring.md) · [🇮🇹 Italiano](../i18n/it/guide/monitoring.md) · [🇩🇪 Deutsch](../i18n/de/guide/monitoring.md) · [🇳🇴 Norsk](../i18n/nb/guide/monitoring.md)

Relays can serve the real model today and quietly swap it next week. `ekte watch`
re-audits on a schedule, records each run to the history, and alerts a webhook
when the risk crosses a threshold or **regresses** versus the previous run.

```bash
ekte watch --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang en                                     # or --once for cron
```

Alerts are formatted for **Slack / Feishu / DingTalk / generic JSON**,
auto-detected from the webhook URL, and written in the alert language — English
by default; `--alert-lang en|zh|fr|es|pt|it|de|nb`. The generic JSON payload keeps
its keys and machine values (`risk_level`, `score`, …) language-neutral,
translates the human-readable ones (`text`, `headline`, `key_findings`) and
reports the `language`.

**In the web UI**, `ekte serve` runs the same monitors in a background scheduler
inside the server process, stores every run in **History** and sends the same
webhook alerts. Open a run in **History** and choose **Schedule as monitor**. ekte
copies that run's configuration (relay, model, claimed model, provider, suite,
custom dimensions) into a paused monitor on the **Monitors** page; set its
interval and API key there (History never stores keys) and switch it on.
Interval, key, **Alert threshold**, webhooks and **Alert language** can be
edited in place on each monitor. Click a monitor's name to collapse its card
to name, status and last run (**Collapse all** / **Expand all** above the
list; remembered per browser), and narrow a long list with the filter panel
(search, status, last risk, endpoint type, relay, suite) as on **History**.

Each monitor has its own alert language (defaulting to the UI language), can be
run now, paused or deleted, and pins the knowledge-base profile it was created
with until you re-pin it.

Every monitor run and every `ekte watch` cycle keeps its raw requests and
responses with the saved run (see [Privacy](privacy.md)); a monitor's **Raw
requests/responses** setting (**Keep** / **Don't keep**) and
`ekte watch --no-evidence` turn that off.

Monitors that come due run at the same time, each as its own audit, but never
more than one audit per relay host at once and at most `EKTE_MAX_PARALLEL_AUDITS`
in total; a run waits for a free slot (an audit you start by hand may queue
behind running monitors, too). A run's time is when its audit starts, after any
wait. The regression check compares against the most recent saved run of the
same relay and model, however many other runs were saved since. Alert webhooks
of a run are sent at the same time, so a slow or dead one does not hold up the
others. API keys are never sent back to the browser.

**API key storage.** By default ekte **does not store** the monitors' API keys:
a key you enter stays in the memory of `ekte serve` only and is never written to
disk. After a restart the **Monitors** page names the monitors that need their
key again, and they wait (no failed run, no alert) until you enter it; keyless
monitors and `env:`/`file:` references keep running. To have keys survive
restarts, pick **Store encrypted on this machine** under **API key storage** on
the **Monitors** page: the keys are then kept in `watches.db`, encrypted with
a master key. Switching back moves the stored keys into memory and erases them
from `watches.db`. The page notice says which mode is in effect, asks before a
switch and reports what moved. An install that already stored encrypted keys, or that
sets `EKTE_SECRET_KEY`, keeps storing them until you switch.

**Master key.** When keys are stored, they are encrypted with a master key that
ekte never writes to disk. The first time you choose to store keys, the
**Monitors** page creates it and shows it once: copy or download it, keep it in a password manager
(your browser can save it), then paste it back to confirm. After every restart
of `ekte serve` the page asks for it again (the browser can fill it in); until
then, monitors that need it wait, while keyless monitors and `env:`/`file:` keys
keep running. The status bar on the **Monitors** page also offers **Lock**,
**Rotate** and **Forgot the key?** (drops the encrypted API keys so you can
enter them again). For unattended or Docker use, pass the key as
`EKTE_SECRET_KEY` (see [Docker](docker.md));
`ekte secret status | export | rotate` manage it on the command line.

### Run window

A monitor can have a **run window**: the days of the week and hours in which
the scheduler starts it, for example Mon–Fri, 07:00–19:00, Europe/Berlin. Edit
it in place on the Monitors page (**Run window**, after **Check interval**).
Outside the window the monitor does not run. Without a window it runs around
the clock, as before.

- Whole hours only. `24:00` is the end of the day. An end at or before the
  start is an overnight window: it ends the next morning and belongs to the
  day it starts on (a Friday 22:00–06:00 window covers Saturday 00:00–06:00).
- The window uses the time zone stored with it (an IANA name), never the
  server's. Daylight saving changes are harmless: ekte only asks whether *now*
  is inside the window.
- A monitor is due when its interval has elapsed **and** it is inside the
  window. After a closed period it runs once when the window opens, not once
  per missed slot. A scheduled run that waited for its relay past the end of
  the window is skipped and records nothing.
- **Run now** ignores the window. Pausing a monitor is independent of it.
- **Blind spot:** hours outside the window are not checked, and a dishonest
  relay can learn the pattern. The editor shows how many hours a week are not
  checked.
- `ekte watch` has no run window; use cron with `--once`.
