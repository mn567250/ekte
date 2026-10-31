# Release checklist

Copy this list into the release tracking issue or PR and tick every item before
you create the tag. The workflow ([`release.yml`](../.github/workflows/release.yml))
re-checks the first three automated items and stops without publishing if one
fails; everything else depends on you. Process and recovery:
[Developer guide, Releases](../DEVELOPER_GUIDE.md#releases) and
[PUBLISHING.md](PUBLISHING.md).

## Version and changelog

- [ ] `version` in `pyproject.toml` is the release version (PEP 440: `X.Y.Z`, or
      `X.Y.ZrcN` for a release candidate).
- [ ] `CHANGELOG.md`: `[Unreleased]` is renamed to `[X.Y.Z] - YYYY-MM-DD` and a fresh,
      empty `[Unreleased]` sits above it. The section reads well as release notes:
      it becomes the GitHub Release text.
- [ ] `python scripts/release_check.py version vX.Y.Z` and
      `python scripts/release_check.py notes vX.Y.Z` succeed locally.
- [ ] The pinned action version in the READMEs and `docs/CI.md` is updated (final releases).

## Supported Python versions and systems

- [ ] The supported Python versions follow the [stability policy](STABILITY.md#python)
      (every CPython that is not end-of-life): `requires-python`, the classifiers, the
      CI matrix and the docs name the same versions (`tests/test_python_versions.py`
      checks the first three).
- [ ] The documented supported systems (README, `docs/`) are still true; a new or
      dropped Python version or operating system is in the changelog.
- [ ] CI is green on the commit you will tag (tests on every supported Python on Linux and on the oldest
      and newest on macOS and Windows, lint, type check, build).

## Knowledge base

- [ ] Profiles in `ekte/knowledge/data/` cover the providers' current models; changed
      numeric values cite an official source (see "Editing the knowledge base" in the
      developer guide).
- [ ] `ekte kb-import --check` passes for the shipped data, the knowledge-base tests
      pass and the wheel installs and loads the knowledge base.
- [ ] Every profile's `last_verified` is the date of this release's review ("Keeping the
      knowledge base current" in the developer guide), so `ekte kb` shows no stale warning.

## Upgrade fixture

- [ ] An upgrade fixture exists for the new version: run
      `python scripts/make_upgrade_fixture.py <version>` after the release is on PyPI
      (it runs that release and writes `tests/fixtures/upgrade/v<version>/`: history,
      monitors with stored and unstored keys, your own knowledge-base entries), commit
      the result, and `tests/test_upgrade_fixtures.py` opens it with the current code
      without loss. Never put real keys or data in a fixture.
- [ ] If the on-disk format changed, the migration and its test are in the changelog.

## Accessibility (UI changes)

- [ ] If the web UI changed since the last release: the accessibility suite was run on
      all pages and its findings reviewed; no new serious findings are left unexplained.
- [ ] The conformance report and `a11y-llm-review.json` are current for the changed pages
      (the nightly and manual CI runs produce the conformance report).
- [ ] Keyboard use and screen-reader labels of new or changed controls were checked by hand.
- [ ] The steps in [ACCESSIBILITY.md, Manual review](ACCESSIBILITY.md#manual-review) that
      the change touches were repeated by a person and recorded there. A step nobody
      performed stays "manual review pending"; a script run does not tick this item.

## Documentation in all languages

- [ ] `README`, `DEVELOPER_GUIDE` and the web UI strings are updated in **every**
      language (`de`, `es`, `fr`, `it`, `nb`, `pt`, `zh-CN`) with identical structure.
- [ ] New CLI flags, endpoints and settings are documented.

## Security

- [ ] No open security advisory or private report is pending for the release
      (GitHub: Security, Advisories). A fix is released first or together.
- [ ] Dependencies were checked for known vulnerabilities; `uv.lock` is current.
- [ ] `SECURITY.md` is still accurate for this release.

## Tag and verify

- [ ] Tag the verified commit: `git tag -a vX.Y.Z -m "ekte vX.Y.Z"` and
      `git push origin vX.Y.Z` (a release candidate: `vX.Y.ZrcN`).
- [ ] Approve the `pypi` environment if required reviewers are configured.
- [ ] After the run: the package is on PyPI with its attestations, the GitHub Release
      exists (marked "Pre-release" for a release candidate) with the changelog text,
      and `pip install ekte==X.Y.Z` works in a clean environment.
