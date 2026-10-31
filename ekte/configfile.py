"""Format, schema, validation and migration of the YAML configuration file.

The file carries a format version (``version:``). A file without one is format
1. Every key is described once, in ``SCHEMA``; validation and the published JSON
schema (``docs/schemas/config.schema.json``) derive from it. See
docs/STABILITY.md#surface-config.
"""

from __future__ import annotations

import difflib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ekte.utils import yamlio

CURRENT_VERSION = 1
SCHEMA_ID = "https://raw.githubusercontent.com/mn567250/ekte/main/docs/schemas/config.schema.json"

SUITES = ("smoke", "standard", "deep", "full", "custom")
DIMENSIONS = ("connectivity", "protocol", "context_window", "model_identity", "capability",
              "streaming", "billing", "reliability", "security", "performance")
APIS = ("auto", "openai", "anthropic", "responses")
FORMATS = ("json", "md", "html", "pdf", "all")


@dataclass(frozen=True)
class Key:
    kind: str  # str | int | number | bool | list | map
    desc: str
    default: Any = None
    choices: tuple[str, ...] | None = None
    minimum: float | None = None


def _endpoint() -> dict[str, Key]:
    return {
        "name": Key("str", "Label shown in reports"),
        "base_url": Key("str", "Endpoint URL, http:// or https://"),
        "api_key": Key("str", "API key: env:VAR, file:/path or a literal"),
        "model": Key("str", "Model id sent to the endpoint"),
        "api": Key("str", "Wire protocol", "auto", APIS),
        "declared_provider": Key("str", "Provider the relay claims; inferred from the model id"),
        "claimed_model": Key("str", "Model the relay claims to serve; defaults to model"),
        "timeout_sec": Key("number", "Base HTTP timeout in seconds", 60, minimum=0),
        "max_request_sec": Key("number", "Hard cap per request in seconds", 900, minimum=0),
        "headers": Key("map", "Extra HTTP headers", {}),
    }


SCHEMA: dict[str, Any] = {
    "version": Key("int", "Format version of this file", CURRENT_VERSION, minimum=1),
    "target": _endpoint(),
    "baseline": _endpoint(),
    "run": {
        "suite": Key("str", "Audit depth", "standard", SUITES),
        "dimensions": Key("list", "Dimensions of the custom suite", [], DIMENSIONS),
        "judge": Key("bool", "Enable code+LLM hybrid judging", False),
        "output_dir": Key("str", "Directory for report files", "reports"),
        "format": Key("str", "Report format", "all", FORMATS),
        "reliability_requests": Key("int", "Reliability probe requests", 8, minimum=0),
        "concurrency": Key("int", "Reliability probe concurrency", 3, minimum=1),
        "max_context_probe_tokens": Key("int", "Cap for the context-window probe", 200000, minimum=0),
        "performance_requests": Key("int", "Performance probe requests per endpoint (0 disables)", 100, minimum=0),
        "performance_max_tokens": Key("int", "Output tokens per performance request", 128, minimum=1),
        "performance_streaming": Key("bool", "Probe with streaming requests", True),
    },
    "judge": {
        "base_url": Key("str", "Judge endpoint URL"),
        "api_key": Key("str", "API key: env:VAR, file:/path or a literal"),
        "model": Key("str", "Judge model id"),
    },
}

# DEPRECATED keys ("section.key" -> "section.new_key") are still part of the
# current format: they load, with a warning naming the replacement, for the
# period docs/STABILITY.md#deprecation defines. RENAMES_FROM[n] lists the
# renames that bring a file of format n to format n+1.
DEPRECATED: dict[str, str] = {}
RENAMES_FROM: dict[int, dict[str, str]] = {}


class ConfigFileError(Exception):
    """A problem with the configuration file (reported as ConfigError)."""


def _line_map(text: str) -> dict[str, int]:
    """1-based line of every key path ("run.suite") in ``text``."""
    lines: dict[str, int] = {}
    try:
        root = yaml.compose(text, Loader=yamlio.SAFE_LOADER)
    except yaml.YAMLError:
        return lines

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                path = f"{prefix}.{k.value}" if prefix else str(k.value)
                lines[path] = k.start_mark.line + 1
                if not prefix:
                    walk(v, path)

    walk(root, "")
    return lines


def _typecheck(key: Key, value: Any) -> str | None:
    """What ``key`` expects instead of ``value``, or None when it is fine."""
    k = key.kind
    if k == "str":
        if not isinstance(value, str):
            return "a string"
        if key.choices and value not in key.choices:
            return "one of " + ", ".join(key.choices)
    elif k == "bool":
        if not isinstance(value, bool):
            return "true or false"
    elif k in ("int", "number"):
        if isinstance(value, bool) or not isinstance(value, int | float) or (
            k == "int" and not isinstance(value, int)
        ):
            return "an integer" if k == "int" else "a number"
        if key.minimum is not None and value < key.minimum:
            return f"a number >= {key.minimum:g}"
    elif k == "list":
        if not isinstance(value, list):
            return "a list"
        for item in value:
            if not isinstance(item, str) or (key.choices and item not in key.choices):
                return "a list of " + (", ".join(key.choices) if key.choices else "strings")
    elif k == "map":
        if not isinstance(value, dict) or not all(
            isinstance(a, str) and isinstance(b, str | int | float) for a, b in value.items()
        ):
            return "a mapping of header names to values"
    return None


def _show(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _unknown(name: str, known: list[str]) -> str:
    match = difflib.get_close_matches(name, known, n=1)
    hint = f" Did you mean {match[0]!r}?" if match else ""
    return f"unknown key.{hint} Allowed: {', '.join(known)}"


def validate(data: dict[str, Any], text: str, source: str) -> dict[str, Any]:
    """Validate parsed config ``data``; return it normalised.

    Raises ConfigFileError naming the file, line, key and what is expected.
    Deprecated keys are moved to their replacement with a warning on stderr.
    """
    lines = _line_map(text)

    def fail(path: str, problem: str) -> ConfigFileError:
        line = lines.get(path)
        where = f"{source}, line {line}" if line else source
        return ConfigFileError(f"{where}: {path}: {problem}")

    version = data.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise fail("version", f"expected a whole number >= 1, got {_show(version)}")
    if version > CURRENT_VERSION:
        raise fail(
            "version",
            f"format {version} is newer than this ekte understands (format "
            f"{CURRENT_VERSION}); upgrade ekte",
        )
    if version < CURRENT_VERSION:
        raise fail(
            "version",
            f"format {version} is outdated (current: {CURRENT_VERSION}); run "
            f"`ekte config migrate {source}`",
        )

    out: dict[str, Any] = {"version": version} if "version" in data else {}
    for name, value in data.items():
        if name == "version":
            continue
        spec = SCHEMA.get(name)
        if not isinstance(spec, dict):
            raise fail(name, _unknown(name, [k for k, v in SCHEMA.items() if isinstance(v, dict)]
                                      + ["version"]))
        if value is None:
            continue
        if not isinstance(value, dict):
            raise fail(name, f"expected a mapping, got {_show(value)}")
        section: dict[str, Any] = {}
        for key, item in value.items():
            path = f"{name}.{key}"
            if path in DEPRECATED:
                new = DEPRECATED[path]
                print(
                    f"ekte: warning: {source}, line {lines.get(path, '?')}: {path} is "
                    f"deprecated; use {new}",
                    file=sys.stderr,
                )
                key = new.split(".", 1)[1]
                if key in value:
                    continue  # the replacement is set too; it wins
                path = new
            key_spec = spec.get(key)
            if key_spec is None:
                raise fail(path, _unknown(str(key), list(spec)))
            if item is None:
                continue
            problem = _typecheck(key_spec, item)
            if problem:
                raise fail(path, f"expected {problem}, got {_show(item)}")
            section[key] = item
        out[name] = section
    return out


def load(text: str, source: str) -> dict[str, Any]:
    """Parse and validate config ``text`` (``{}`` for an empty file)."""
    try:
        data = yamlio.safe_load(text)
    except yaml.YAMLError as c_exc:
        exc = yamlio.detailed_error(c_exc, lambda loader: yamlio.safe_load(text, loader))
        raise ConfigFileError(f"Invalid YAML in {source}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigFileError(f"{source}: must contain a mapping at the top level")
    return validate(data, text, source)


def migrate_text(text: str, source: str) -> tuple[str, list[str]]:
    """Rewrite config ``text`` to the current format, keeping its comments.

    Returns the new text and what changed (an empty list when already current).
    """
    try:
        data = yamlio.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigFileError(f"Invalid YAML in {source}: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigFileError(f"{source}: must contain a mapping at the top level")
    version = data.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ConfigFileError(f"{source}: version: expected a whole number >= 1")
    if version > CURRENT_VERSION:
        raise ConfigFileError(
            f"{source}: format {version} is newer than this ekte understands; upgrade ekte"
        )
    changes: list[str] = []
    rows = text.splitlines()
    lines = _line_map(text)
    renames = {o: n for v in range(version, CURRENT_VERSION) for o, n in RENAMES_FROM.get(v, {}).items()}
    renames.update(DEPRECATED)
    for old, new in renames.items():
        idx = lines.get(old)
        section = old.split(".", 1)[0]
        if idx and new.split(".", 1)[1] not in (data.get(section) or {}):
            leaf, new_leaf = old.rsplit(".", 1)[-1], new.rsplit(".", 1)[-1]
            rows[idx - 1] = rows[idx - 1].replace(f"{leaf}:", f"{new_leaf}:", 1)
            changes.append(f"renamed {old} to {new}")
    if "version" in data:
        if data["version"] != CURRENT_VERSION:
            rows[lines["version"] - 1] = f"version: {CURRENT_VERSION}"
            changes.append(f"set version to {CURRENT_VERSION}")
    else:
        at = 0  # after the leading comment block, so the header stays on top
        while at < len(rows) and (rows[at].startswith("#") or not rows[at].strip()):
            at += 1
        rows[at:at] = [f"version: {CURRENT_VERSION}", ""]
        changes.append(f"added version: {CURRENT_VERSION}")
    return "\n".join(rows) + "\n", changes


def json_schema() -> dict[str, Any]:
    """The JSON Schema (draft 2020-12) of the current format."""
    types = {"str": "string", "int": "integer", "number": "number", "bool": "boolean",
             "list": "array", "map": "object"}

    def prop(key: Key) -> dict[str, Any]:
        p: dict[str, Any] = {"type": types[key.kind], "description": key.desc}
        if key.kind == "str" and key.choices:
            p["enum"] = list(key.choices)
        if key.kind == "list":
            p["items"] = {"type": "string", **({"enum": list(key.choices)} if key.choices else {})}
        if key.kind == "map":
            p["additionalProperties"] = {"type": ["string", "number"]}
        if key.minimum is not None:
            p["minimum"] = key.minimum
        if key.default is not None:
            p["default"] = key.default
        return p

    props: dict[str, Any] = {}
    for name, spec in SCHEMA.items():
        if isinstance(spec, Key):
            props[name] = prop(spec)
        else:
            props[name] = {
                "type": "object",
                "additionalProperties": False,
                "properties": {k: prop(v) for k, v in spec.items()},
            }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": f"ekte configuration file, format {CURRENT_VERSION}",
        "type": "object",
        "additionalProperties": False,
        "properties": props,
    }


def schema_text() -> str:
    return json.dumps(json_schema(), indent=2) + "\n"


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "docs" / "schemas" / "config.schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(schema_text(), encoding="utf-8")
