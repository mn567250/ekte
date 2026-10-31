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
