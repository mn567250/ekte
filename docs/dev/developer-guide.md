# ekte — Developer guide

This guide is for people who change ekte: the principles, the development
setup, the repository layout, contributing and testing. What ekte does and how
to use it is in the [README](../../README.md) and the [user guide](../guide/);
how every check works and is scored is in the
[Methodology](../guide/methodology.md). The developer documentation is in
English only.

| Document | Covers |
|---|---|
| [Architecture](architecture.md) | Audit pipeline, clients, detectors, scoring, knowledge base, prompts, reports, surfaces, local data |
| [Web server and HTTP API](web-server.md) | The FastAPI server, its local-only protections, background jobs, the HTTP API v1 |
| [Web front end](ui.md) | Pages, shared scripts, design tokens and themes, page notices |
| [Accessibility](accessibility.md) | BITV / EN 301 549 coverage, the conformance report, manual review |
| [Maintaining the knowledge base](knowledge-base.md) | Editing profiles and keeping them current |
| [Translations](translations.md) | UI strings and documentation in every language |
| [Continuous integration](ci.md) | Workflows, dependency updates, vulnerability checks, distribution contents |
| [Releases](releasing.md) | Cutting a release, release candidates, recovery; [checklist](release-checklist.md), [PyPI publishing](publishing.md) |

## Principles

ekte is a black-box auditing aid: correctness and **not falsely accusing honest
relays** matter more than catching every possible trick. Keep that bar in mind
for any change.

- **Evidence over accusation.** Findings report *divergence and risk*, never
  "fraud". Prefer *inconclusive* to a guess. A new HIGH-severity path needs hard,
  reproducible evidence and must be hard to trip on an honest endpoint.
- **No network in tests.** Detector tests run against the in-process mock server
  in `tests/conftest.py` (httpx `MockTransport`), never a live API.
- **Secrets never leave.** API keys are fingerprinted, never stored in reports.
  Any new output path must route relay-controlled text through
  `ekte.utils.redact` and escape it for its format.
- **Same probes for everyone.** Probe texts are English and fixed, whatever the
  UI language, so the same relay gets the same verdict (see
  [Prompt library](architecture.md#prompt-library)).
- **Local only.** ekte contacts only the endpoints the user configures, and the
  web UI only listens on loopback (see [Web server](web-server.md#web-server)).

## Development setup

Requires Python 3.11+. Linux, macOS and Windows are tested in CI; tests that only make sense on POSIX are skipped on Windows with an explicit reason (`skipif(sys.platform == "win32", reason=...)`). Use `pathlib`, pass `encoding="utf-8"` to text I/O and never hard-code `/tmp`. Node.js is optional: the tests of the browser JavaScript
run under `node` and are skipped without it.

```bash
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e '.[dev,web]'   # editable install with the dev tools and the web UI
pytest                        # test suite
ruff check ekte tests         # lint
mypy ekte                     # type-check
```

With uv: `uv venv && uv pip install -e '.[dev,web]'`. No system
libraries are needed, PDF reports included.

Run from source with `ekte …` or `python -m ekte …`. `ekte serve` serves the
web UI from `ekte/web/static/` directly, so a browser reload picks up front-end
changes; there is no build step.

## Repository layout

```text
ekte/
  cli.py               Typer CLI: check, compare, models, kb*, serve, watch, embed, rerank, image, audio,
                       init, config, data-dir, secret
  clidocs.py           renders docs/reference/cli.md from the CLI's own options
  config.py            YAML config, secret references (env:/file:), AuditOptions
  configfile.py        config file format: schema, validation, migration, its JSON schema
  runner.py            run_audit(): wires everything up and runs the detectors
  context.py           AuditContext handed to every detector
  models.py            pydantic data contracts: TargetConfig, Finding, DetectorResult, AuditReport, …
  scoring.py           dimension scores, weights, overall score, risk verdict, confidence
  clients/             HTTP clients: OpenAI-compatible, Anthropic Messages, OpenAI Responses
  detectors/           one file per detector, plus base.py (registry), scale.py, helpers.py
  judge/               the trusted LLM judge used by quality_judge
  knowledge/           KB schema, loader, user store (kb.db), importer, research prompt, snapshots
    data/              packaged provider profiles (*.yaml)
  prompts/en.json      every text ekte sends to an LLM API
  perf/                per-request recorder and the report's performance section
  report/              JSON / Markdown / HTML / PDF renderers and the writer
  embed_audit.py       standalone embedding and rerank auditor
  media_audit.py       standalone image and audio (TTS) auditor
  notify.py            webhook alerts (Slack / Feishu / DingTalk / generic JSON)
  datadir.py           the local data directory and its SQLite files
  dbmigrate.py         versioned schema migrations (with backups) of every SQLite database
  schemas/             JSON schemas of the report and the webhook payload (generated)
  legacy.py            the ZING_* settings and the ~/.zing copy from before the rename
  secretbox.py         encryption of stored secrets; the master key held in memory
  i18n/                translations shared by the web UI and the alerts
    locales/           <code>.json per language, fragments/<feature>/<code>.json
  utils/               redaction, SSE parsing, statistics, token estimation
  web/
    server.py          FastAPI app: pages, JSON API, SSE audit stream, monitor scheduler
    caching.py         gzip compression and browser caching of pages and assets
    jobs.py            background audit jobs and the per-relay gate
    security.py        loopback bind, Host allowlist, Origin/JSON checks, headers
    history.py         audit history store (history.db)
    analytics_store.py its analytics tables: per-run metrics, request records
    analytics.py       analytics queries: KPIs, time series, leaderboards
    watches.py         monitor store (watches.db)
    masterkey.py       the master key's states and actions (server and `ekte secret`)
    static/            scripts shared by every page (lang.js, i18n.js, icons.js, …)
    static/v2/         the web UI's pages, styles and scripts
tests/                 pytest suite; conftest.py holds the mock relay
scripts/               checks and generators run by CI and releases (translations, coverage, CLI
                       reference, schemas, dist contents, vulnerabilities, release checks)
docs/                  guide/ (user guide), i18n/<lang>/ (its translations), reference/, dev/
examples/ekte.yaml     annotated config file
action.yml             the GitHub composite action
Dockerfile             web UI image
```

## Contributing

### Pull requests

- Keep `pytest`, `ruff check ekte tests` and `mypy ekte` green (CI runs all three
  on Python 3.11–3.14).
- Describe the relay trick or the false positive a change addresses.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Update the documentation the change touches. The README and the user guide
  (`docs/guide/`) in **every language** (see [Translations](translations.md#documentation));
  developer and reference docs in English.

By contributing you agree that your contributions are licensed under the
project's [Apache-2.0](../../LICENSE) license.

### Adding a detector

1. Create `ekte/detectors/<name>.py` and import it in
   `ekte/detectors/__init__.py`.
2. Define its `SCALE` (`Scale` or `DeductionScale` from `scale.py`) with every
   outcome of every check, and create findings only through it.
3. Subclass `Detector`; set `id`, `name`, `dimension`, `min_suite` and
   `cost_hint`; set `requires_judge = True` or `requires_baseline = True` if it
   needs one, or override `applies()` for other gating. Decorate it with
   `@register`.
4. Implement `async def run(self, ctx) -> DetectorResult`, starting from
   `self.new_result(scoring=SCALE.scoring())`. Send requests through `ctx.client`
   and take every prompt from `ekte/prompts/en.json`.
5. Add behavioral tests for both the flagged and the clean path, using the mock
   relay in `tests/conftest.py`.
6. Translate new finding titles and summaries (see [Translations](translations.md#translations))
   and document the detector and its scale in every
   [Methodology](../guide/methodology.md) file.

### Changing probe prompts

Probe texts are calibration data. Changing one in `ekte/prompts/en.json` can
change answer checks, token estimates and thus verdicts, so adjust the detector
and its tests with it, and mention the change in the CHANGELOG. Never make a
probe follow the UI language.

### Changing a database schema

Every SQLite database ekte creates (`history.db`, `watches.db`, `kb.db`) is
versioned and migrated by one shared mechanism, `ekte/dbmigrate.py`; a store
never migrates itself with ad-hoc `ALTER TABLE`s. The schema version lives in
`PRAGMA user_version`, and `datadir.connect(name, MIGRATIONS)` checks it on
every open.

To change a schema:

1. Add a function `_vN(conn)` to the store (`web/history.py`, `web/watches.py`,
   `knowledge/store.py`) that makes the change, and append
   `dbmigrate.Migration(N, _vN)` to its `MIGRATIONS` tuple. Never edit or
   reorder an existing step: databases in the field have already run it.
2. Keep the step idempotent (`CREATE ... IF NOT EXISTS`, and
   `kb_snapshot.add_link_columns()` for columns) and do not commit or roll back
   inside it. The mechanism runs each step in its own `BEGIN IMMEDIATE`
   transaction together with the version bump, so an interrupted or failing
   step leaves the database at the previous version.
3. A new database starts at version 0 and runs every step; a database from
   before versioning also has version 0, which is why step 1 of a store must
   adopt an existing schema.
4. Add a test to `tests/test_dbmigrate.py` that builds the schema at version
   N-1, opens it and checks the new version, the new schema and that the data
   is intact. If rows need filling for existing data, do that in the store's
   `on_migrated` callback (see `history._after_migration`), not in the step.

What the mechanism does for you: a database written by a **newer** ekte is
refused with `DatabaseTooNewError` (both versions named, with what to do)
before anything is written; before the first step of a run, a non-empty
database is copied to `<db>.v<version>.<UTC time>.bak` next to it, and only the
newest 3 backups per database are kept (`dbmigrate.BACKUP_KEEP`); the version
is re-read under the write lock, so the CLI and the server never run the same
step twice.

## Testing

```bash
pytest                       # everything
pytest tests/test_billing.py # one module
pytest -k streaming          # by keyword
pytest -n auto               # in parallel, one worker per CPU (pytest-xdist)
```

- `tests/conftest.py` provides `MockServer`, an OpenAI-compatible endpoint on
  `httpx.MockTransport` with knobs for every divergence ekte hunts for (served
  model, self-identity, context truncation, fake streaming, missing or inflated
  usage, tool calls, JSON mode, …). Every knob defaults to an honest relay.
- Anthropic and Responses clients have their own tests (`test_anthropic.py`,
  `test_responses.py`); the web server is tested through FastAPI's test client
  (`test_web*.py`), including the local-only protections
  (`test_web_security.py`).
- The browser scripts (`lang.js`, `v2/relaycfg.js`, `perf.js`, `secretfield.js`,
  `v2/report.js`, the locales) are evaluated under `node` in
  `test_web_*_js.py` and `test_web_locales.py`; they are skipped without Node.js.
- No test may reach the network.
- `test_cli_startup.py` keeps the CLI fast to start: importing `ekte.cli` must
  not load the HTTP clients, the runner, the knowledge loader, the report
  renderers (ReportLab) or the web server. Import those inside the command that
  needs them.
- `test_filler_perf.py` pins the filler text byte for byte and fails when the
  context-window probe stalls the event loop.
- `tests/a11y/` checks web UI v2 against BITV 2.0 / EN 301 549 / WCAG 2.1 AA
  in a real browser (Playwright + axe-core), in every UI language and both
  themes: `pip install -e '.[web,a11y]' && playwright install chromium`, then
  `pytest -m a11y`. Without Playwright the directory is skipped. What is
  automated and what still needs a manual BITV review is in
  [Accessibility](accessibility.md).
- `EKTE_A11Y_PAGES=history,kb` runs only the a11y tests of those pages (plus
  the checks that span every page); `python -m tests.a11y.affected --base
  origin/main --head HEAD` prints the pages a change affects. Both use one
  mapping, `tests/a11y/pages.py`: a new page is added to its `PAGES` and
  `RULES` ([tests/a11y/README.md](../../tests/a11y/README.md)).

## Security

Report vulnerabilities privately, as described in [SECURITY.md](../SECURITY.md).
In scope are, above all: a key or secret reaching a report, relay-controlled
text injecting markup into a report or the UI, egress to anything but the
configured endpoints, and ways around the web UI's local-only protections.

## License

[Apache-2.0](../../LICENSE)
