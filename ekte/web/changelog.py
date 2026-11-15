"""The running ekte version and where its changelog is: the header's version link.

* **Installed package** (a wheel, e.g. from PyPI): the label is ``v<version>``,
  the link ``CHANGELOG.md`` on GitHub at the release tag ``v<version>``. The
  wheel ships no changelog of its own.
* **Source checkout** (an editable install such as ``uv sync``, or ekte run
  from the source tree): the label is ``v<version>+dev``, the link
  :data:`ROUTE`, which serves the checkout's own ``CHANGELOG.md``. An editable
  install reports the released version number while it runs the code on disk,
  ``[Unreleased]`` and uncommitted changes included; only the local file
  describes that code. The server answers only local clients
  (:mod:`ekte.web.security`), so the file never leaves the machine.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import ekte

REPO_URL = "https://github.com/mn567250/ekte"
# Served only in a source checkout (create_app); an installed package has no
# such route.
ROUTE = "/changelog"

# ekte/web/changelog.py -> the directory that holds the ekte package: the
# checkout's root, or site-packages for an installed wheel.
_ROOT = Path(__file__).resolve().parents[2]


def source_changelog(root: Path | None = None) -> Path | None:
    """The ``CHANGELOG.md`` of the source checkout ekte runs from, or None for
    an installed package (no ``CHANGELOG.md`` and ``pyproject.toml`` beside the
    ``ekte`` package)."""
    root = root or _ROOT
    path = root / "CHANGELOG.md"
    return path if path.is_file() and (root / "pyproject.toml").is_file() else None


def _source_version(root: Path) -> str | None:
    """The ``version`` in the checkout's ``pyproject.toml``, or None."""
    try:
        with (root / "pyproject.toml").open("rb") as f:
            version = tomllib.load(f).get("project", {}).get("version")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return version if isinstance(version, str) and version else None


def version_label(root: Path | None = None, version: str | None = None) -> str:
    """The version the header shows: ``v0.34.0``, or ``v0.34.0+dev`` in a
    source checkout (whose version without an install is ``0.0.0+unknown``:
    then the one in ``pyproject.toml``)."""
    root, version = root or _ROOT, version or ekte.__version__
    if source_changelog(root) is None:
        return f"v{version}"
    if "+" in version:
        version = _source_version(root) or version
    return f"v{version}" if "+" in version else f"v{version}+dev"


def changelog_url(root: Path | None = None, version: str | None = None) -> str:
    """Where the header's version link points (see the module docstring)."""
    if source_changelog(root) is not None:
        return ROUTE
    return f"{REPO_URL}/blob/v{version or ekte.__version__}/CHANGELOG.md"
