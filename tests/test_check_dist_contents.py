import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_dist", ROOT / "scripts" / "check_dist_contents.py")
assert _spec and _spec.loader
cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd)

NOTICE = (ROOT / "NOTICE").read_text(encoding="utf-8")


def test_notice_lists_vendored_axe():
    assert "tests/a11y/vendor/axe.min.js" in cd.notice_undistributed(NOTICE)


def test_notice_distributed_file_not_listed():
    text = "Foo ekte/x.py is bundled.\n\nBar tests/y.js is not distributed."
    assert cd.notice_undistributed(text) == ["tests/y.js"]


def test_violations_flags_excluded_and_notice_files():
    members = ["ekte/cli.py", "tests/a11y/vendor/axe.min.js", "tests/z.js", "tests/a11y/vendor/README.md"]
    assert cd.violations(members, "tests/z.js is not distributed.") == [
        "tests/a11y/vendor/axe.min.js",
        "tests/z.js",
    ]


def test_archive_members(tmp_path):
    whl = tmp_path / "a.whl"
    with zipfile.ZipFile(whl, "w") as z:
        z.writestr("ekte/__init__.py", "")
    assert cd.archive_members(whl) == ["ekte/__init__.py"]
    sd = tmp_path / "a.tar.gz"
    with tarfile.open(sd, "w:gz") as t:
        t.addfile(tarfile.TarInfo("ekte-1/tests/a.py"), io.BytesIO(b""))
    assert cd.archive_members(sd) == ["tests/a.py"]


_hspec = importlib.util.spec_from_file_location("hatch_readme", ROOT / "scripts" / "hatch_readme.py")
assert _hspec and _hspec.loader
hr = importlib.util.module_from_spec(_hspec)
_hspec.loader.exec_module(hr)


def test_readme_links_become_absolute_for_the_release_tag():
    text = (
        "[Install](docs/guide/install.md) [x](./LICENSE) ![shot](docs/a.png) "
        "[ext](https://example.com) [mail](mailto:a@b.c)"
    )
    out = hr.absolute_links(text, "1.2.3")
    assert "](https://github.com/mn567250/ekte/blob/v1.2.3/docs/guide/install.md)" in out
    assert "](https://github.com/mn567250/ekte/blob/v1.2.3/LICENSE)" in out
    assert "](https://raw.githubusercontent.com/mn567250/ekte/v1.2.3/docs/a.png)" in out
    assert "](https://example.com)" in out and "](mailto:a@b.c)" in out
    assert hr.relative_links(out) == []


def test_relative_links_and_anchors_are_reported():
    assert hr.relative_links("[a](docs/x.md) [b](#top) [c](https://x.y)") == ["docs/x.md", "#top"]


def test_repository_readme_has_no_link_left_relative_after_the_rewrite():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert hr.relative_links(hr.absolute_links(text, "0.0.0")) == []


def test_wheel_description(tmp_path):
    whl = tmp_path / "a.whl"
    with zipfile.ZipFile(whl, "w") as z:
        z.writestr("ekte-1.dist-info/METADATA", "Name: ekte\nVersion: 1\n\n# ekte\n[x](docs/y.md)\n")
    desc = cd.wheel_description(whl)
    assert desc.startswith("# ekte")
    assert cd.unresolvable_links(desc) == ["docs/y.md"]
