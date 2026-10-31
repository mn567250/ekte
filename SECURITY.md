# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue for a
vulnerability.

- Preferred: use GitHub's **private vulnerability reporting** on this repository
  (the **Security** tab → *Report a vulnerability*), which opens a draft advisory
  visible only to maintainers.
- We aim to acknowledge a report within a few days and to provide a remediation
  plan or fix timeline once triaged.

When reporting, please include the affected version, reproduction steps, and the
impact you observed.

## Scope

ekte is a local-first auditing tool. The security properties that matter most:

- **Credential handling.** API keys are fingerprinted (SHA-256, truncated) and
  never stored verbatim. Reports and logs route every relay-controlled string
  through the redactor (`ekte/utils/redact.py`) before serialization. A path that
  lets a configured key or another secret reach a JSON/Markdown/HTML report is an
  in-scope vulnerability.
- **Monitor keys.** By default `ekte serve` does not store a monitor's API key:
  `watches.db` holds only the marker `mem:` and the key stays in the server's
  memory until it stops (`ekte/web/watches.py`). Storing keys is opt-in
  (**API key storage** on the Monitors page,
  `POST /api/secret/storage`); switching back erases the encrypted keys and the
  check value from `watches.db` and scrubs SQLite's free pages and WAL. A path
  that writes a key in clear to disk, or stores one while storage is off, is an
  in-scope vulnerability.
- **Stored monitor keys.** When the user opts in, `ekte serve` keeps each
  monitor's API key in `watches.db`, encrypted with Fernet (`ekte/secretbox.py`). The master key is
  **never written to the data directory**: the Monitors page shows it once
  when it is created, the user keeps it (password manager, the browser's
  vault) and enters it again after every restart; until then the server holds
  it only in memory and monitors that need it wait. Headless setups pass it as
  `EKTE_SECRET_KEY` (a key, or an `env:`/`file:` reference such as
  `file:/run/secrets/ekte_key`), kept outside the data directory. Only a check
  value sealed with the key is stored, to reject a wrong key. A copy of the
  data directory (backup, synced folder, support bundle) therefore reveals no
  API key. Not covered: someone who can read the running server's memory or
  is root on its host. A `secret.key` left by an older version is still read,
  until the user moves it out, which replaces it with a new key so old backups
  holding it become useless. A lost key can only be reset, which drops the
  stored API keys. The key-handling routes (`/api/secret/*`) answer with
  `Cache-Control: no-store`, never echo a submitted key, and sit behind the
  same local-only checks as the rest of the UI.
- **Untrusted input.** Relay responses are untrusted by design. Report renderers
  must neutralize relay-controlled text (HTML-escape, Markdown-escape) so it
  cannot inject markup or spoof report structure.
- **No surprising egress.** ekte only contacts the endpoints you configure (the
  target, an optional baseline, an optional judge, and monitor webhooks). It
  downloads nothing at runtime, not even tokenizer files. A change that sends
  data elsewhere or fetches anything at runtime is in scope.

## Responsible use (not a vulnerability)

ekte reports *black-box evidence of divergence and risk*, not proof of fraud. It
cannot prove a provider logs prompts, always routes to one exact model, or
commits billing fraud. Publishing an accusation against a vendor based on a single
run is a misuse of the tool, not a security issue — see the "Responsible use"
section of the README and `docs/METHODOLOGY.md`.
