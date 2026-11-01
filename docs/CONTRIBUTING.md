# Contributing to ekte

Thanks for helping make relay auditing more trustworthy. ekte is a black-box
auditing aid: correctness and **not falsely accusing honest relays** matter more
than catching every possible trick.

Everything you need — principles, development setup, architecture, adding a
detector, editing the knowledge base, translations, tests and pull-request
rules — is in the **[Developer guide](dev/developer-guide.md)** and the
documents it links to.

In short:

```bash
pip install -e '.[dev,web]'
pytest && ruff check ekte tests && mypy ekte
```

- Describe the relay trick or false positive your change addresses.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Update the documentation the change touches: the README and the user guide
  in every language, see [Translations](dev/translations.md#documentation).
- Dependency updates and accepted advisories: see
  [Continuous integration](dev/ci.md#dependency-updates-and-vulnerability-checks).
- No coding needed to help with accessibility: a manual review of the web UI,
  with or without a screen reader, is welcome. ekte 1.0.0 has none yet; the
  [worksheet and how to fill it in](dev/accessibility.md#contributing-a-review)
  are ready; coordinate in [#67](https://github.com/mn567250/ekte/issues/67).
- Report security issues privately — see the [Security policy](SECURITY.md).
- Be kind: this project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
  Conduct reports go privately to the maintainer, the same way as security
  reports.

By contributing you agree your contributions are licensed under the project's
[Apache-2.0](../LICENSE) license.
