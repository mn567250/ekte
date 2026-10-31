# Contributing to ekte

Thanks for helping make relay auditing more trustworthy. ekte is a black-box
auditing aid: correctness and **not falsely accusing honest relays** matter more
than catching every possible trick.

Everything you need — principles, development setup, architecture, adding a
detector, editing the knowledge base, translations, tests and pull-request
rules — is in the **[Developer guide](DEVELOPER_GUIDE.md)**
([中文](DEVELOPER_GUIDE.zh-CN.md) · [Français](DEVELOPER_GUIDE.fr.md) ·
[Español](DEVELOPER_GUIDE.es.md) · [Português](DEVELOPER_GUIDE.pt.md) ·
[Italiano](DEVELOPER_GUIDE.it.md) · [Deutsch](DEVELOPER_GUIDE.de.md) ·
[Norsk](DEVELOPER_GUIDE.nb.md)).

In short:

```bash
pip install -e '.[dev,web]'
pytest && ruff check ekte tests && mypy ekte
```

- Describe the relay trick or false positive your change addresses.
- Update `CHANGELOG.md` under `[Unreleased]`, and the documentation in every
  language.
- Report security issues privately — see [SECURITY.md](SECURITY.md).

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

By contributing you agree your contributions are licensed under the project's
[Apache-2.0](LICENSE) license.
