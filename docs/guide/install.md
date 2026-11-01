# Install

> **🇬🇧 English** · [🇨🇳 中文](../i18n/zh-CN/guide/install.md) · [🇫🇷 Français](../i18n/fr/guide/install.md) · [🇪🇸 Español](../i18n/es/guide/install.md) · [🇵🇹 Português](../i18n/pt/guide/install.md) · [🇮🇹 Italiano](../i18n/it/guide/install.md) · [🇩🇪 Deutsch](../i18n/de/guide/install.md) · [🇳🇴 Norsk](../i18n/nb/guide/install.md)

Requires Python 3.11+. Runs on Linux, macOS and Windows (the Docker image is Linux); on Windows the owner-only data directory modes have no effect, see [Supported operating systems](../reference/stability.md#os). Every option below provides the `ekte` command.

## With pip

```bash
# from PyPI
pip install ekte

# or from source
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e .
```

## With [uv](https://docs.astral.sh/uv/)

```bash
# from PyPI, as a standalone tool on your PATH
uv tool install ekte

# or run it once without installing
uvx --from ekte ekte --help

# or from source, into a project-local virtual environment
git clone https://github.com/mn567250/ekte
cd ekte
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

You can also install straight from the Git repository without cloning:
`uv tool install git+https://github.com/mn567250/ekte`.

## Optional extras

- `web` — the local web UI (`ekte serve`).

```bash
pip install 'ekte[web]'      # pip, from PyPI
pip install -e '.[web]'            # pip, from source
uv tool install 'ekte[web]'  # uv, from PyPI
uv pip install -e '.[web]'         # uv, from source
```

The `tokenizers` extra is no longer needed: it is empty and kept
only so older install commands still work. ekte counts tokens with a built-in
heuristic and downloads nothing at runtime (no tokenizer files), so it also
runs in restricted or offline environments that only reach the relays you
audit.

PDF reports (`--format pdf`, and the PDF download in the web UI) need no extra: they
are typeset with [ReportLab](https://www.reportlab.com/opensource/), a pure Python
dependency that needs no system libraries on Linux, macOS or Windows.

## With Docker (web UI only)

From a source checkout:

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# open http://localhost:8000
```

Always publish the port to `127.0.0.1` as shown. Environment variables and what
protects the UI: [Docker](docker.md).
