# Accessibility tests of web UI v2

The browser suite in this directory (`pytest tests/a11y -m a11y`) checks web UI
v2 against BITV 2.0 / EN 301 549 / WCAG 2.1 A+AA. What it covers and how is
described in [docs/ACCESSIBILITY.md](../../docs/ACCESSIBILITY.md).

## Testing some pages

```sh
ZING_A11Y_PAGES=history pytest tests/a11y -m a11y -n auto        # History only
ZING_A11Y_PAGES=tools,kb pytest tests/a11y -m a11y --collect-only -q
```

`ZING_A11Y_PAGES` is a comma list of page ids (`PAGES` in `pages.py`: `audit`,
`history`, `monitors`, `tools`, `kb`, `accessibility`), or `all`; an unknown
id is a usage error. A test runs when it is tied to a selected page:

- tests parametrised by `page_id`, or by a `state` such as `history-charts` or
  `kb+expanded` (`test_time_media.py`): by that page;
- tests that open fixed pages (the History-only files, the flows, the
  colour-state checks): by their entry in `TEST_PAGES` in `pages.py`;
- everything else (the checks that compare every page: consistent navigation
  and identification, page titles, reachability; the self-checks) always runs.

It combines with `ZING_A11Y_SHARD=k/n`, which then splits the selection.
Collected with `ZING_A11Y_PAGES=<page>` (1,122 tests in all; 33 of them, 4 %
of the test time, run with any selection), and each page's share of a full
run's test time (`WEIGHTS` in `pages.py`):

| Page | Tests | Share of the run time |
|---|---:|---:|
| audit | 213 | 15 % |
| history | 234 | 21 % |
| monitors | 212 | 10 % |
| tools | 206 | 10 % |
| kb | 199 | 29 % |
| accessibility | 197 | 12 % |

## Which pages a change affects

```sh
python -m tests.a11y.affected --base origin/main --head HEAD
# {"pages": ["history"], "full": false, "reason": "zing/web/static/v2/history.html -> history"}
python -m tests.a11y.affected --files zing/web/static/v2/nav.js
# {"pages": ["audit", …, "accessibility"], "full": true, "reason": "zing/web/static/v2/nav.js affects every page"}
```

`affected.py` (standard library only) diffs the two commits from their merge
base, or takes `--files` (`-` reads stdin), and maps every changed file through
`RULES` in `pages.py`; the first matching glob decides. Each page's HTML and
the scripts and styles only it loads select that page; assets loaded by some
pages select those (`report.js`: audit and History); files every page uses
(`nav.js`, `zing.css`, `theme.js`, `i18n.js`, the locales, `server.py`, this
directory, `ci.yml`, `pyproject.toml`, `uv.lock`, the seeded report fixture)
select all of them. The audit pipeline (`zing/detectors/`, `zing/runner.py`,
`zing/clients/`, `zing/scoring.py`, `zing/report/`) selects the audit page:
its flow runs a real audit against a fake relay and renders the report.
Other files outside the web UI (docs, other tests, the CLI) select none. **Fail-safe:** a file under `zing/web/`, `zing/i18n/` or
`tests/a11y/` that no rule matches selects everything, and so does a failing
`git diff`.

`full` means every page; only such a run builds the BITV conformance report.

In CI the `accessibility scope` job runs it on pull requests; pushes (to
`main` and the integration branches), the nightly run (03:17 UTC) and manual
runs test every page. A full run is four round-robin
shards; a partial run gets one to four jobs by the summed weight of its pages
(`WEIGHTS`, `job_count` in `pages.py`), each running the whole selection with
`ZING_A11Y_SHARD=k/n`, so the jobs stay even however large a page is.

**Keeping the mapping right.** A new page is added to `PAGES` (the harness and
every `page_id` test pick it up) and gets rules for its HTML and its own
assets in `RULES`. A new test that opens one fixed page without a `page_id`
parameter gets a `TEST_PAGES` entry (unmapped, it simply always runs). A new
asset shared by several pages gets a rule naming them (unmapped, it runs
everything). `tests/test_a11y_pages.py` checks the tables against the sources:
every file under `zing/web/`, `zing/i18n/` and `tests/a11y/` has a rule, every
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

`llm_review.py` asks Claude for a second opinion on these. It starts the app as
the suite does, opens every v2 page in every UI language (all disclosures
open), extracts the title, headings, links (name, target, context), control
names, form labels/placeholders/descriptions, image alternatives, visible
instruction sentences and the error/status messages shown after submitting
each visible form empty, and sends that as compact JSON with a fixed rubric to
the Messages API (one request per page and language, plus one translation
comparison per page).

```sh
pip install -e '.[web,a11y]' && playwright install chromium
export ANTHROPIC_API_KEY=...
python -m tests.a11y.llm_review --out a11y-llm-review.json
```

Options: `--pages audit,kb`, `--langs en,de`, `--effort high`, `--max-requests 60`
and `--max-cost 10` (USD, estimated from the reported token usage; the run stops
sending once either limit is reached), `--dry-run` (collect the page data and
build the requests without calling the API; no key needed).

The output looks like:

```json
{"generated_at": "…", "model": "claude-opus-5-5",
 "pages": [{"task": "page", "page": "audit", "lang": "en", "status": "reviewed", "findings": 1, "data": {…}}, …],
 "steps": {"9.3.3.3": {"verdict": "issues",
                       "findings": [{"page": "…", "lang": "…", "element": "…", "problem": "…", "suggestion": "…"}]}, …}}
```

`verdict` is `ok`, `issues`, or `not-reviewed` (no answer was received for
that step, e.g. in a dry run).

**This is advisory.** The findings are a model's opinion for a human tester to
confirm or reject; they are not test results and do not decide any BITV step.
The script never asserts and always exits 0. Without `ANTHROPIC_API_KEY` it
prints a notice and does nothing.

Notes:

- Model: `claude-opus-5-5`. It accepts no sampling parameters
  (`temperature` is rejected), so results can vary slightly between runs; the
  fixed rubric, sorted input and a JSON-schema-constrained answer
  (`output_config.format`) keep them as stable as possible.
- The rubric is the system prompt and is prompt-cached, so only the first
  request pays for it in full.
- Retries: 408/409/429/5xx/529 and network errors, with exponential backoff
  (honours `retry-after`). Refusals are re-run on Anthropic's recommended
  fallback model (`fallbacks: "default"`); a remaining refusal is recorded as an
  error for that page.
- Only the standard library, httpx and Playwright are used (no SDK).
- The pure parts (compaction, request building, response parsing, client
  retries, cost guard) are tested offline in `tests/test_a11y_llm_review.py`.
- In CI the informational a11y job runs it only when the `ANTHROPIC_API_KEY`
  secret is set and uploads `a11y-llm-review.json`.
