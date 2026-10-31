# Publishing ekte to PyPI

Releases are automated by [`.github/workflows/release.yml`](../.github/workflows/release.yml),
which verifies the release, builds the wheel + sdist and publishes them to PyPI via
**Trusted Publishing (OIDC)** — no API token is stored as a repository secret.

## One-time setup (PyPI side)

Before the first release, register a *pending publisher* so PyPI trusts this repo:

1. Sign in to PyPI and open **Account settings → Publishing → Add a pending publisher**
   (<https://pypi.org/manage/account/publishing/>).
2. Fill in:
   - **PyPI project name:** `ekte`
   - **Owner:** `mn567250`
   - **Repository name:** `ekte`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`
3. (Recommended) In the GitHub repo, create an **Environment** named `pypi`
   (Settings → Environments) and optionally add required reviewers so a human
   approves each publish. Also restrict the environment's deployment branches
   and tags to `v*`, and set the same environment name on the PyPI publisher.
   Only the `publish` job requests an OIDC token (`id-token: write`); every other
   job has read-only (or, for the GitHub Release, `contents: write`) permissions.

After the first successful publish, `ekte` becomes a normal Trusted Publisher
and the pending entry is consumed.

The publish job runs only in `mn567250/ekte` (`if: github.repository == …`), so a
fork or mirror that pushes a `v*` tag never publishes. While no release is planned,
the workflow can stay disabled (**Actions → Release to PyPI → ⋯ → Disable workflow**);
enable it again before pushing a release tag.

## Cutting a release

Work through the [release checklist](RELEASE_CHECKLIST.md), then:

1. Bump `version` in [`pyproject.toml`](../pyproject.toml) and rename `[Unreleased]` in
   [`CHANGELOG.md`](../CHANGELOG.md) to `[X.Y.Z] - YYYY-MM-DD`.
2. Merge, then tag the commit and push the tag:
   ```bash
   git tag -a vX.Y.Z -m "ekte vX.Y.Z"
   git push origin vX.Y.Z
   ```
   For a release candidate use `X.Y.ZrcN` in `pyproject.toml` and `vX.Y.ZrcN` as the tag.
3. The `Release to PyPI` workflow then:
   - **verifies** (`scripts/release_check.py`) that the tag equals the package
     version, `CHANGELOG.md` has a section for it and CI is green for the tagged
     commit; if any check fails it stops and publishes nothing;
   - builds, runs `twine check` and publishes to PyPI with provenance attestations
     (PEP 740, Trusted Publishing);
   - creates the GitHub Release with the changelog section as notes, marked
     "Pre-release" for `rcN` versions.

If a publish fails halfway, see "If a publish fails halfway" in the
[developer guide](../DEVELOPER_GUIDE.md#releases). Check locally before tagging with
`python scripts/release_check.py version vX.Y.Z` and `... notes vX.Y.Z`.

## Manual fallback

If you ever need to publish by hand:

```bash
python -m pip install --upgrade build twine
python -m build
twine check dist/*
twine upload dist/*          # needs a PyPI API token
```
