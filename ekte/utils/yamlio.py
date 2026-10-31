"""Safe YAML loading with libyaml's C parser when PyYAML was built with it.

``CSafeLoader`` parses about 10x faster than the pure-Python ``SafeLoader`` and
loads the same safe subset of YAML into the same data: the scanner, parser and
composer are C, construction (and so the refusal of unknown or unsafe tags) is
the same Python ``SafeConstructor``. libyaml's composer recurses in C once per
nesting level, so bound the nesting of untrusted input (from :func:`parse`'s
events) before loading it, as the profile importer does.

libyaml's error messages are terser, though: "found character that cannot
start any token" instead of "found character '\\t' that cannot start any
token". Where a message is shown to the user, :func:`detailed_error` re-runs
the failed load with the pure-Python loader to get its more specific message;
that costs time only for input that is already being rejected.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import yaml

# Typed as Any: CSafeLoader is not a SafeLoader subclass in the stubs. The
# functions below take an explicit ``loader`` (default: this one, looked up at
# call time) so the pure-Python loader can be used for comparison.
SAFE_LOADER: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


# Errors PyYAML's SafeConstructor raises, as plain Python exceptions, for a
# scalar it cannot convert: ``!!int abc`` (ValueError), ``!!bool maybe``
# (KeyError), ``!!timestamp 2026-99-99`` (ValueError), a huge float (OverflowError).
_SCALAR_ERRORS = (ValueError, LookupError, TypeError, OverflowError)
_STRICT: dict[Any, Any] = {}


def _strict(loader: Any) -> Any:
    """``loader`` with a constructor that reports a scalar it cannot convert
    as a ``ConstructorError`` at that node (with its line and column), like
    every other YAML error, instead of letting a bare ValueError/KeyError
    escape callers that handle ``yaml.YAMLError``."""
    cls = _STRICT.get(loader)
    if cls is None:

        class Strict(loader):
            def construct_object(self, node: yaml.Node, deep: bool = False) -> Any:
                try:
                    return super().construct_object(node, deep=deep)
                except _SCALAR_ERRORS as exc:
                    tag = str(node.tag).rsplit(":", 1)[-1]
                    value = node.value if isinstance(node.value, str) else ""
                    shown = value if len(value) <= 40 else value[:40] + "…"
                    # a KeyError's text is just the value again (``!!bool maybe``)
                    why = "" if isinstance(exc, LookupError) else f": {exc}"
                    raise yaml.constructor.ConstructorError(
                        None, None, f"cannot read {shown!r} as {tag}{why}", node.start_mark
                    ) from exc

        cls = _STRICT[loader] = Strict
    return cls


def safe_load(text: str, loader: Any = None) -> Any:
    """The single document in ``text`` (``None`` when empty), like ``yaml.safe_load``."""
    return yaml.load(text, Loader=_strict(loader or SAFE_LOADER))


def safe_load_all(text: str, loader: Any = None) -> Iterator[Any]:
    """Each document in ``text``, like ``yaml.safe_load_all``."""
    return yaml.load_all(text, Loader=_strict(loader or SAFE_LOADER))


def parse(text: str, loader: Any = None) -> Iterator[yaml.Event]:
    """The parser events of ``text``, like ``yaml.parse`` with a safe loader."""
    return yaml.parse(text, Loader=loader or SAFE_LOADER)


def detailed_error(exc: yaml.YAMLError, retry: Callable[[Any], object]) -> yaml.YAMLError:
    """The pure-Python loader's error for a load that failed with ``exc``.

    ``retry`` repeats the failed load (or just its parsing) with the loader
    class it is given. When the pure-Python loader fails too, its (more
    specific) error is returned; otherwise -- the loaders disagree, or the
    retry hits RecursionError on very deep nesting -- ``exc`` is. Constructor
    errors (such as an unknown tag) come from the same Python code with both
    loaders, so they are returned as they are, without a retry.
    """
    if SAFE_LOADER is yaml.SafeLoader or isinstance(exc, yaml.constructor.ConstructorError):
        return exc
    try:
        retry(yaml.SafeLoader)
    except yaml.YAMLError as detailed:
        return detailed
    except RecursionError:
        pass
    return exc
