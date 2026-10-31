"""Render the command-line reference (docs/CLI.md) from the live Typer/Click app.

The reference is generated from the same option declarations ``--help`` shows, so
the two cannot drift: ``scripts/generate_cli_docs.py`` writes it, a test checks it.
"""

from __future__ import annotations

from typing import Any

import typer

from ekte import cli


def _walk(cmd: Any, path: tuple[str, ...]):
    """Yield ``(path, command)`` for every real (non-group) command, sorted by name."""
    if hasattr(cmd, "commands"):  # a group
        for name in sorted(cmd.commands):
            yield from _walk(cmd.commands[name], (*path, name))
    else:
        yield path, cmd


def commands() -> list[tuple[tuple[str, ...], Any]]:
    root = typer.main.get_command(cli.app)
    return list(_walk(root, ()))


def _first_line(text: str | None) -> str:
    return " ".join((text or "").strip().split("\n\n")[0].split())


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _option_row(p: Any) -> str:
    if p.param_type_name == "argument":
        name = f"`{p.name.upper()}`" + ("" if p.required else " (optional)")
        return f"| {name} | argument | | {_cell(getattr(p, 'help', '') or '')} |"
    names = ", ".join(f"`{n}`" for n in [*p.opts, *p.secondary_opts])
    kind = "flag" if p.is_flag else p.type.name.lower() + (" (repeatable)" if p.multiple else "")
    default = ""
    if p.default not in (None, False, "", ()) and not p.is_flag:
        default = f"`{p.default}`"
    return f"| {names} | {kind} | {default} | {_cell(p.help or '')} |"


def render() -> str:
    lines = [
        "# Command line reference",
        "",
        "<!-- Generated from `ekte --help` by scripts/generate_cli_docs.py; do not edit. -->",
        "",
        "The commands, options and exit codes below are public: see the",
        "[stability policy](STABILITY.md#surface-cli). This page is generated from the",
        "option declarations that `ekte <command> --help` prints, and a test fails when it",
        "is out of date. The English text is canonical.",
        "",
        "## Conventions",
        "",
        "- `--data-dir` is a global option and goes before the command:",
        "  `ekte --data-dir DIR check ...` (`serve` also accepts it after the command).",
        "- `--json` prints machine-readable JSON on stdout and nothing else; messages,",
        "  progress and warnings go to stderr. Where the result is a report it follows the",
        "  [report schema](SCHEMAS.md). `--compact` (audit commands) prints the lean verdict.",
        "- `--format` always means the report file format (`json|md|html|pdf|all`).",
        "- `--fail-on-risk` and `--fail-under` gate the exit code (1).",
        "- A renamed option keeps working with a deprecation warning on stderr that names",
        "  the replacement and the removal version (see",
        "  [Deprecated options](#deprecated-options)).",
        "- Long options use lowercase words joined by hyphens. Short options exist only for",
        "  `-c` (`--config`), `-H` (`--header`), `-D` (`--dimension`) and `-p` (`--path` of",
        "  `init`, `--port` of `serve`).",
        "",
        "## Exit codes",
        "",
        "Every command follows this table.",
        "",
        "| Code | Meaning | When |",
        "|---|---|---|",
    ]
    for code, (meaning, when) in cli.EXIT_CODES.items():
        lines.append(f"| {code} | {meaning} | {_cell(when)} |")
    lines += ["", "## Commands", ""]
    cmds = commands()
    lines.append(", ".join(f"[`ekte {' '.join(p)}`](#{'-'.join(p)})" for p, _ in cmds))
    lines.append("")
    root = typer.main.get_command(cli.app)
    lines += [
        "### Global options",
        "",
        "| Option | Type | Default | Description |",
        "|---|---|---|---|",
        *[_option_row(p) for p in root.params if p.param_type_name == "option" and p.name != "help"],
        "",
    ]
    for path, cmd in cmds:
        title = " ".join(path)
        lines += [f'<a id="{"-".join(path)}"></a>', f"### `ekte {title}`", "", _first_line(cmd.help), ""]
        params = [
            p for p in cmd.params
            if p.name != "help" and not getattr(p, "hidden", False)
        ]
        if params:
            lines += [
                "| Option | Type | Default | Description |",
                "|---|---|---|---|",
                *[_option_row(p) for p in params],
                "",
            ]
    lines += [
        "## Deprecated options",
        "",
        "These spellings still work, print a warning on stderr and are removed in ekte "
        f"{cli._DEPRECATED_REMOVAL}.",
        "",
        "| Command | Deprecated | Use instead |",
        "|---|---|---|",
    ]
    for path, cmd in cmds:
        for p in cmd.params:
            if p.param_type_name == "option" and getattr(p, "hidden", False):
                new = (p.help or "").rsplit("use ", 1)[-1].rstrip(".")
                lines.append(f"| `ekte {' '.join(path)}` | `{p.opts[0]}` | `{new}` |")
    return "\n".join(lines) + "\n"
