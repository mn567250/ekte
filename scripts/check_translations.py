#!/usr/bin/env python3
"""Check that translated documentation has not drifted structurally.

Compares every translation of README, the developer guide and the methodology
against the English source: heading levels, code blocks, link targets, inline
code, placeholders and version numbers. It never judges wording. It also checks
that relative links and in-document anchors resolve (no network access).

Adding a language: add its code to ``LANGUAGES``.
Marking a translation as pending: put ``<!-- translation-pending: reason -->``
anywhere in the file; its structure is then not compared (links must still
resolve). See CONTRIBUTING.md.

Usage: python scripts/check_translations.py [--root DIR]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

# The one list to edit when a language is added.
LANGUAGES = ["de", "es", "fr", "it", "nb", "pt", "zh-CN"]

# English source documents, relative to the repository root.
DOCUMENTS = ["README.md", "DEVELOPER_GUIDE.md", "docs/METHODOLOGY.md"]

# Fenced blocks that may contain localized wording; only their length is compared.
FREE_TEXT_BLOCKS = {"", "text", "txt", "plain", "console-output", "output"}

PENDING_RE = re.compile(r"<!--\s*translation-pending\b[^>]*-->")
FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([^\s`]*)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
LINK_RE = re.compile(
    r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)"
)
HTML_ATTR_RE = re.compile(r"""(?:href|src)=["']([^"']+)["']""")
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`]+)`(?!`)")
PLACEHOLDER_RE = re.compile(
    r"\{[A-Za-z_][\w.-]*\}|<[A-Z][A-Z0-9_]+>|\$\{?[A-Z_][A-Z0-9_]*\}?"
)
VERSION_RE = re.compile(r"(?<![\w.])v?\d+\.\d+(?:\.\d+)*\+?(?![\w])")


def doc_path(source: str, lang: str) -> str:
    stem, ext = source.rsplit(".", 1)
    return f"{stem}.{lang}.{ext}"


def slugify(text: str) -> str:
    """GitHub-style heading anchor."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").strip().lower()
    out = []
    for ch in text:
        if ch.isalnum() or ch in "_-":
            out.append(ch)
        elif ch.isspace():
            out.append("-")
    return "".join(out)


class Doc:
    def __init__(self, path: Path, text: str):
        self.path = path
        self.pending = bool(PENDING_RE.search(text))
        self.headings: list[tuple[int, str]] = []
        self.blocks: list[tuple[str, str]] = []
        prose: list[str] = []
        fence = None
        buf: list[str] = []
        info = ""
        for line in text.splitlines():
            m = FENCE_RE.match(line)
            if fence is None:
                if m:
                    fence, info, buf = m.group(2), m.group(3), []
                    continue
                prose.append(line)
                h = HEADING_RE.match(line)
                if h:
                    self.headings.append((len(h.group(1)), h.group(2)))
            elif (
                m
                and m.group(2)[0] == fence[0]
                and len(m.group(2)) >= len(fence)
                and not m.group(3)
            ):
                self.blocks.append((info, "\n".join(buf).strip()))
                fence = None
            else:
                buf.append(line)
        prose_text = "\n".join(prose)
        no_code = INLINE_CODE_RE.sub("", prose_text)
        self.links = LINK_RE.findall(no_code) + HTML_ATTR_RE.findall(no_code)
        self.inline_code = [" ".join(c.split()) for c in INLINE_CODE_RE.findall(prose_text)]
        self.anchors: set[str] = set()
        seen: Counter[str] = Counter()
        for _, title in self.headings:
            s = slugify(title)
            n = seen[s]
            seen[s] += 1
            self.anchors.add(s if n == 0 else f"{s}-{n}")
        self.anchors |= set(re.findall(r"""<a\s[^>]*(?:name|id)=["']([^"']+)["']""", text))
        code_all = "\n".join(c for _, c in self.blocks)
        self.placeholders = Counter(PLACEHOLDER_RE.findall(prose_text + "\n" + code_all))
        # Prose decimals are localized (1,5 vs 1.5), so prose only counts x.y.z.
        prose_versions = [v for v in VERSION_RE.findall(no_code) if v.count(".") >= 2]
        self.versions = Counter(
            prose_versions + VERSION_RE.findall(code_all + "\n" + "\n".join(self.inline_code))
        )


def load(path: Path) -> Doc:
    return Doc(path, path.read_text(encoding="utf-8"))


def _strip_lang(target: str) -> str:
    """Map translated file names back to the English source name."""
    pat = "|".join(re.escape(lang) for lang in LANGUAGES)
    return re.sub(rf"\.(?:{pat})\.md\b", ".md", target)


def _is_external(target: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target)) or target.startswith("//")


def _norm_link(target: str) -> str:
    if _is_external(target):
        return target
    path, _, frag = target.partition("#")
    if not path:  # in-document anchor: wording-dependent, checked for resolution only
        return "#"
    return _strip_lang(path) + ("#" if frag else "")


def check_links(doc: Doc, cache: dict[Path, Doc]) -> list[str]:
    errs = []
    for target in doc.links:
        if _is_external(target):
            continue
        path, _, frag = target.partition("#")
        if not path:
            if frag and frag not in doc.anchors and frag != "top":
                errs.append(f"anchor #{frag} does not resolve")
            continue
        dest = (doc.path.parent / path.split("?")[0]).resolve()
        if not dest.exists():
            errs.append(f"link target {path} does not exist")
            continue
        if frag and dest.suffix == ".md" and dest.is_file():
            other = cache.get(dest)
            if other is None:
                other = cache[dest] = load(dest)
            if frag not in other.anchors:
                errs.append(f"anchor {path}#{frag} does not resolve")
    return errs


def _short(items, n=6):
    items = list(items)
    return items[:n] + (["..."] if len(items) > n else [])


def _code_norm(code: str) -> str:
    """Ignore comment wording: drop '# ...' comments (comments are prose)."""
    lines = []
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("#") and not s.startswith("#!"):
            continue
        line = re.sub(r"\s+#\s.*$", "", line)
        line = re.sub(r"(--alert-lang\s+)\S+", r"\1LANG", line)  # per-language value
        line = re.sub(r"\bsk-[\w-]+", "sk-KEY", line)  # localized dummy keys
        if line.strip():
            lines.append(line.rstrip())
    return "\n".join(lines)


def _inline_keys(spans):
    """CLI flags, HTTP endpoints and field names; other inline code may legitimately be localized."""
    keys = []
    for span in spans:
        m = re.match(r"^(--[\w-]+)", span) or re.match(r"^((?:GET|POST|PUT|DELETE) /\S*)", span)
        if m:
            keys.append(m.group(1))
        elif re.fullmatch(r"[a-z][a-z0-9]*(?:[._][a-z0-9]+)+", span) and not re.search(
            r"\.(?:json|md|ya?ml|pdf|html?|py|toml|txt|csv)$", span
        ):
            keys.append(span)  # report field / setting names such as target.api_auto
    return keys


def compare(src: Doc, tr: Doc) -> list[str]:
    errs = []
    sl = [lv for lv, _ in src.headings]
    tl = [lv for lv, _ in tr.headings]
    if len(sl) != len(tl):
        errs.append(f"heading count differs: source {len(sl)}, translation {len(tl)}")
    for i, (a, b) in enumerate(zip(sl, tl, strict=False)):
        if a != b:
            errs.append(
                f"heading #{i + 1} level differs: source h{a} ({src.headings[i][1]!r}), "
                f"translation h{b} ({tr.headings[i][1]!r})"
            )
            break
    if len(src.blocks) != len(tr.blocks):
        errs.append(
            f"code block count differs: source {len(src.blocks)}, "
            f"translation {len(tr.blocks)}"
        )
    else:
        for i, (a, b) in enumerate(zip(src.blocks, tr.blocks, strict=True)):
            if a[0] != b[0]:
                errs.append(f"code block #{i + 1} language differs: {a[0]!r} vs {b[0]!r}")
            elif a[0] in FREE_TEXT_BLOCKS:
                # trees / sample output carry localized descriptions: compare size only
                if len(_code_norm(a[1]).splitlines()) != len(_code_norm(b[1]).splitlines()):
                    errs.append(f"code block #{i + 1} ({a[0] or 'text'}) line count differs")
            elif _code_norm(a[1]) != _code_norm(b[1]):
                errs.append(f"code block #{i + 1} ({a[0] or 'text'}) content differs")
    sn = Counter(_norm_link(t) for t in src.links)
    tn = Counter(_norm_link(t) for t in tr.links)
    if sn != tn:
        errs.append(
            "links differ: missing " + str(_short((sn - tn).elements()))
            + ", extra " + str(_short((tn - sn).elements()))
        )
    sc = set(_inline_keys(src.inline_code))
    tc = set(_inline_keys(tr.inline_code))
    if sc != tc:
        errs.append(
            "flags, endpoints or field names in inline code differ: missing " + str(_short(sorted(sc - tc)))
            + ", extra " + str(_short(sorted(tc - sc)))
        )
    if src.placeholders != tr.placeholders:
        errs.append(
            "placeholders differ: missing "
            + str(_short((src.placeholders - tr.placeholders).elements()))
            + ", extra " + str(_short((tr.placeholders - src.placeholders).elements()))
        )
    if src.versions != tr.versions:
        errs.append(
            "version numbers differ: missing "
            + str(_short((src.versions - tr.versions).elements()))
            + ", extra " + str(_short((tr.versions - src.versions).elements()))
        )
    return errs


def check(root: Path, languages=None, documents=None) -> list[str]:
    languages = LANGUAGES if languages is None else languages
    documents = DOCUMENTS if documents is None else documents
    errors: list[str] = []
    cache: dict[Path, Doc] = {}

    def get(p: Path) -> Doc:
        p = p.resolve()
        if p not in cache:
            cache[p] = load(p)
        return cache[p]

    for source in documents:
        sp = root / source
        if not sp.exists():
            errors.append(f"{source}: source document missing")
            continue
        src = get(sp)
        errors += [f"{source}: {e}" for e in check_links(src, cache)]
        for lang in languages:
            rel = doc_path(source, lang)
            tp = root / rel
            if not tp.exists():
                errors.append(f"{rel}: translation missing (add the file or mark it pending)")
                continue
            tr = get(tp)
            errors += [f"{rel}: {e}" for e in check_links(tr, cache)]
            if tr.pending:
                continue
            errors += [f"{rel}: {e}" for e in compare(src, tr)]
    return errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check translated docs for structural drift.")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args(argv)
    errors = check(args.root)
    for e in errors:
        print(e)
    if errors:
        print(f"\n{len(errors)} translation problem(s). See CONTRIBUTING.md.")
        return 1
    print("translations consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
