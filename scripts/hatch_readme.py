"""Hatchling metadata hook: README.md as the PyPI description, links made absolute.

The README links to the rest of the documentation with relative paths, which
work on GitHub and are checked by scripts/check_translations.py. PyPI cannot
resolve them, so the build rewrites every relative link to the file on GitHub
at the release tag (``v<version>``): links to ``github.com/.../blob/<tag>/``,
images to ``raw.githubusercontent.com/.../<tag>/``.
Configured in pyproject.toml under ``[tool.hatch.metadata.hooks.custom]``.
"""
from __future__ import annotations

import re
from pathlib import Path

try:
    from hatchling.metadata.plugin.interface import MetadataHookInterface
except ImportError:  # imported by the tests, without hatchling
    MetadataHookInterface = object  # type: ignore[assignment,misc]

REPO = "mn567250/ekte"
README = "README.md"
LINK_RE = re.compile(r"(!?)(\[(?:[^\[\]]|\[[^\]]*\])*\]\()\s*<?([^)\s>]+)>?((?:\s+\"[^\"]*\")?\s*\))")
ABSOLUTE_RE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//|#)")


def absolute_links(text: str, version: str) -> str:
    """Rewrite relative Markdown links and images to absolute GitHub URLs."""
    tag = f"v{version}"

    def fix(m: re.Match[str]) -> str:
        bang, label, target, tail = m.groups()
        if ABSOLUTE_RE.match(target):
            return m.group(0)
        path = target[2:] if target.startswith("./") else target
        base = (
            f"https://raw.githubusercontent.com/{REPO}/{tag}/"
            if bang
            else f"https://github.com/{REPO}/blob/{tag}/"
        )
        return f"{bang}{label}{base}{path}{tail}"

    return LINK_RE.sub(fix, text)


def relative_links(text: str) -> list[str]:
    """Link targets PyPI cannot resolve (relative paths and in-page anchors)."""
    out = []
    for m in LINK_RE.finditer(text):
        target = m.group(3)
        if not re.match(r"^(?:https?:|mailto:)", target):
            out.append(target)
    return out


class ReadmeHook(MetadataHookInterface):  # type: ignore[misc,valid-type]
    PLUGIN_NAME = "custom"

    def update(self, metadata: dict) -> None:
        text = (Path(self.root) / README).read_text(encoding="utf-8")
        metadata["readme"] = {
            "content-type": "text/markdown",
            "text": absolute_links(text, metadata["version"]),
        }
