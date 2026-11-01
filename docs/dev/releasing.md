# Releases

A release is a version tag; everything else is automated and checked. The
checklist is in the [release checklist](release-checklist.md), the one-time
PyPI setup and the manual fallback in [Publishing to PyPI](publishing.md).

## Cutting a release

1. Work through the [release checklist](release-checklist.md): version and
   changelog, supported Python versions and systems, knowledge-base freshness,
   upgrade fixture, accessibility review for UI changes, docs in all languages,
   security advisories.
2. Set `version` in `pyproject.toml` and rename `[Unreleased]` in `CHANGELOG.md` to
   `[X.Y.Z] - YYYY-MM-DD`. Check locally with
   `python scripts/release_check.py version vX.Y.Z` and `... notes vX.Y.Z`.
3. Merge, then tag the commit and push the tag: `git tag -a vX.Y.Z -m "ekte vX.Y.Z"`,
   `git push origin vX.Y.Z`.
4. `release.yml` first verifies, with `scripts/release_check.py`, that the tag
   equals the package version, that `CHANGELOG.md` has a section for it and that CI
   is green for the tagged commit (it waits for a running CI). If any check fails
   the workflow stops and nothing is published. Then it builds, publishes to PyPI
   via Trusted Publishing with provenance attestations, and creates the GitHub
   Release with the changelog section as its notes.

## Release candidates

Tag `vX.Y.ZrcN` (with `version = "X.Y.ZrcN"` in `pyproject.toml`). PyPI treats it as
a PEP 440 pre-release, so `pip install ekte` ignores it and `pip install --pre ekte`
finds it; GitHub marks the release as "Pre-release". The changelog may use the
`[X.Y.ZrcN]`, the `[X.Y.Z]` or the `[Unreleased]` section.

## If a publish fails halfway

PyPI never accepts the same file twice and a version cannot be reused, so decide by
how far the run got (Actions, "Release to PyPI"):

- **A check failed (verify job).** Nothing was published. Fix the cause (version,
  changelog, CI), delete the tag locally and on origin
  (`git push origin :refs/tags/vX.Y.Z`), and tag the fixed commit again.
- **Build or upload failed before PyPI had the files.** Re-run the failed jobs; no
  version was consumed. If the tagged commit itself must change, delete the tag and
  tag again.
- **PyPI has some of the files** (check <https://pypi.org/project/ekte/#files>). Re-run
  the failed jobs: the upload skips files that already exist. If the files differ
  from what you want to ship, do not retry; yank the version on PyPI and release the
  next one (`X.Y.Z+1` or `rcN+1`).
- **PyPI is complete but the GitHub Release failed.** Re-run the `GitHub Release`
  job; it creates or updates the release idempotently. Or create it by hand with
  `gh release create vX.Y.Z --notes-file <(python scripts/release_check.py notes vX.Y.Z)`.
- **A bad version is already live.** Yank it on PyPI (it stays installable by exact
  pin only), fix forward with a new version and say so in its changelog.
