# Contributing to ekte

Thanks for helping make relay auditing more trustworthy. ekte is a black-box
auditing aid: correctness and **not falsely accusing honest relays** matter more
than catching every possible trick.

Everything you need — principles, development setup, architecture, adding a
detector, editing the knowledge base, translations, tests and pull-request
rules — is in the **[Developer guide](DEVELOPER_GUIDE.md)**
([中文](DEVELOPER_GUIDE.zh-CN.md) · [Français](DEVELOPER_GUIDE.fr.md) ·
[Español](DEVELOPER_GUIDE.es.md) · [Português](DEVELOPER_GUIDE.pt.md) ·
[Italiano](DEVELOPER_GUIDE.it.md) · [Deutsch](DEVELOPER_GUIDE.de.md)).

In short:

```bash
pip install -e '.[dev,web]'
pytest && ruff check ekte tests && mypy ekte
```

- Describe the relay trick or false positive your change addresses.
- Update `CHANGELOG.md` under `[Unreleased]`, and the documentation in every
  language.
- Report security issues privately — see [SECURITY.md](SECURITY.md).

By contributing you agree your contributions are licensed under the project's
[Apache-2.0](LICENSE) license.
