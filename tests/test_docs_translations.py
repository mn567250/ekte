"""The documentation translations must not drift structurally (issue #31)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_translations", ROOT / "scripts" / "check_translations.py"
)
assert _spec and _spec.loader
ct = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ct)

SOURCE = """# Title

Intro with `--flag` and version 1.2.3, see [guide](GUIDE.md) and [below](#usage).

## Usage

```bash
ekte check --model gpt-4o
```

## Limits

Set `{name}` carefully.
"""


def _tree(tmp_path: Path, translation: str) -> Path:
    (tmp_path / "DOC.md").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "GUIDE.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / "GUIDE.de.md").write_text("# Anleitung\n", encoding="utf-8")
    (tmp_path / "DOC.de.md").write_text(translation, encoding="utf-8")
    return tmp_path


def _run(root: Path) -> list[str]:
    return ct.check(root, languages=["de"], documents=["DOC.md"])


GOOD = """# Titel

Einleitung mit `--flag` und Version 1.2.3, siehe [Anleitung](GUIDE.de.md) und [unten](#verwendung).

## Verwendung

```bash
ekte check --model gpt-4o
```

## Grenzen

Setze `{name}` sorgfältig.
"""


def test_repository_docs_are_consistent():
    assert ct.check(ROOT) == []


def test_every_language_in_the_list_has_all_documents():
    for source in ct.DOCUMENTS:
        for lang in ct.LANGUAGES:
            assert (ROOT / ct.doc_path(source, lang)).exists()


def test_consistent_translation_passes(tmp_path):
    assert _run(_tree(tmp_path, GOOD)) == []


def test_removed_section_fails(tmp_path):
    bad = GOOD.split("## Grenzen")[0]
    errors = _run(_tree(tmp_path, bad))
    assert any("heading count differs" in e for e in errors)


def test_changed_heading_level_fails(tmp_path):
    errors = _run(_tree(tmp_path, GOOD.replace("## Grenzen", "### Grenzen")))
    assert any("level differs" in e for e in errors)


def test_changed_command_fails(tmp_path):
    errors = _run(_tree(tmp_path, GOOD.replace("gpt-4o", "gpt-5")))
    assert any("code block #1" in e for e in errors)


def test_comment_wording_in_code_is_ignored(tmp_path):
    src = SOURCE.replace("ekte check", "# run it\nekte check")
    (tmp_path / "x").mkdir()
    root = _tree(tmp_path, GOOD.replace("ekte check", "# starte es\nekte check"))
    (root / "DOC.md").write_text(src, encoding="utf-8")
    assert _run(root) == []


def test_broken_relative_link_fails(tmp_path):
    errors = _run(_tree(tmp_path, GOOD.replace("GUIDE.de.md", "NOPE.de.md")))
    assert any("does not exist" in e for e in errors)


def test_broken_anchor_fails(tmp_path):
    errors = _run(_tree(tmp_path, GOOD.replace("#verwendung", "#gibtsnicht")))
    assert any("anchor #gibtsnicht" in e for e in errors)


def test_version_drift_fails(tmp_path):
    errors = _run(_tree(tmp_path, GOOD.replace("1.2.3", "1.2.4")))
    assert any("version numbers differ" in e for e in errors)


def test_placeholder_drift_fails(tmp_path):
    errors = _run(_tree(tmp_path, GOOD.replace("{name}", "{nom}")))
    assert any("placeholders differ" in e for e in errors)


def test_missing_translation_fails(tmp_path):
    root = _tree(tmp_path, GOOD)
    (root / "DOC.de.md").unlink()
    assert any("translation missing" in e for e in _run(root))


def test_pending_marker_skips_structure_but_not_links(tmp_path):
    pending = "<!-- translation-pending: waiting for a translator -->\n# Titel\n"
    assert _run(_tree(tmp_path, pending)) == []
    broken = pending + "\n[x](NOPE.md)\n"
    assert any("does not exist" in e for e in _run(_tree(tmp_path, broken)))


def test_slugify_matches_github():
    assert ct.slugify("Über `ekte` & Co.") == "über-ekte--co"


@pytest.mark.parametrize("lang", ["de", "zh-CN"])
def test_doc_path(lang):
    assert ct.doc_path("docs/METHODOLOGY.md", lang) == f"docs/METHODOLOGY.{lang}.md"
