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
- Be kind: this project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
  Conduct reports go privately to the maintainer, the same way as security
  reports.

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

## Documentation in every language

These documents exist in English and in every language listed in
`LANGUAGES` in [`scripts/check_translations.py`](scripts/check_translations.py)
(currently de, es, fr, it, nb, pt, zh-CN):

- `README.md` (`README.<lang>.md`)
- `DEVELOPER_GUIDE.md` (`DEVELOPER_GUIDE.<lang>.md`)
- `docs/METHODOLOGY.md` (`docs/METHODOLOGY.<lang>.md`)

When you change one of them, update every translation in the same pull
request. CI runs `python scripts/check_translations.py` (also covered by
`pytest tests/test_docs_translations.py`). It does not judge wording; it fails
when a translation differs from the English source in heading levels and count,
code blocks and commands, link targets, CLI flags / endpoints / field names in
inline code, `{placeholders}` or version numbers, or when a relative link or an
anchor does not resolve.

If you cannot write a translation, update the English text, copy the changed
structure (headings, code blocks, links) into the translation, and mark the
file as pending by adding this line anywhere in it:

```markdown
<!-- translation-pending: short reason, e.g. "new section needs a translator" -->
```

A pending translation is skipped by the structure comparison, but its links
must still resolve. Say in the pull request which translations are pending, and
remove the marker once the text is translated.

To add a language, create the three translated files and add its code to
`LANGUAGES`; the check then covers it.

By contributing you agree your contributions are licensed under the project's
[Apache-2.0](LICENSE) license.
