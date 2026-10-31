# Stability and compatibility policy

ekte follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). This
document defines **what that means for ekte**: which surfaces the version number
protects, what counts as a breaking change, how things are deprecated and
removed, what is supported, and what happens to your data when you upgrade or
downgrade. The English text is canonical; this document is not translated.

ekte is an **application**, not a library. Its contract is its command line, its
files, its reports and its container and CI integrations, not its Python code.

The policy applies from the first release that contains it (0.31). Until 1.0.0
the major version is 0, and the rules below apply with the *minor* version in
the role of the major one: a breaking change to a public surface may happen in a
minor release before 1.0.0, but only after the deprecation period, and it is
always listed under "Changed" or "Removed" in the [changelog](../CHANGELOG.md)
with the upgrade steps. From 1.0.0 on, breaking changes need a new major version.

## Contents

- [Surfaces at a glance](#surfaces)
- [What counts as breaking](#breaking)
- [Deprecation policy](#deprecation)
- [Supported Python versions](#python)
- [Supported operating systems](#os)
- Surfaces in detail: [CLI](#surface-cli), [exit codes](#surface-exit-codes),
  [config file](#surface-config), [environment variables](#surface-env),
  [report JSON](#surface-report), [webhooks](#surface-webhooks),
  [GitHub Action](#surface-action), [data directory](#surface-data),
  [HTTP API](#surface-http-api), [web UI addresses](#surface-web-addresses),
  [Python modules](#surface-python)
- [Upgrade guarantee for your data](#upgrade)
- [Downgrades](#downgrade)

<a id="surfaces"></a>
## Surfaces at a glance

**Public** means stable within a major version: it changes incompatibly only in
a major release, after a [deprecation period](#deprecation). **Internal** means
it may change in any release without notice.

| Surface | Status | Section |
|---|---|---|
| CLI commands, options, output formats | Public | [CLI](#surface-cli) |
| CLI exit codes | Public | [Exit codes](#surface-exit-codes) |
| Configuration file (`ekte.yaml`) | Public | [Config file](#surface-config) |
| Environment variables (the documented ones) | Public | [Environment variables](#surface-env) |
| Report JSON (`--format json`, `--json`, `--compact`) | Public | [Report JSON](#surface-report) |
| Webhook payloads (`ekte watch`, monitors) | Public | [Webhooks](#surface-webhooks) |
| GitHub Action inputs and outputs (`action.yml`) | Public | [GitHub Action](#surface-action) |
| Data directory and its databases | Public as an upgrade guarantee only | [Data directory](#surface-data) |
| HTTP API under `/api/` | Internal until decided by #22 | [HTTP API](#surface-http-api) |
| Web UI addresses (URLs) | Internal until decided by #28 | [Web UI addresses](#surface-web-addresses) |
| Python modules (`import ekte...`) | Internal | [Python modules](#surface-python) |
| Console text, Markdown/HTML/PDF report layout, web UI look and wording | Internal | [Breaking](#breaking) |
| Knowledge-base contents and scoring weights | Internal (data, not interface) | [Breaking](#breaking) |

<a id="breaking"></a>
## What counts as breaking

A change is **breaking** when something that worked and that this document
promises stops working or means something else, without the user changing
anything. For each public surface:

| Surface | Not breaking (allowed in any release) | Breaking (major release, after deprecation) |
|---|---|---|
| CLI | Adding a command, or an option whose default keeps today's behaviour; a new value for an open-ended option; new output on stderr | Removing or renaming a command, option or value; changing a default so results change; making an optional option required; changing what a documented value means |
| Exit codes | Using a code for a case that previously crashed with an unlisted code | Changing the meaning of a documented code; moving a documented case to another code |
| Config file | Adding an optional key; accepting more values for a key | Removing or renaming a key; making a key required; changing the meaning or default of a key so results change; rejecting a file that was valid |
| Environment variables | Adding a variable | Removing or renaming a variable; changing the meaning of a value |
| Report JSON | Adding an optional field; adding a value to a field documented as open-ended; reordering keys | Removing or renaming a field; changing a field's type or meaning; making an optional field required |
| Webhook payloads | Adding a field | Removing or renaming a field; changing a field's type or meaning; removing a supported platform format |
| GitHub Action | Adding an optional input or an output | Removing or renaming an input or output; changing a default so results change; changing an output's value format |
| Data directory | Adding files, tables or columns through a migration | Any change that loses data, or that an upgrade within the major version cannot migrate automatically (see [Upgrade guarantee](#upgrade)) |

Not covered by the version number, because they are results and presentation and
not interface: the **verdict of an audit** (scores, risk levels and findings can
change when detectors, scoring or the knowledge base improve; such changes are
listed in the changelog), the wording of messages and findings, the layout of
Markdown, HTML and PDF reports, and the look of the web UI. Fixing a bug is never
breaking, even if someone relied on the bug.

<a id="deprecation"></a>
## Deprecation policy

- A public feature is **deprecated** before it is removed: it keeps working and
  prints a warning (stderr for the CLI, a log or `warnings` entry elsewhere)
  that names the replacement.
- A deprecated feature keeps working for **at least one minor release** after
  the release that deprecated it.
- It is **removed only in a major release** (before 1.0.0: in a minor release,
  as described at the top).
- The deprecation and the removal are both listed in the
  [changelog](../CHANGELOG.md) under "Deprecated" and "Removed".
- A security fix may break a public surface without a deprecation period when
  there is no safe way to keep it; the changelog says so.
- Internal surfaces need no deprecation.

The zing-era `ZING_*` environment variables and the `~/.zing` data directory are
deprecated in this sense; their removal is planned by #26.

<a id="python"></a>
## Supported Python versions

ekte supports **every CPython version that is not end-of-life**, as listed on
[devguide.python.org/versions](https://devguide.python.org/versions/). Today that
is **3.11, 3.12, 3.13 and 3.14**.

- A new CPython version is added to the supported set, and to the CI test matrix,
  in the first minor release after its final release in which the test suite passes.
- A version is **dropped in the first minor release after its end of life**.
  Python 3.10 reaches end of life in October 2026 and is dropped in 0.31.
- Dropping a Python version is announced in the changelog and is not a breaking
  change. The `requires-python` field in the package metadata always matches this
  rule, so `pip` keeps installing the last compatible ekte on older Pythons.
- Other implementations (PyPy and so on) are not tested and not supported.

<a id="os"></a>
## Supported operating systems

**Linux, macOS and Windows** are supported and tested in CI. The **Docker image
is Linux** (see [DOCKER.md](DOCKER.md)). A bug that occurs on one of these systems
is a bug, not a limitation. Dropping an operating system needs a major release.

- **CI.** The full test suite runs on Linux on every supported Python version. On
  macOS and Windows it runs on the oldest and the newest supported Python (today
  3.11 and 3.14): the Python versions behave the same across systems, so the
  extremes find the platform problems at a third of the cost. Tests that only
  make sense on POSIX are skipped on Windows with an explicit reason.
- **Owner-only data directory.** On Linux and macOS ekte creates the data
  directory with mode `0700` and the database files with `0600`. Windows ignores
  these modes: the directory inherits the permissions of its parent folder, which
  for the default `%USERPROFILE%\.ekte` is your account, administrators and the
  system. ekte says so on standard error when it creates the directory there. Put
  `EKTE_DATA_DIR` inside your user profile and do not share it.
- **Master key.** The master key is never stored in the data directory (see
  `ekte secret`). It comes from `EKTE_SECRET_KEY` or is entered by the user, on
  every system. A legacy `secret.key` file is protected only where file modes work.
- **Local-only server.** `ekte serve` binds to loopback by default on every
  system; this does not depend on the operating system.
- **Paths and home directory.** The default data directory is `~/.ekte`
  (`%USERPROFILE%\.ekte` on Windows). Text files are read and written as UTF-8.
- **PDF reports.** They use a pure Python library and need no system libraries on
  any of the three systems.

<a id="surface-cli"></a>
## CLI commands, options and output formats

Public. The commands are `ekte init`, `check`, `compare`, `models`, `kb`,
`kb-prompt`, `kb-import`, `kb-export`, `serve`, `watch`, `embed`, `rerank`,
`image`, `audio`, `data-dir`, `config` (`migrate`) and `secret` (`status`, `export`, `rotate`), plus
`--version` and `--help`. Their options and values are those shown by
`ekte <command> --help`.

- Machine-readable output is public: `--json` (full report on stdout), `--compact`
  (lean verdict), `--format json|md|html|pdf|all` (files), `kb --json`,
  `models --json`, and the `{"error": {...}}` object printed on stdout for
  configuration errors in `--json` and `--compact` mode.
- Human-readable console output (tables, colours, wording) is internal and may
  change in any release. Scripts should read JSON and the exit code.
- Short aliases (`-c`, `-p`, ...) are as stable as the long option.
- Consistency rules (command line review, #25): the same option means the same
  thing in every command (`--json`, `--fail-on-risk`, `--claimed-model`, `--format`
  = report file format), long options are lowercase words joined by hyphens, and
  short options exist only for `-c`, `-H`, `-D` and `-p`. Every command and option
  has a help text. The full reference is [CLI.md](CLI.md), generated from the
  `--help` declarations; a test fails when it is out of date.
- With `--json` (and `--compact`) stdout carries only JSON; messages, progress and
  warnings go to stderr. `--json` is available on every command that reports a
  result (`watch --json` prints one JSON object per cycle).
- Renamed options keep working with a deprecation warning on stderr that names the
  replacement and the removal version: `ekte audio --format` is now
  `--audio-format`, and `ekte image|audio --save` is now `--save-to` (both removed
  in 1.0.0).

<a id="surface-exit-codes"></a>
## Exit codes

Public. Every command follows this one table (also in [CLI.md](CLI.md)); a test
pins each code.

| Code | Meaning | When |
|---|---|---|
| 0 | success | The command succeeded; any gate passed. |
| 1 | gate or check failed | The risk is at or above `--fail-on-risk`, the score is below `--fail-under`, `kb-import` rejected the file, or `config migrate --check` found an outdated file. |
| 2 | usage or configuration error | Invalid option, value or configuration file, or a missing extra or master key. In `--json` and `--compact` mode an `{"error": {...}}` object is printed on stdout. |
| 3 | endpoint failure | `ekte models` could not list the models: the endpoint is unreachable or answered with an error. (Before 0.32 it exited 1.) |
| 4 | internal error | An unexpected error in ekte itself; the traceback is on stderr. (Before 0.32 an unexpected crash exited 1.) |

<a id="surface-config"></a>
## Configuration file

Public. The file is YAML, `ekte.yaml` by default (`ekte init` writes a commented
starter; `ekte check -c ekte.yaml` reads it).

- **Format version.** The top-level key `version` is the format version; the
  current one is **1**. A file without `version` is format 1. A file with a
  newer version than the installed ekte understands is refused with a message
  to upgrade ekte.
- **Validation.** Unknown keys, wrong types and invalid values are rejected
  (exit code 2) with a message naming the file, the line, the key and what is
  expected. A key added in a newer release therefore does not load in an older
  one.
- **Schema.** Every key, with its type, allowed values and default, is in
  [`schemas/config.schema.json`](schemas/config.schema.json) (JSON Schema,
  generated from `ekte/configfile.py`). Adding an optional key adds it to the
  schema; the file for a released format only grows.
- **Deprecated keys** keep working for the [deprecation period](#deprecation)
  and print a warning on stderr that names the replacement. There are none in
  format 1.
- **New formats.** A change that is breaking by the table above gets a new
  `version`. Files of an older format are refused with the command that fixes
  them: `ekte config migrate FILE` rewrites the file to the current format,
  keeping its comments and writing `FILE.bak` first (`--check` only reports).
  `ekte init` always writes the current version.

<a id="surface-env"></a>
## Environment variables

Public (all `EKTE_`-prefixed variables below):

| Variable | Purpose |
|---|---|
| `EKTE_DATA_DIR` | Data directory (default `~/.ekte`) |
| `EKTE_SECRET_KEY` | Master key for stored API keys |
| `EKTE_KB_DIR` | Extra knowledge-base directory |
| `EKTE_NO_USER_KB` | Ignore the user's own knowledge-base entries |
| `EKTE_HOST`, `EKTE_PORT` | Bind address and port of `ekte serve` |
| `EKTE_ALLOWED_HOSTS` | Extra accepted `Host` values for `ekte serve` |
| `EKTE_CONTAINER` | Allow a non-loopback bind inside a container |
| `EKTE_MAX_PARALLEL_AUDITS` | Concurrent audits in the web UI |

Also public: any variable you name yourself and pass as `--api-key env:NAME` or
`api_key: env:NAME`. The `ZING_*` equivalents are deprecated (see
[deprecation](#deprecation)). Any other `EKTE_*` variable (for example those only
the test suite reads) is internal.

<a id="surface-report"></a>
## Report JSON

Public. The structure is the `AuditReport` document written by `--format json`,
printed by `--json` and stored in the history: top-level `tool_version`, `mode`,
`generated_at`, `suite`, `surface`, `target`, `baseline`, `verdict`, `dimensions`,
`detectors`, `reliability`, `performance`, `judge_used`, `notes`, `warnings`,
`knowledge` and related fields. The lean `--compact` verdict
(`{"verdict": {"risk", "score", "rating", ...}, "target": {...}}`) is public too.
API keys never appear in a report.

Every report carries `schema_version` (`MAJOR.MINOR`, independent of the ekte
version). The JSON Schema is published as
[`ekte/schemas/report.schema.json`](../ekte/schemas/report.schema.json) (it ships
in the wheel and the sdist) and is generated from the `AuditReport` model. See
[SCHEMAS.md](SCHEMAS.md) for the format, an example and how to validate.

- A compatible change (a new optional field) raises the **minor** schema version.
  A breaking change (see [Breaking](#breaking)) raises the **major** schema
  version, and happens only in a major ekte release after the deprecation period.
- CI fails when the schema changes without a version bump.
- Consumers must ignore fields they do not know. Reports written by older
  versions stay readable by newer ones: a report without `schema_version`
  (written before 0.32) is schema version 1.0, and history, re-run and
  re-export read it unchanged.

<a id="surface-webhooks"></a>
## Webhook payloads

Public. `ekte watch` and monitors POST an alert on a risk threshold or a
regression. The generic payload has the fields `tool`, `event` (`audit_alert`),
`language`, `text`, `risk_level`, `score`, `rating`, `headline`, `base_url`,
`claimed_model`, `key_findings`, `previous_risk_level` and `regressed`. Machine
values are language-neutral; `text`, `headline` and `key_findings` are in the
alert language. The Slack, Feishu/Lark and DingTalk bodies follow the respective
platform's schema; their text is internal, the platform envelope is public.

The generic payload carries `schema_version` (`MAJOR.MINOR`, versioned
independently of the report schema and of ekte). Its JSON Schema is published as
[`ekte/schemas/webhook.schema.json`](../ekte/schemas/webhook.schema.json),
generated from the code that builds the payload. Adding a field raises the minor
version; removing or renaming a field or changing its type or meaning raises the
major version, in a major ekte release only. CI fails on an unannounced change.
Consumers must ignore fields they do not know. See [SCHEMAS.md](SCHEMAS.md).

<a id="surface-action"></a>
## GitHub Action

Public. The inputs and outputs of [`action.yml`](../action.yml), documented in
[CI.md](CI.md):

- Inputs: `base-url`, `api-key`, `model`, `claimed-model`, `api`,
  `declared-provider`, `suite`, `fail-on-risk`, `python-version`, `version`.
- Outputs: `risk`, `score`, `rating`.

The action runs the ekte version selected by the `version` input; its behaviour
follows this policy. The actions the composite action and the repository's
workflows use internally are pinned to full commit SHAs and checked by a
workflow linter in CI; that hardening is not part of the public surface and can
change in any release. The inputs reach the action's shell scripts only through
environment variables, so their values are never interpreted as shell code.

<a id="surface-data"></a>
## Data directory and databases

The location (`~/.ekte`, or `EKTE_DATA_DIR` / `--data-dir`) is public. The files
inside (`history.db`, `watches.db`, `kb.db`, `secret.key`) and their schemas are
**internal**: do not read or write them with other tools. What is public is the
[upgrade guarantee](#upgrade) and the [downgrade behaviour](#downgrade). Use
reports, `ekte kb-export` and `ekte secret export` for data you want to take
elsewhere.

<a id="surface-http-api"></a>
## HTTP API under `/api/`

To be decided by #22 (public contract or internal to the web UI). **Internal
until then**: it may change in any release.

<a id="surface-web-addresses"></a>
## Web UI addresses

To be decided by #28 (final addresses; serving the UI at the root). **Internal
until then**: pages may move in any release. The default bind address (loopback
`127.0.0.1:8000`) and the `ekte serve` options are public as part of the
[CLI](#surface-cli).

<a id="surface-python"></a>
## Python modules

Internal. ekte is an application, not a library: `import ekte...`, the module,
class and function names and the pydantic models may change in any release. To
use ekte from Python, call the CLI and read its JSON.

<a id="upgrade"></a>
## Upgrade guarantee for your data

An **upgrade within a major version never loses or corrupts data** in the data
directory (audit history, watches, your knowledge-base entries, stored API
keys). When a release changes the format of a database, ekte migrates it
automatically on first start, and it first writes a **backup next to the
database** (the migration mechanism of #14). If a migration fails, the original
is untouched and ekte stops with a message instead of continuing with
half-migrated data. Skipping versions within a major version is supported.

Upgrading across a major version is covered by the migration notes in the
changelog.

<a id="downgrade"></a>
## Downgrades

Downgrades are **not supported**. An older ekte that finds a data directory or
database written by a newer ekte **refuses to open it, modifies nothing, and
points to the pre-migration backup** made by the upgrade. To go back, install the
older version and restore that backup (or use a fresh data directory).
