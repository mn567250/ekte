# Continuous integration

| Workflow | Runs | Does |
|---|---|---|
| `.github/workflows/ci.yml` | push and pull request to `main` (and the integration branches `*/integration`); nightly and manual (accessibility only) | `ruff`, `mypy` and `pytest` on Python 3.11–3.14 (Linux; on macOS and Windows 3.11 and 3.14) with the `dev` and `web` extras; builds the wheel and sdist and checks that the wheel installs and loads the knowledge base; runs the accessibility suite (informational, never fails the run) and uploads its findings: every page on pushes, the nightly and manual runs (with the BITV conformance report), on pull requests only the pages the change affects (none for docs-only changes) — except on pull requests into `perf/integration`, where the slow browser suite is skipped (it runs on that branch's pushes and on its pull request into `main`) |
| `.github/workflows/release.yml` | a `v*` tag | builds, runs `twine check` and publishes to PyPI (Trusted Publishing) |
| `.github/workflows/example-audit.yml` | daily schedule, manual | example of a scheduled relay audit with the action |
| `.github/workflows/docs.yml` | push and pull request | `scripts/check_translations.py`: the translations of the user documentation have not drifted (see [Translations](translations.md#documentation)) |
| `.github/workflows/dist.yml` | push and pull request | builds the wheel and sdist, checks their contents and that PyPI can render the package description (see below) |
| `.github/workflows/security.yml` | push and pull request, nightly | `pip-audit` of the locked dependencies (see below) |

The composite action itself is `action.yml`, documented in the user guide's
[GitHub Action](../guide/github-action.md) page.

## Dependency updates and vulnerability checks

- **Updates.** Dependabot (`.github/dependabot.yml`) opens one grouped pull
  request per week for the Python dependencies (it only refreshes `uv.lock`)
  and one for GitHub Actions. Ranges in `pyproject.toml` stay open; the
  lockfile pins the tested set.
- **Vulnerabilities.** The `Security` workflow exports `uv.lock` and runs
  `pip-audit` on pull requests, pushes to `main` and nightly. Run it locally
  with `pip install uv pip-audit && python scripts/check_vulnerabilities.py`.
- **Accepting an advisory.** If a reviewed advisory does not affect ekte, add
  an entry to `.github/vulnerability-ignores.yml` with `id`, `reason` and
  `expires` (`YYYY-MM-DD`). The check fails again after the expiry date, and
  entries missing a field are rejected. Prefer upgrading the lockfile.

## Third-party files in the distribution

The source distribution contains the tests but no vendored third-party files. `tests/a11y/vendor/axe.min.js` (axe-core, MPL-2.0) is in the git repository only; it is excluded from the sdist (`exclude` under `[tool.hatch.build.targets.sdist]` in `pyproject.toml`) and was never part of the wheel.

- Tests that need an excluded file skip with a clear reason when it is absent; run the accessibility suite from a git checkout.
- `NOTICE` lists every third-party file and says whether it is distributed. Add a new vendored file to the `exclude` list and to `NOTICE`, or, if it must ship, state in `NOTICE` that it does.
- `scripts/check_dist_contents.py` builds the wheel and the sdist (`uv build`) and fails if an excluded file, or a file that `NOTICE` lists as not distributed, is present. The `.github/workflows/dist.yml` workflow runs it in a separate job.
