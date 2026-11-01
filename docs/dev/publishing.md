# Publishing ekte to PyPI

Releases are automated by [`.github/workflows/release.yml`](../../.github/workflows/release.yml),
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

The release process, release candidates and what to do when a publish fails
halfway are in [Releases](releasing.md).

## Manual fallback

If you ever need to publish by hand:

```bash
python -m pip install --upgrade build twine
python -m build
twine check dist/*
twine upload dist/*          # needs a PyPI API token
```
