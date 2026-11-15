"""The header's version link (ekte/web/changelog.py, caching.stamp_version, nav.js):
the release's CHANGELOG.md on GitHub for an installed package, the checkout's
own CHANGELOG.md (GET /changelog) in a source checkout."""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte.web import caching, changelog  # noqa: E402
from ekte.web.server import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_HEADER = re.compile(r'<header class="znav" data-page="([^"]*)" data-version="([^"]*)" data-changelog="([^"]*)">')


def _checkout(tmp_path: Path, version: str = "1.2.3") -> Path:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "ekte"\nversion = "{version}"\n', "utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n- not committed yet\n", "utf-8")
    return tmp_path


@pytest.fixture
def fresh_pages(monkeypatch):
    # rendered pages are cached per process; these tests change what is stamped
    monkeypatch.setattr(caching, "_pages", {})


# ----- installed package vs source checkout -------------------------------- #
def test_installed_package_links_to_its_release_on_github(tmp_path):
    # site-packages: no CHANGELOG.md / pyproject.toml beside the package
    assert changelog.source_changelog(tmp_path) is None
    assert changelog.version_label(tmp_path, "0.34.0") == "v0.34.0"
    assert changelog.changelog_url(tmp_path, "0.34.0") == (
        "https://github.com/mn567250/ekte/blob/v0.34.0/CHANGELOG.md"
    )


def test_a_changelog_alone_is_no_checkout(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", "utf-8")
    assert changelog.source_changelog(tmp_path) is None


def test_source_checkout_links_to_its_own_changelog(tmp_path):
    root = _checkout(tmp_path)
    assert changelog.source_changelog(root) == root / "CHANGELOG.md"
    # an editable install reports the released version: marked +dev
    assert changelog.version_label(root, "1.2.3") == "v1.2.3+dev"
    assert changelog.changelog_url(root, "1.2.3") == changelog.ROUTE == "/changelog"


def test_source_tree_without_install_takes_the_pyproject_version(tmp_path):
    root = _checkout(tmp_path, "0.35.0")
    assert changelog.version_label(root, "0.0.0+unknown") == "v0.35.0+dev"
    (root / "pyproject.toml").write_text("not toml [", "utf-8")
    assert changelog.version_label(root, "0.0.0+unknown") == "v0.0.0+unknown"


def test_this_checkout_is_detected():
    # the tests run from the source tree
    assert changelog.source_changelog() == ROOT / "CHANGELOG.md"
    assert changelog.version_label().endswith("+dev")


# ----- the pages ------------------------------------------------------------ #
@pytest.mark.parametrize("path", ["/", "/history", "/watches", "/analytics", "/kb", "/accessibility"])
def test_every_page_carries_the_version_and_its_link(path, fresh_pages):
    r = TestClient(create_app(), base_url="http://localhost").get(path)
    m = _HEADER.search(r.text)
    assert m, path
    assert html.unescape(m[2]) == changelog.version_label()
    assert html.unescape(m[3]) == changelog.changelog_url()


def test_installed_package_pages_link_to_github(monkeypatch, tmp_path, fresh_pages):
    monkeypatch.setattr(changelog, "_ROOT", tmp_path)
    monkeypatch.setattr("ekte.__version__", "0.34.0")
    client = TestClient(create_app(), base_url="http://localhost")
    m = _HEADER.search(client.get("/").text)
    assert m and m[2] == "v0.34.0"
    assert html.unescape(m[3]) == "https://github.com/mn567250/ekte/blob/v0.34.0/CHANGELOG.md"
    # no route serves a changelog: the address is an unknown page (the audit page)
    r = client.get("/changelog")
    assert "text/plain" not in r.headers["content-type"] and "## [Unreleased]" not in r.text


def test_checkout_serves_its_changelog_as_it_is_on_disk(monkeypatch, tmp_path, fresh_pages):
    root = _checkout(tmp_path)
    monkeypatch.setattr(changelog, "_ROOT", root)
    client = TestClient(create_app(), base_url="http://localhost")
    m = _HEADER.search(client.get("/history").text)
    assert m and m[2].endswith("+dev") and m[3] == "/changelog"
    r = client.get("/changelog")
    assert r.status_code == 200 and r.headers["content-type"] == "text/plain; charset=utf-8"
    assert r.headers["cache-control"] == "no-cache"
    assert "- not committed yet" in r.text
    # an uncommitted edit shows up on the next request
    (root / "CHANGELOG.md").write_text("# Changelog\n\n- edited just now\n", "utf-8")
    assert "- edited just now" in client.get("/changelog").text


def test_changelog_route_is_local_only(monkeypatch, tmp_path):
    monkeypatch.setattr(changelog, "_ROOT", _checkout(tmp_path))
    client = TestClient(create_app(), base_url="http://evil.example")
    assert client.get("/changelog").status_code != 200


# ----- nav.js ---------------------------------------------------------------- #
def test_nav_renders_the_version_link_from_the_header():
    src = (ROOT / "ekte" / "web" / "static" / "v2" / "nav.js").read_text("utf-8")
    assert 'header.getAttribute("data-version")' in src
    assert 'header.getAttribute("data-changelog")' in src
    # first in .tail; accessible name = visible version + hidden "Changelog"
    assert "'<div class=\"tail\">' + versionLink +" in src
    assert '<span class="sr-only" data-en="Changelog">Changelog</span>' in src


def test_changelog_label_is_translated():
    from ekte import i18n

    langs = i18n._load()
    assert len(langs) >= 8
    for code, data in langs.items():
        assert data["strings"].get("Changelog"), code
    assert langs["de"]["strings"]["Changelog"] != "Changelog"
