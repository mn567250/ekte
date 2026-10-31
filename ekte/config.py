"""Config loading, secret resolution, and run options.

A run can be configured entirely on the command line or via a YAML file (see
``TEMPLATE``). CLI flags always win over file values.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ekte import configfile
from ekte.models import Dimension, TargetConfig

# ``custom`` runs the dimensions the user picks (``AuditOptions.dimensions``) at
# deep depth; the others are cumulative tiers.
SUITES = ("smoke", "standard", "deep", "full", "custom")
DIMENSIONS = tuple(d.value for d in Dimension)
# What kind of endpoint is audited, orthogonal to the suite (the depth). A
# missing value (old reports, NULL database columns) means ``chat``.
SURFACES = ("chat", "embedding", "rerank")
# The request op whose records measure a surface (performance, errors view).
SURFACE_OPS = {"chat": "complete", "embedding": "embed", "rerank": "rerank"}
FORMATS = ("json", "md", "html", "pdf", "all")
RISK_LEVELS = ("low", "medium", "high")
APIS = ("auto", "openai", "anthropic", "responses")


class ConfigError(Exception):
    """Raised for user-facing configuration problems."""


class AuditOptions(BaseModel):
    """Knobs that control which detectors run and how aggressively."""

    model_config = ConfigDict(extra="forbid")

    suite: str = "standard"
    surface: str = "chat"  # one of SURFACES
    judge: bool = False
    only: list[str] = Field(default_factory=list)   # run only these detector ids
    skip: list[str] = Field(default_factory=list)    # skip these detector ids
    # Dimensions the ``custom`` suite runs (empty for the fixed suites).
    dimensions: list[str] = Field(default_factory=list)

    # Context-window probe: cap so a claimed 1M model does not cost a fortune.
    max_context_probe_tokens: int = 200_000
    context_probe_floor_tokens: int = 1_000

    # Reliability probe.
    reliability_requests: int = 8
    reliability_concurrency: int = 3

    # Identity/determinism sampling.
    determinism_samples: int = 3

    # Performance probe (deep/full/custom, or compare mode on standard): uncacheable
    # streaming requests per endpoint and their output length. 0 disables it.
    performance_requests: int = 100
    performance_max_tokens: int = 128
    # Probe with streaming (True) or non-streaming requests, e.g. for a relay
    # that cannot stream. The full suite always measures both.
    performance_streaming: bool = True

    # Embedding surface: expected vector length of the claimed model, overriding
    # the knowledge base (0 = take it from the KB).
    embedding_dimensions: int = 0

    def enabled(self, detector_id: str) -> bool:
        if self.only:
            return detector_id in self.only
        return detector_id not in self.skip


def resolve_secret(value: str | None) -> str:
    """Resolve a secret reference.

    Supports ``env:VAR`` (read from environment), ``file:/path`` (read file
    contents, stripped), or a raw literal. Empty/None resolves to "".
    """
    if not value:
        return ""
    if value.startswith("env:"):
        var = value[len("env:"):]
        return os.environ.get(var, "")
    if value.startswith("file:"):
        path = Path(value[len("file:"):]).expanduser()
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"Could not read secret file {path}: {exc}") from exc
    return value


def load_config_file(path: Path | None) -> dict[str, Any]:
    """Read and validate the config file (see ``ekte.configfile``)."""
    if path is None:
        return {}
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Could not read config file {path}: {exc}") from exc
    try:
        return configfile.load(text, str(path))
    except configfile.ConfigFileError as exc:
        raise ConfigError(str(exc)) from exc


def section(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    value = cfg.get(name)
    return value if isinstance(value, dict) else {}


def merge_headers(
    file_headers: dict[str, str] | None, cli_headers: list[str] | None
) -> dict[str, str]:
    merged: dict[str, str] = dict(file_headers or {})
    for raw in cli_headers or []:
        if ":" not in raw:
            raise ConfigError(f"Header must be in 'Name: value' form: {raw!r}")
        key, _, val = raw.partition(":")
        merged[key.strip()] = val.strip()
    return merged


def build_target(
    *,
    kind: str,
    name: str | None,
    base_url: str | None,
    api_key: str | None,
    model: str | None,
    declared_provider: str | None = None,
    timeout_sec: float | None = None,
    max_request_sec: float | None = None,
    headers: dict[str, str] | None = None,
    api: str | None = None,
    claimed_model: str | None = None,
) -> TargetConfig:
    if not base_url:
        raise ConfigError(f"{kind}: base_url is required")
    base_url = base_url.strip()
    if not base_url.lower().startswith(("http://", "https://")):
        raise ConfigError(
            f"{kind}: base_url must start with http:// or https:// (got {base_url!r})"
        )
    if not model:
        raise ConfigError(f"{kind}: model is required")
    return TargetConfig(
        name=name or kind,
        kind=kind,
        base_url=base_url,
        api_key=resolve_secret(api_key),
        model=model,
        claimed_model=claimed_model,
        declared_provider=declared_provider,
        timeout_sec=timeout_sec if timeout_sec is not None else 60.0,
        max_request_sec=max_request_sec if max_request_sec is not None else 900.0,
        headers=headers or {},
        api=validate_api(api),
    )


def validate_suite(value: str) -> str:
    if value not in SUITES:
        raise ConfigError(f"Unknown suite {value!r}. Choose from: {', '.join(SUITES)}")
    return value


def validate_surface(value: str | None) -> str:
    """``value`` as a surface; empty or None means ``chat``."""
    value = value or "chat"
    if value not in SURFACES:
        raise ConfigError(f"Unknown surface {value!r}. Choose from: {', '.join(SURFACES)}")
    return value


def validate_dimensions(suite: str, value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Validate the ``custom`` suite's dimension selection.

    Accepts a list (e.g. a repeated ``--dimension``), comma-separated entries or
    a mix; returns the distinct dimensions in canonical order. ``custom`` needs
    at least one, and the fixed suites take none.
    """
    raw = [value] if isinstance(value, str) else list(value or [])
    picked: set[str] = set()
    for item in raw:
        for part in str(item).split(","):
            name = part.strip().lower()
            if not name:
                continue
            if name not in DIMENSIONS:
                raise ConfigError(
                    f"Unknown dimension {name!r}. Choose from: {', '.join(DIMENSIONS)}"
                )
            picked.add(name)
    if suite == "custom" and not picked:
        raise ConfigError(
            f"The custom suite needs at least one dimension. Choose from: {', '.join(DIMENSIONS)}"
        )
    if suite != "custom" and picked:
        raise ConfigError(
            f"Dimensions can only be selected with the custom suite (got suite {suite!r})"
        )
    return [d for d in DIMENSIONS if d in picked]


def validate_format(value: str) -> str:
    if value not in FORMATS:
        raise ConfigError(f"Unknown format {value!r}. Choose from: {', '.join(FORMATS)}")
    return value


def validate_api(value: str | None) -> str:
    """Validate the wire-protocol selector; default to 'auto'."""
    if value is None:
        return "auto"
    if value not in APIS:
        raise ConfigError(f"Unknown api {value!r}. Choose from: {', '.join(APIS)}")
    return value


def validate_risk(value: str | None) -> str | None:
    """Validate a --fail-on-risk threshold up front.

    A typo here (e.g. ``--fail-on-risk hihg``) must fail loudly rather than silently
    disabling the CI gate, so an unknown value raises instead of being ignored.
    """
    if value is None:
        return None
    if value not in RISK_LEVELS:
        raise ConfigError(
            f"Unknown risk level {value!r}. Choose from: {', '.join(RISK_LEVELS)}"
        )
    return value


TEMPLATE = """\
# ekte configuration — LLM relay reality check
# Run:  ekte check -c ekte.yaml
# Docs: https://github.com/mn567250/ekte

version: 1                         # format version of this file

target:
  name: my-relay
  base_url: https://relay.example.com/v1
  api_key: env:EKTE_API_KEY        # env:VAR | file:/path | raw value
  model: gpt-4o
  api: auto                        # auto | openai | anthropic (wire protocol)
  declared_provider: openai        # optional; inferred from model id if omitted
  timeout_sec: 60                  # base HTTP timeout; grows with prompt and output size
  max_request_sec: 900             # hard cap per request (seconds)
  headers: {}

# Optional trusted baseline for `ekte compare` (strongest downgrade evidence).
baseline:
  name: openai-official
  base_url: https://api.openai.com/v1
  api_key: env:OPENAI_API_KEY
  model: gpt-4o

run:
  suite: standard                  # smoke | standard | deep | full | custom
  # dimensions: [protocol, performance]  # custom suite only: the dimensions to run
  judge: false                     # enable code+LLM hybrid judging
  output_dir: reports
  format: all                      # json | md | html | pdf | all
  reliability_requests: 8
  concurrency: 3
  max_context_probe_tokens: 200000 # cap for the real-context-window probe
  performance_requests: 100        # performance probe requests per endpoint (deep/full/custom; 0 disables)
  performance_max_tokens: 128      # output tokens per performance probe request
  performance_streaming: true      # probe mode on standard/deep/custom (full measures both)

# Optional LLM judge backend (used when run.judge is true).
# Defaults to the baseline endpoint if omitted.
judge:
  base_url: https://api.openai.com/v1
  api_key: env:OPENAI_API_KEY
  model: gpt-4o-mini
"""
