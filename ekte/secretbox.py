"""Encryption at rest for secrets zing stores locally (the watch API keys).

A stored secret is sealed as ``enc:v1:<Fernet token>``: AES-128-CBC with an
HMAC-SHA256 tag, from ``cryptography`` (part of the ``web`` extra, the only
place secrets are stored). Values that are only pointers to a secret
(``env:VAR`` / ``file:/path``, see :func:`zing.config.resolve_secret`) and the
empty string are stored as is, and so is :data:`MEMORY`, the marker of a key
that is deliberately not stored (it is held in the server's memory only, see
:mod:`zing.web.watches`).

The master key is never written to the data directory. It lives in this
process's memory only (:func:`unlock` / :func:`lock` / :func:`current`), put
there by :mod:`zing.web.masterkey` from, in order:

1. ``ZING_SECRET_KEY`` — itself resolved with :func:`~zing.config.resolve_secret`,
   so a literal key, ``env:OTHER`` or ``file:/run/secrets/zing_key`` all work.
   A comma-separated list rotates: the first key seals, every key opens.
2. A legacy ``<data dir>/secret.key`` written by older versions — read (never
   created) until the user moves the key out, which also replaces it.
3. The user, who enters it in the web UI (or at the CLI prompt) after each
   start of ``zing serve``.

A *check value* (:func:`make_canary`) sealed with the key is stored next to
the secrets it protects, so a wrong key is rejected even with nothing stored.

Threat model: a copy of the data directory (a backup, a synced folder, a
support bundle) does not expose the stored keys. Someone who can read the
memory of the running server, or is root on its host, still can.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import threading
from pathlib import Path
from typing import Any

from zing import datadir

PREFIX = "enc:v1:"
_REFERENCES = ("env:", "file:")
# Stored in place of a key that is held in memory only: it holds no secret.
MEMORY = "mem:"
_KEY_FILE = "secret.key"
ENV = "ZING_SECRET_KEY"


# Sealed into the check value; opening it back proves a key is the right one.
_CANARY = "zing-canary-v1"


class SecretError(Exception):
    """A secret could not be sealed or opened (missing extra, bad or wrong key)."""


class SecretLocked(SecretError):
    """No master key is loaded: it has to be entered (UI or CLI) first."""


def _fernet() -> Any:
    try:
        from cryptography import fernet
    except ImportError as exc:  # pragma: no cover - the web extra ships it
        raise SecretError(
            "encrypting stored keys needs the 'cryptography' package: "
            "pip install 'zing-audit[web]'"
        ) from exc
    return fernet


def generate_key() -> str:
    return str(_fernet().Fernet.generate_key().decode("ascii"))


def is_sealed(stored: str | None) -> bool:
    return bool(stored) and str(stored).startswith(PREFIX)


def is_reference(stored: str | None) -> bool:
    return bool(stored) and str(stored).startswith(_REFERENCES)


def is_memory(stored: str | None) -> bool:
    return bool(stored) and str(stored).startswith(MEMORY)


def needs_seal(stored: str | None) -> bool:
    """True for a raw secret still stored in plain text."""
    return (
        bool(stored) and not is_sealed(stored) and not is_reference(stored) and not is_memory(stored)
    )


class SecretBox:
    """Seal and open secrets with a list of keys (first seals, all open)."""

    def __init__(self, keys: list[str], source: str = "") -> None:
        if not keys:
            raise SecretError("no secret key given")
        fernet = _fernet()
        try:
            self._multi = fernet.MultiFernet([fernet.Fernet(k.encode("ascii")) for k in keys])
        except (ValueError, TypeError, UnicodeEncodeError) as exc:
            raise SecretError(f"invalid secret key from {source or 'input'}: {exc}") from exc
        self._invalid = fernet.InvalidToken
        self.keys = list(keys)
        self.source = source

    def fingerprint(self) -> str:
        """First 8 hex chars of SHA-256 of the sealing key — safe to show."""
        return hashlib.sha256(self.keys[0].encode("ascii")).hexdigest()[:8]

    def cache_id(self) -> str:
        """Identifies the whole key list (what :meth:`open` accepts), for caches."""
        return hashlib.sha256(",".join(self.keys).encode("ascii")).hexdigest()

    def seal(self, plain: str | None) -> str:
        if not plain:
            return ""
        if not needs_seal(plain):
            return str(plain)
        return PREFIX + self._multi.encrypt(str(plain).encode("utf-8")).decode("ascii")

    def open(self, stored: str | None) -> str:
        if not stored:
            return ""
        if not is_sealed(stored):
            return str(stored)
        try:
            return str(self._multi.decrypt(str(stored)[len(PREFIX):].encode("ascii")).decode("utf-8"))
        except (self._invalid, UnicodeError) as exc:
            raise SecretError(
                f"stored key cannot be decrypted with the key from {self.source} "
                f"(fingerprint {self.fingerprint()}): wrong or rotated-away master key"
            ) from exc

    def can_open(self, stored: str | None) -> bool:
        try:
            self.open(stored)
        except SecretError:
            return False
        return True

    def reseal(self, stored: str | None) -> str:
        """Re-encrypt a sealed value with the first key; seal a plain one."""
        if is_sealed(stored):
            return self.seal(self.open(stored))
        return self.seal(stored)


def parse_key(value: str) -> str:
    """A single master key as typed or pasted: whitespace trimmed, format checked.

    The error never repeats the value, so it is safe to show or log.
    """
    key = "".join(str(value or "").split())
    try:
        SecretBox([key], "input")
    except SecretError:
        raise SecretError("not a zing master key (44 characters, letters, digits, - and _)") from None
    return key


def make_canary(box: SecretBox) -> str:
    """The check value for ``box``: a known constant sealed with its first key."""
    return PREFIX + box._multi.encrypt(_CANARY.encode("ascii")).decode("ascii")


def check_canary(box: SecretBox, stored: str | None) -> bool:
    """True when ``box`` opens the check value ``stored``."""
    if not is_sealed(stored):
        return False
    try:
        return box.open(stored) == _CANARY
    except SecretError:
        return False


# --------------------------------------------------------------------------- #
# Where the key comes from
# --------------------------------------------------------------------------- #
def _split(value: str) -> list[str]:
    return [k.strip() for k in value.split(",") if k.strip()]


def env_box() -> SecretBox | None:
    """The box from ``ZING_SECRET_KEY``, or None when it is unset."""
    from zing.config import resolve_secret

    raw = os.environ.get(ENV, "").strip()
    if not raw:
        return None
    try:
        value = resolve_secret(raw)
    except Exception as exc:
        raise SecretError(f"{ENV}: {exc}") from exc
    keys = _split(value)
    if not keys:
        raise SecretError(f"{ENV} is set but resolves to no key")
    return SecretBox(keys, ENV)


def env_in_data_dir() -> bool:
    """True when ``ZING_SECRET_KEY=file:`` points inside the data directory."""
    raw = os.environ.get(ENV, "").strip()
    if not raw.startswith("file:"):
        return False
    try:
        path = Path(raw[len("file:"):]).expanduser().resolve()
        return path.is_relative_to(datadir.data_dir().expanduser().resolve())
    except (OSError, ValueError):
        return False


def legacy_key_file() -> Path:
    """Where versions before the UI-managed key kept it (next to the databases)."""
    return datadir.db_path(_KEY_FILE)


def legacy_box() -> SecretBox | None:
    """The box from a legacy ``secret.key``, or None when there is none."""
    path = legacy_key_file()
    if not path.exists():
        return None
    try:
        keys = _split(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError) as exc:
        raise SecretError(f"cannot read secret key file {path}: {exc}") from exc
    if not keys:
        raise SecretError(f"secret key file {path} is empty")
    return SecretBox(keys, "legacy")


def remove_legacy_key_file() -> None:
    """Delete a legacy key file (and a rotation's leftover ``.tmp``)."""
    path = legacy_key_file()
    for p in (path, path.with_name(path.name + ".tmp")):
        with contextlib.suppress(FileNotFoundError):
            p.unlink()


# --------------------------------------------------------------------------- #
# The key held by this process
# --------------------------------------------------------------------------- #
_held: SecretBox | None = None
_held_lock = threading.Lock()


def unlock(box: SecretBox) -> None:
    """Hold ``box`` as this process's master key (memory only)."""
    global _held
    with _held_lock:
        _held = box


def lock() -> None:
    """Forget the held master key."""
    global _held
    with _held_lock:
        _held = None


def current() -> SecretBox | None:
    """The held master key, or None while locked."""
    return _held


def default() -> SecretBox:
    """The held master key; raises :class:`SecretLocked` while there is none."""
    box = _held
    if box is None:
        raise SecretLocked("the master key is locked: enter it to use stored API keys")
    return box
