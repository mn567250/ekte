# Command line reference

<!-- Generated from `ekte --help` by scripts/generate_cli_docs.py; do not edit. -->

The commands, options and exit codes below are public: see the
[stability policy](STABILITY.md#surface-cli). This page is generated from the
option declarations that `ekte <command> --help` prints, and a test fails when it
is out of date. The English text is canonical.

## Conventions

- `--data-dir` is a global option and goes before the command:
  `ekte --data-dir DIR check ...` (`serve` also accepts it after the command).
- `--json` prints machine-readable JSON on stdout and nothing else; messages,
  progress and warnings go to stderr. Where the result is a report it follows the
  [report schema](SCHEMAS.md). `--compact` (audit commands) prints the lean verdict.
- `--format` always means the report file format (`json|md|html|pdf|all`).
- `--fail-on-risk` and `--fail-under` gate the exit code (1).
- A renamed option keeps working with a deprecation warning on stderr that names
  the replacement and the removal version (see
  [Deprecated options](#deprecated-options)).
- Long options use lowercase words joined by hyphens. Short options exist only for
  `-c` (`--config`), `-H` (`--header`), `-D` (`--dimension`) and `-p` (`--path` of
  `init`, `--port` of `serve`).

## Exit codes

Every command follows this table.

| Code | Meaning | When |
|---|---|---|
| 0 | success | The command succeeded; any gate passed. |
| 1 | gate or check failed | The risk is at or above `--fail-on-risk`, the score is below `--fail-under`, `kb-import` rejected the file, or `config migrate --check` found an outdated file. |
| 2 | usage or configuration error | Invalid option, value or configuration file, or a missing extra or master key. In `--json` and `--compact` mode an `{"error": {...}}` object is printed on stdout. |
| 3 | endpoint failure | `ekte models` could not list the models: the endpoint is unreachable or answered with an error. |
| 4 | internal error | An unexpected error in ekte itself; the traceback is on stderr. Please report it. |

## Commands

[`ekte audio`](#audio), [`ekte check`](#check), [`ekte compare`](#compare), [`ekte config migrate`](#config-migrate), [`ekte data-dir`](#data-dir), [`ekte embed`](#embed), [`ekte image`](#image), [`ekte init`](#init), [`ekte kb`](#kb), [`ekte kb-export`](#kb-export), [`ekte kb-import`](#kb-import), [`ekte kb-prompt`](#kb-prompt), [`ekte models`](#models), [`ekte rerank`](#rerank), [`ekte secret export`](#secret-export), [`ekte secret rotate`](#secret-rotate), [`ekte secret status`](#secret-status), [`ekte serve`](#serve), [`ekte watch`](#watch)

### Global options

| Option | Type | Default | Description |
|---|---|---|---|
| `--version` | flag |  | Show version and exit. |
| `--data-dir` | path |  | Where ekte keeps history.db, watches.db and kb.db (default ~/.ekte). Env: EKTE_DATA_DIR. |

<a id="audio"></a>
### `ekte audio`

Audit an audio/TTS endpoint (POST /v1/audio/speech, a non-chat surface).

| Option | Type | Default | Description |
|---|---|---|---|
| `--base-url` | str |  | Audio/TTS endpoint base URL, e.g. https://relay.example.com/v1. |
| `--api-key` | str |  | API key, or env:VAR / file:/path reference. |
| `--model` | str |  | TTS model id actually sent in requests. |
| `--claimed-model` | str |  | Model the relay claims to serve, if different from --model. |
| `--declared-provider` | str |  | Provider hint for KB lookup (openai, qwen, ...). |
| `--voice` | str | `alloy` | Voice id to request. |
| `--audio-format` | str |  | Requested audio format (wav\|mp3\|opus\|flac; default wav). |
| `--text` | str | `The quick brown fox jumps over the lazy dog.` | Probe sentence to synthesize. |
| `--save-to` | path |  | Write a synthesized clip to this path for inspection. |
| `--json` | flag |  | Print the verdict as JSON to stdout. |
| `--fail-on-risk` | str |  | Exit 1 if risk >= this (low\|medium\|high). |

<a id="check"></a>
### `ekte check`

Audit one relay endpoint and write a report.

| Option | Type | Default | Description |
|---|---|---|---|
| `--config`, `-c` | path |  | YAML config path. |
| `--base-url` | str |  | Relay base URL, e.g. https://relay.example.com/v1. |
| `--api-key` | str |  | API key, or env:VAR / file:/path reference. |
| `--model` | str |  | Model id actually sent in requests. |
| `--claimed-model` | str |  | Model the relay claims to serve, if different from --model (audits the real model against this profile). |
| `--name` | str |  | Display name for the target. |
| `--api` | str |  | Wire protocol: auto \| openai \| anthropic. |
| `--declared-provider` | str |  | Provider hint for KB lookup (openai, anthropic, deepseek, ...). |
| `--header`, `-H` | str (repeatable) |  | Extra header 'Name: value' (repeatable). |
| `--suite` | str |  | smoke \| standard \| deep \| full \| custom. |
| `--dimension`, `-D` | str (repeatable) |  | Dimension to run (repeatable or comma-separated); implies --suite custom: connectivity \| protocol \| context_window \| model_identity \| capability \| streaming \| billing \| reliability \| security \| performance. |
| `--judge`, `--no-judge` | flag |  | Enable code+LLM hybrid judging. |
| `--judge-base-url` | str |  | Trusted judge endpoint base URL. |
| `--judge-api-key` | str |  | Judge API key (env:VAR ok). |
| `--judge-model` | str |  | Judge model id. |
| `--only` | str (repeatable) |  | Run only these detector ids (repeatable). |
| `--skip` | str (repeatable) |  | Skip these detector ids (repeatable). |
| `--out-dir` | path |  | Report output directory. |
| `--format` | str |  | json \| md \| html \| pdf \| all (pdf needs the [pdf] extra). |
| `--timeout` | float |  | Base HTTP timeout (seconds); grows with prompt and output size. |
| `--max-request-time` | float |  | Hard cap for one request (seconds, default 900). |
| `--reliability-requests` | int |  | Reliability probe request count (0 disables). |
| `--concurrency` | int |  | Reliability probe concurrency. |
| `--max-context-tokens` | int |  | Cap for the real-context-window probe. |
| `--performance-requests` | int |  | Performance probe requests per endpoint (deep/full/custom; 0 disables). |
| `--performance-max-tokens` | int |  | Output tokens per performance probe request. |
| `--performance-streaming`, `--performance-non-streaming` | flag |  | Probe with streaming or non-streaming requests (standard/deep/custom; full measures both). |
| `--kb-dir` | path (repeatable) |  | Extra knowledge-base directory (repeatable). |
| `--no-user-kb` | flag |  | Ignore the knowledge-base entries you added in the web UI (kb.db); packaged profiles and EKTE_KB_DIR still apply. Env: EKTE_NO_USER_KB=1. |
| `--fail-under` | float |  | Exit 1 if overall score < this. |
| `--fail-on-risk` | str |  | Exit 1 if risk >= this (low\|medium\|high). |
| `--json` | flag |  | Print the full JSON report to stdout instead of writing files. |
| `--compact` | flag |  | Print a lean agent/LLM-facing JSON verdict to stdout (much smaller than --json). |
| `--dry-run` | flag |  | Show which detectors would run and the estimated API-call count, without making any requests. |

<a id="compare"></a>
### `ekte compare`

Audit a relay against a trusted baseline of the same declared model.

| Option | Type | Default | Description |
|---|---|---|---|
| `--config`, `-c` | path |  | YAML config path. |
| `--target-base-url` | str |  | Target relay base URL. |
| `--target-api-key` | str |  | Target API key (env:VAR ok). |
| `--target-model` | str |  | Target model id. |
| `--target-name` | str |  | Target display name. |
| `--target-api` | str |  | Target wire protocol: auto \| openai \| anthropic. |
| `--declared-provider` | str |  | Provider hint for KB lookup. |
| `--baseline-base-url` | str |  | Trusted baseline base URL. |
| `--baseline-api-key` | str |  | Baseline API key (env:VAR ok). |
| `--baseline-model` | str |  | Baseline model id. |
| `--baseline-name` | str |  | Baseline display name. |
| `--baseline-api` | str |  | Baseline wire protocol: auto \| openai \| anthropic. |
| `--suite` | str |  | smoke \| standard \| deep \| full \| custom. |
| `--dimension`, `-D` | str (repeatable) |  | Dimension to run (repeatable or comma-separated); implies --suite custom: connectivity \| protocol \| context_window \| model_identity \| capability \| streaming \| billing \| reliability \| security \| performance. |
| `--judge`, `--no-judge` | flag |  | Enable code+LLM hybrid judging. |
| `--judge-model` | str |  | Judge model id (defaults to baseline). |
| `--out-dir` | path |  | Report output directory. |
| `--format` | str |  | json \| md \| html \| pdf \| all (pdf needs the [pdf] extra). |
| `--timeout` | float |  | Base HTTP timeout (seconds); grows with prompt and output size. |
| `--max-request-time` | float |  | Hard cap for one request (seconds, default 900). |
| `--max-context-tokens` | int |  | Cap for the context-window probe. |
| `--performance-requests` | int |  | Performance probe requests per endpoint (0 disables; standard suite uses 5). |
| `--performance-max-tokens` | int |  | Output tokens per performance probe request. |
| `--performance-streaming`, `--performance-non-streaming` | flag |  | Probe with streaming or non-streaming requests (standard/deep/custom; full measures both). |
| `--kb-dir` | path (repeatable) |  | Extra knowledge-base directory (repeatable). |
| `--no-user-kb` | flag |  | Ignore the knowledge-base entries you added in the web UI (kb.db); packaged profiles and EKTE_KB_DIR still apply. Env: EKTE_NO_USER_KB=1. |
| `--fail-under` | float |  | Exit 1 if overall score < this. |
| `--fail-on-risk` | str |  | Exit 1 if risk >= this. |
| `--json` | flag |  | Print the full JSON report to stdout. |
| `--compact` | flag |  | Print a lean agent/LLM-facing JSON verdict to stdout. |
| `--dry-run` | flag |  | Show the detectors and estimated API calls without making requests. |

<a id="config-migrate"></a>
### `ekte config migrate`

Rewrite a config file to the current format (comments are kept).

| Option | Type | Default | Description |
|---|---|---|---|
| `PATH` (optional) | argument | | The config file to update. |
| `--check` | flag |  | Only report; exit 1 if the file is outdated. |
| `--json` | flag |  | Print the result as JSON. |

<a id="data-dir"></a>
### `ekte data-dir`

Print the data directory: history.db, watches.db and kb.db (plain SQLite).

| Option | Type | Default | Description |
|---|---|---|---|
| `--json` | flag |  | Print the result as JSON. |

<a id="embed"></a>
### `ekte embed`

Audit an embeddings endpoint (a non-chat surface).

| Option | Type | Default | Description |
|---|---|---|---|
| `--base-url` | str |  | Embedding endpoint base URL, e.g. https://relay.example.com/v1. |
| `--api-key` | str |  | API key, or env:VAR / file:/path reference. |
| `--model` | str |  | Embedding model id actually sent in requests. |
| `--claimed-model` | str |  | Model the relay claims to serve, if different from --model (resolves the claimed dimension from the KB). |
| `--declared-provider` | str |  | Provider hint for KB lookup (openai, qwen, ...). |
| `--claimed-dimensions` | int |  | Override the expected vector dimension instead of resolving it from the KB (0 = unknown). |
| `--suite` | str | `standard` | smoke \| standard \| deep \| full (deep/full add the performance probe). |
| `--save`, `--no-save` | flag |  | Save the report to the local history (the next run's vector-drift reference). |
| `--kb-dir` | path (repeatable) |  | Extra knowledge-base directory (repeatable). |
| `--json` | flag |  | Print the verdict as JSON to stdout. |
| `--fail-on-risk` | str |  | Exit 1 if risk >= this (low\|medium\|high). |
| `--dry-run` | flag |  | Show the detectors and estimated API calls without making requests. |

<a id="image"></a>
### `ekte image`

Audit an image-generation endpoint (POST /v1/images/generations, a non-chat surface).

| Option | Type | Default | Description |
|---|---|---|---|
| `--base-url` | str |  | Image endpoint base URL, e.g. https://relay.example.com/v1. |
| `--api-key` | str |  | API key, or env:VAR / file:/path reference. |
| `--model` | str |  | Image model id actually sent in requests. |
| `--claimed-model` | str |  | Model the relay claims to serve, if different from --model (resolves the native sizes from the KB). |
| `--declared-provider` | str |  | Provider hint for KB lookup (openai, qwen, ...). |
| `--size` | str | `1024x1024` | Requested image size as WxH. |
| `--save-to` | path |  | Write the first generated image to this path for inspection. |
| `--kb-dir` | path (repeatable) |  | Extra knowledge-base directory (repeatable). |
| `--json` | flag |  | Print the verdict as JSON to stdout. |
| `--fail-on-risk` | str |  | Exit 1 if risk >= this (low\|medium\|high). |

<a id="init"></a>
### `ekte init`

Write a starter ekte.yaml config.

| Option | Type | Default | Description |
|---|---|---|---|
| `--path`, `-p` | path | `ekte.yaml` | Where to write the config. |
| `--force` | flag |  | Overwrite if it exists. |

<a id="kb"></a>
### `ekte kb`

Inspect the knowledge base: packaged profiles, EKTE_KB_DIR and your own entries.

| Option | Type | Default | Description |
|---|---|---|---|
| `PROVIDER` (optional) | argument | | Filter by provider key (openai, deepseek, ...). |
| `--kb-dir` | path (repeatable) |  | Extra knowledge-base directory. |
| `--json` | flag |  | Print the knowledge base as JSON (for programmatic discovery). |
| `--no-user-kb` | flag |  | Ignore the knowledge-base entries you added in the web UI (kb.db); packaged profiles and EKTE_KB_DIR still apply. Env: EKTE_NO_USER_KB=1. |

<a id="kb-export"></a>
### `ekte kb-export`

Print your own knowledge-base entries (kb.db) as provider YAML.

| Option | Type | Default | Description |
|---|---|---|---|
| `--provider` | str |  | Only this provider. |

<a id="kb-import"></a>
### `ekte kb-import`

Check a profile YAML and store it in your knowledge base (kb.db in the data directory).

| Option | Type | Default | Description |
|---|---|---|---|
| `PATH` | argument | | Provider YAML file (e.g. an AI assistant's answer to `ekte kb-prompt`). |
| `--check` | flag |  | Only check the file; store nothing. |
| `--json` | flag |  | Print the check result as JSON. |

<a id="kb-prompt"></a>
### `ekte kb-prompt`

Print a research prompt for an external AI assistant; import its YAML answer with `ekte kb-import`.

| Option | Type | Default | Description |
|---|---|---|---|
| `MODEL` | argument | | Model id to research. |
| `--provider` | str |  | Provider key, if known. |

<a id="models"></a>
### `ekte models`

List the models an endpoint advertises via GET /v1/models.

| Option | Type | Default | Description |
|---|---|---|---|
| `--base-url` | str |  | Endpoint base URL. |
| `--api-key` | str |  | API key (env:VAR ok). |
| `--model` | str | `x` | A model id (for the client; not required to list). |
| `--api` | str |  | Wire protocol: auto \| openai \| anthropic. |
| `--json` | flag |  | Print the model list as JSON. |

<a id="rerank"></a>
### `ekte rerank`

Audit a rerank endpoint (a non-chat surface).

| Option | Type | Default | Description |
|---|---|---|---|
| `--base-url` | str |  | Rerank endpoint base URL, e.g. https://relay.example.com/v1. |
| `--api-key` | str |  | API key, or env:VAR / file:/path reference. |
| `--model` | str |  | Rerank model id actually sent in requests. |
| `--claimed-model` | str |  | Model the relay claims to serve, if different from --model. |
| `--declared-provider` | str |  | Provider hint for KB lookup (cohere, jina, ...). |
| `--suite` | str | `standard` | smoke \| standard \| deep \| full (deep/full add the performance probe). |
| `--save`, `--no-save` | flag |  | Save the report to the local history (the next run's ranking-drift reference). |
| `--kb-dir` | path (repeatable) |  | Extra knowledge-base directory (repeatable). |
| `--json` | flag |  | Print the verdict as JSON to stdout. |
| `--fail-on-risk` | str |  | Exit 1 if risk >= this (low\|medium\|high). |
| `--dry-run` | flag |  | Show the detectors and estimated API calls without making requests. |

<a id="secret-export"></a>
### `ekte secret export`

Print the master key from EKTE_SECRET_KEY or a legacy key file, to back it up.

<a id="secret-rotate"></a>
### `ekte secret rotate`

Generate a new master key and re-encrypt every stored API key with it.

<a id="secret-status"></a>
### `ekte secret status`

Whether the master key is set up and where it comes from, and the stored keys' state.

| Option | Type | Default | Description |
|---|---|---|---|
| `--json` | flag |  | Print the status as JSON. |

<a id="serve"></a>
### `ekte serve`

Serve the local web UI — a point-and-click front end for `ekte check`.

| Option | Type | Default | Description |
|---|---|---|---|
| `--host` | str |  | Loopback bind address: 127.0.0.1 (default), ::1 or localhost. Env: EKTE_HOST. |
| `--port`, `-p` | int |  | Port to serve on (default 8000). Env: EKTE_PORT. |
| `--open`, `--no-open` | flag |  | Open the UI in a browser (default: yes, except in a container). |
| `--data-dir` | path |  | Where ekte keeps history.db, watches.db and kb.db (default ~/.ekte). Env: EKTE_DATA_DIR. |

<a id="watch"></a>
### `ekte watch`

Continuously re-audit a relay on a schedule and alert webhooks on risk.

| Option | Type | Default | Description |
|---|---|---|---|
| `--config`, `-c` | path |  | YAML config path (reuses the same [target]/[run] shape as `check`). |
| `--base-url` | str |  | Relay base URL, e.g. https://relay.example.com/v1. |
| `--api-key` | str |  | API key, or env:VAR / file:/path reference. |
| `--model` | str |  | Model id actually sent in requests. |
| `--claimed-model` | str |  | Model the relay claims to serve, if different from --model. |
| `--name` | str |  | Display name for the target. |
| `--api` | str |  | Wire protocol: auto \| openai \| anthropic. |
| `--declared-provider` | str |  | Provider hint for KB lookup. |
| `--header`, `-H` | str (repeatable) |  | Extra header 'Name: value' (repeatable). |
| `--suite` | str |  | smoke \| standard \| deep \| full \| custom. |
| `--dimension`, `-D` | str (repeatable) |  | Dimension to run (repeatable or comma-separated); implies --suite custom: connectivity \| protocol \| context_window \| model_identity \| capability \| streaming \| billing \| reliability \| security \| performance. |
| `--interval` | int | `3600` | Seconds between re-audit cycles. |
| `--once` | flag |  | Run a single cycle and exit (no loop). |
| `--webhook` | str (repeatable) |  | Alert webhook URL (repeatable). |
| `--webhook-kind` | str | `auto` | auto \| slack \| feishu \| dingtalk \| generic. |
| `--alert-on` | str | `medium` | Alert when risk >= this: low \| medium \| high. |
| `--alert-on-regression`, `--no-alert-on-regression` | flag |  | Also alert when risk is worse than the previous saved run for this target+model. |
| `--alert-lang` | str | `en` | Language of the webhook alerts: en \| zh \| fr \| es \| pt \| it \| de \| nb. |
| `--json` | flag |  | Print one JSON object per cycle (JSON Lines) on stdout; progress goes to stderr. |

## Deprecated options

These spellings still work, print a warning on stderr and are removed in ekte 1.0.0.

| Command | Deprecated | Use instead |
|---|---|---|
| `ekte audio` | `--format` | `--audio-format` |
| `ekte audio` | `--save` | `--save-to` |
| `ekte image` | `--save` | `--save-to` |
