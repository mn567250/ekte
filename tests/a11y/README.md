# Accessibility tests of web UI v2

The browser suite in this directory (`pytest tests/a11y -m a11y`) checks web UI
v2 against BITV 2.0 / EN 301 549 / WCAG 2.1 A+AA. What it covers and how is
described in [docs/ACCESSIBILITY.md](../../docs/ACCESSIBILITY.md).

## Testing some pages

```sh
EKTE_A11Y_PAGES=history pytest tests/a11y -m a11y -n auto        # History only
EKTE_A11Y_PAGES=audit,kb pytest tests/a11y -m a11y --collect-only -q
```

`EKTE_A11Y_PAGES` is a comma list of page ids (`PAGES` in `pages.py`: `audit`,
`history`, `monitors`, `kb`, `analytics`, `accessibility`), or `all`; an unknown
id is a usage error. A test runs when it is tied to a selected page:

- tests parametrised by `page_id`, or by a `state` such as `history-charts` or
  `kb+expanded` (`test_time_media.py`): by that page;
- tests that open fixed pages (the History-only files, the flows, the
  colour-state checks): by their entry in `TEST_PAGES` in `pages.py`;
- everything else (the checks that compare every page: consistent navigation
  and identification, page titles, reachability; the self-checks) always runs.

It combines with `EKTE_A11Y_SHARD=k/n`, which then splits the selection.
Collected with `EKTE_A11Y_PAGES=<page>` (1,277 tests in all; 37 of them, 4 %
of the test time, run with any selection), and each page's share of a full
run's test time (`WEIGHTS` in `pages.py`):

| Page | Tests | Share of the run time |
|---|---:|---:|
| audit | 276 | 20 % |
| history | 260 | 24 % |
| monitors | 244 | 9 % |
| kb | 229 | 23 % |
| analytics | 236 | 10 % |
| accessibility | 227 | 10 % |

## Which pages a change affects

```sh
python -m tests.a11y.affected --base origin/main --head HEAD
# {"pages": ["history"], "full": false, "reason": "ekte/web/static/v2/history.html -> history"}
python -m tests.a11y.affected --files ekte/web/static/v2/nav.js
# {"pages": ["audit", …, "accessibility"], "full": true, "reason": "ekte/web/static/v2/nav.js affects every page"}
```

`affected.py` (standard library only) diffs the two commits from their merge
base, or takes `--files` (`-` reads stdin), and maps every changed file through
`RULES` in `pages.py`; the first matching glob decides. Each page's HTML and
the scripts and styles only it loads select that page; assets loaded by some
pages select those (`report.js`: audit and History); files every page uses
(`nav.js`, `ekte.css`, `theme.js`, `i18n.js`, the locales, `server.py`, this
directory, `ci.yml`, `pyproject.toml`, `uv.lock`, the seeded report fixture)
select all of them. The audit pipeline (`ekte/detectors/`, `ekte/runner.py`,
`ekte/clients/`, `ekte/scoring.py`, `ekte/report/`) selects the audit page:
its flow runs a real audit against a fake relay and renders the report.
Other files outside the web UI (docs, other tests, the CLI) select none. **Fail-safe:** a file under `ekte/web/`, `ekte/i18n/` or
`tests/a11y/` that no rule matches selects everything, and so does a failing
`git diff`.

`full` means every page; only such a run builds the BITV conformance report.

In CI the `accessibility scope` job runs it on pull requests; pushes (to
`main` and the integration branches), the nightly run (03:17 UTC) and manual
runs test every page. A full run is four round-robin
shards; a partial run gets one to four jobs by the summed weight of its pages
(`WEIGHTS`, `job_count` in `pages.py`), each running the whole selection with
`EKTE_A11Y_SHARD=k/n`, so the jobs stay even however large a page is.

**Keeping the mapping right.** A new page is added to `PAGES` (the harness and
every `page_id` test pick it up) and gets rules for its HTML and its own
assets in `RULES`. A new test that opens one fixed page without a `page_id`
parameter gets a `TEST_PAGES` entry (unmapped, it simply always runs). A new
asset shared by several pages gets a rule naming them (unmapped, it runs
everything). `tests/test_a11y_pages.py` checks the tables against the sources:
every file under `ekte/web/`, `ekte/i18n/` and `tests/a11y/` has a rule, every
`<script>`/`<link>` of a page is mapped to that page, `TEST_PAGES` entries name
every page their test opens, and a narrowed locale fragment is used on no
other page. Locale fragments re-declare shared strings ("Cancel", "API key"),
so most of them select every page.

## Optional LLM review (advisory)

Some test steps depend on what a text *means*, which a browser cannot decide:

| Step | Question |
|---|---|
| 9.1.1.1 | Does a text alternative describe the image's purpose? |
| 9.1.3.3 | Do instructions rely only on shape, colour, size, position or sound? |
| 9.2.4.4 | Is a link's purpose clear from its name and context? |
| 9.2.4.6 | Do headings and labels describe their topic or purpose? |
| 9.3.3.2 | Are labels and instructions sufficient? |
| 9.3.3.3 | Do error messages say how to correct the input? |
| translation | Does a translation change the meaning compared with English? |

`llm_review.py` asks an LLM (Claude by default) for an opinion on these. It
starts the app as the suite does, opens every v2 page in every UI language
(all disclosures open), extracts the title, headings, links (name, target,
context), control names and descriptions, form labels/placeholders/descriptions, image
alternatives, visible instruction sentences and the error/status messages
shown after submitting each visible form empty, and sends that as compact JSON
with a fixed rubric (one request per page and language, plus one translation
comparison per page).

```sh
pip install -e '.[web,a11y]' && playwright install chromium
export ANTHROPIC_API_KEY=...
python -m tests.a11y.llm_review --out a11y-llm-review.json

# a local model (Ollama, LM Studio, vLLM): no key, no cost
python -m tests.a11y.llm_review --base-url http://localhost:11434/v1 --model qwen3

# the endpoint of an audit configuration (judge, else baseline, else target)
python -m tests.a11y.llm_review --config ekte.yaml
```

**Endpoint.** Each of `--base-url`, `--api-key` (raw, `env:VAR` or
`file:/path`), `--model` and `--api` (`auto`, `anthropic`, `openai`) is
optional. A missing one is taken from the ekte configuration (`--config`,
default `./ekte.yaml` when it exists): its `judge` endpoint, else `baseline`,
else `target`, the same order ekte's own judge uses. Then from
`ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY`, then the defaults (the Anthropic
API, `claude-opus-5-5`). A key or model is only taken from the source that
gave the URL, so a configured key is never sent to another host; a URL that is
neither configured nor Anthropic's needs `--model`. The protocol is detected
like an audit target's (`ekte.clients.detect_api`): the Anthropic Messages API
or OpenAI-compatible chat completions (structured output via
`response_format`, falling back to JSON mode on servers without it; `<think>`
blocks and code fences in the answer are ignored). A local or private-network
endpoint needs no key and is costed at zero.

Other options: `--pages audit,kb`, `--langs en,de`, `--effort high`
(Anthropic only), `--max-requests 60` and `--max-cost 10` (USD, estimated from
the reported token usage; the run stops sending once either limit is reached),
`--dry-run` (collect the page data and build the requests without calling the
API; no key needed).

The output looks like:

```json
{"generated_at": "…", "model": "claude-opus-5-5",
 "pages": [{"task": "page", "page": "audit", "lang": "en", "status": "reviewed", "findings": 1, "data": {…}}, …],
 "steps": {"9.3.3.3": {"verdict": "issues",
                       "findings": [{"page": "…", "lang": "…", "element": "…", "problem": "…", "suggestion": "…"}]}, …}}
```

`verdict` is `ok`, `issues`, `partial` (some requests failed) or
`not-reviewed` (no answer was received for that step, e.g. in a dry run). The
report also names the endpoint (`base_url`, `api`, where it came from; never
the key) and the pages and languages it reviewed.

**In the accessibility report.** `python -m tests.a11y.conformance` picks up
`./a11y-llm-review.json` (or `--llm <file>`; `--no-llm` ignores it) and counts
a completed review as the manual part of the steps it covers: a step whose
automated part passed becomes **pass** when the review found nothing and
**fail** when it found an issue; the report records a manual review and
`/accessibility` names the model. A review that was skipped, failed, a dry
run, or covered fewer pages or languages than were tested changes nothing, and
without the file the report is built as before. The script itself never
asserts and always exits 0; without a key for a remote endpoint it prints a
notice and writes a `skipped` report.

**Review and update the report in one command.** The page shows
`ekte/web/static/v2/bitv-report.json`; the review file alone does not change
it. `--update-report` applies the finished review to that report right away
(another path can follow the option):

```sh
python -m tests.a11y.llm_review --base-url http://localhost:1234/v1 --model liquid/lfm2-24b-a2b --update-report
# or build the report afresh from a suite run's results instead of updating it
python -m tests.a11y.llm_review --update-report --results a11y-results.json
```

Each step of the report keeps its status from the tests alone
(`status_tests`), so a new review replaces the previous one instead of adding
to it. A dry run or a failed review leaves the report unchanged. Without
running a new review, `python -m tests.a11y.conformance --update
ekte/web/static/v2/bitv-report.json --llm a11y-llm-review.json` applies an
existing review file (`--no-llm` removes it again).

Notes:

- Default model: `claude-opus-5-5`. It accepts no sampling parameters
  (`temperature` is rejected), so results can vary slightly between runs; the
  fixed rubric, sorted input and a JSON-schema-constrained answer
  (`output_config.format`) keep them as stable as possible.
- The rubric is the system prompt and is prompt-cached, so only the first
  request pays for it in full.
- Retries: 408/409/429/5xx/529 and network errors, with exponential backoff
  (honours `retry-after`). On the Anthropic API, refusals are re-run on
  Anthropic's recommended fallback model (`fallbacks: "default"`; not asked of
  other hosts); a remaining refusal is recorded as an error for that page.
- Only the standard library, httpx and Playwright are used (no SDK).
- The pure parts (compaction, request building, response parsing, client
  retries, cost guard) are tested offline in `tests/test_a11y_llm_review.py`.
- In CI the accessibility report job runs it only when the
  `ANTHROPIC_API_KEY` secret is set, before building the conformance report,
  and uploads `a11y-llm-review.json`.
