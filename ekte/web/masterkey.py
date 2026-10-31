"""The master key's life cycle: create, unlock, lock, rotate, reset.

The key that encrypts the monitors' API keys (:mod:`ekte.secretbox`) is never
stored in the data directory. ``ekte serve`` holds it in memory once it is
known, from ``EKTE_SECRET_KEY`` (headless / Docker), from a legacy
``secret.key`` an older version wrote (until the user moves it out), or from
the user, who enters it in the web UI after every start. Shared by the web
server and the ``ekte secret`` commands, so both follow the same rules.

States (:meth:`Vault.status`):

``uninitialized``  no key yet (no check value): ``new`` creates one
``locked``         a key exists but is not entered: ``unlock``, or ``reset``
                   when it is lost
``unlocked``       the key is in memory; from the UI or a legacy file it can
                   be replaced (``new``: rotate / move out) or locked again
``env_mismatch``   ``EKTE_SECRET_KEY`` is set but is not the key the stored
                   secrets use; only fixing the variable helps

Whether there is a master key at all is the user's choice: with key storage
``memory`` (:func:`ekte.web.watches.get_key_storage`, the default) no API key
is stored, so none is needed; :meth:`Vault.set_storage` switches between the
modes and moves the keys along.

A new key (first key, moving a legacy key out, rotation) is always the same
two steps: :meth:`Vault.begin_new` hands it out once, :meth:`Vault.confirm_new`
takes it back (pasted by the user) before anything is written, so the key in
use is always one the user has seen. Moving a legacy key out generates a new
key too, so a backup that holds the old ``secret.key`` stops being a risk.

Assumes one server process: the key lives in that process's memory.
"""

from __future__ import annotations

import hmac
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from ekte import secretbox
from ekte.web import watches

_log = logging.getLogger("ekte.web")

# How long a key handed out by begin_new waits to be confirmed.
PENDING_TTL_SEC = 600.0

SOURCE_UI = "ui"
SOURCE_ENV = secretbox.ENV
SOURCE_LEGACY = "legacy"


class VaultError(Exception):
    """An action that the current state does not allow, or a wrong input.

    ``status`` is the HTTP status the web API answers with.
    """

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


class Vault:
    """The process's master key and the rules for changing it."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self.reset_state()

    def reset_state(self) -> None:
        """Forget everything held in memory (as after a restart), the API keys
        that are not stored included."""
        with self._lock:
            secretbox.lock()
            watches.forget_memory_keys()
            self._canary_seen: str | None = None
            self._pending: tuple[str, float] | None = None
            self._env_error: str | None = None

    # ----- state ----------------------------------------------------------- #
    def startup(self) -> dict[str, Any]:
        """Load the key from ``EKTE_SECRET_KEY`` or a legacy file, if there is one.

        Called when the server starts (and by the CLI). A key already held is
        kept. Never raises: a broken variable or file is reported in the status.
        When no API key is stored (``memory``) no master key is loaded.
        """
        with self._lock:
            watches.init()
            if watches.settle_key_storage() == watches.STORAGE_ENCRYPTED:
                self._load_known()
            return self.status()

    def take_stored_keys(self) -> int:
        """When no API key may be stored, move the ones an older version left in
        the database (in plain text) into this process's memory. Only the
        server calls this: it is the process that runs the monitors."""
        with self._lock:
            if watches.get_key_storage() != watches.STORAGE_MEMORY:
                return 0
            try:
                moved = watches.keys_to_memory(secretbox.current())
            except secretbox.SecretError as exc:
                _log.warning("API keys: %s", exc)
                return 0
            if moved:
                _log.warning("moved %d stored API key(s) out of the database into memory", moved)
            return moved

    def _load_known(self) -> None:
        """Hold the key from ``EKTE_SECRET_KEY`` or a legacy file, if any."""
        if secretbox.current() is not None:
            return
        self._env_error = None
        try:
            box = secretbox.env_box()
        except secretbox.SecretError as exc:
            self._env_error = str(exc)
            box = None
        if box is None and self._env_error is None:
            try:
                box = secretbox.legacy_box()
            except secretbox.SecretError as exc:
                _log.warning("master key: %s", exc)
        if box is not None:
            self._adopt_known(box)

    def _adopt_known(self, box: secretbox.SecretBox) -> None:
        """Hold a key that came from the environment or a legacy file."""
        canary = watches.get_canary()
        if canary is None:
            # First start with this key: it becomes the store's key.
            watches.adopt_key(box)
        elif not secretbox.check_canary(box, canary):
            if box.source == SOURCE_ENV:
                self._env_error = (
                    f"{SOURCE_ENV} (fingerprint {box.fingerprint()}) is not the master key "
                    "the stored API keys were encrypted with"
                )
            else:
                _log.warning("legacy key file does not match the stored master key; ignored")
            return
        self._hold(box)

    def _hold(self, box: secretbox.SecretBox) -> None:
        migrated = watches.migrate_keys(box)
        if migrated:
            _log.warning("encrypted %d API key(s) that were stored in plain text", migrated)
        secretbox.unlock(box)
        self._canary_seen = watches.get_canary()

    def verify(self) -> bool:
        """Lock when the stored check value changed under us (another process
        rotated or reset the key). Cheap: one row read, no decryption.
        Returns whether a key is held afterwards."""
        with self._lock:
            if secretbox.current() is None:
                return False
            if watches.get_canary() != self._canary_seen:
                _log.warning("the master key was changed by another process; locked")
                self._forget()
                return False
            return True

    def status(self) -> dict[str, Any]:
        """What the UI and ``ekte secret status`` show; never the key itself."""
        with self._lock:
            box = secretbox.current()
            if box is not None:
                self.verify()
                box = secretbox.current()
            source = box.source if box is not None else None
            if box is not None:
                state = "unlocked"
            elif self._env_error is not None:
                state = "env_mismatch"
            elif watches.get_canary() is None:
                state = "uninitialized"
            else:
                state = "locked"
            actions = {
                "uninitialized": ["new"],
                "locked": ["unlock", "reset"],
                "unlocked": [] if source == SOURCE_ENV else ["new", "lock"],
                "env_mismatch": [],
            }[state]
            warnings = []
            if secretbox.legacy_key_file().exists():
                warnings.append("legacy_key_file")
            if secretbox.env_in_data_dir():
                warnings.append("env_in_data_dir")
            return {
                "storage": watches.get_key_storage(),
                "state": state,
                "source": source,
                "fingerprint": box.fingerprint() if box is not None else None,
                "actions": actions,
                "warnings": warnings,
                "error": self._env_error if state == "env_mismatch" else None,
                "counts": watches.key_counts(box),
            }

    def box(self) -> secretbox.SecretBox:
        """The held key; raises :class:`~ekte.secretbox.SecretLocked` without one."""
        return secretbox.default()

    def _require(self, action: str) -> dict[str, Any]:
        st = self.status()
        if action not in st["actions"]:
            raise VaultError(f"cannot {action} the master key while it is {st['state']}")
        return st

    # ----- actions --------------------------------------------------------- #
    def begin_new(self) -> str:
        """A new key to show the user once; the same one again until it expires."""
        with self._lock:
            self._require("new")
            now = self._clock()
            if self._pending is None or self._pending[1] <= now:
                self._pending = (secretbox.generate_key(), now + PENDING_TTL_SEC)
            return self._pending[0]

    def confirm_new(self, typed: str) -> dict[str, Any]:
        """Make the pending key the master key once the user typed it back."""
        with self._lock:
            self._require("new")
            pending = self._pending
            if pending is None or pending[1] <= self._clock():
                self._pending = None
                raise VaultError("the new key expired; start again", status=410)
            try:
                key = secretbox.parse_key(typed)
            except secretbox.SecretError as exc:
                raise VaultError(str(exc), status=400) from None
            if not hmac.compare_digest(key.encode("ascii"), pending[0].encode("ascii")):
                raise VaultError("that is not the key shown; paste it exactly", status=400)
            new = secretbox.SecretBox([key], SOURCE_UI)
            watches.adopt_key(new, opener=secretbox.current())
            self._pending = None
            self._hold(new)
            secretbox.remove_legacy_key_file()
            return self.status()

    def unlock(self, typed: str) -> dict[str, Any]:
        """Hold the key the user entered, if it opens the check value."""
        with self._lock:
            self._require("unlock")
            try:
                key = secretbox.parse_key(typed)
            except secretbox.SecretError as exc:
                raise VaultError(str(exc), status=400) from None
            box = secretbox.SecretBox([key], SOURCE_UI)
            # A Fernet key is 256 random bits: guessing is hopeless, so a wrong
            # key needs no rate limit, only a clear answer.
            if not secretbox.check_canary(box, watches.get_canary()):
                raise VaultError("wrong master key", status=403)
            self._hold(box)
            return self.status()

    def lock(self) -> dict[str, Any]:
        """Forget the key; monitors pause until it is entered again."""
        with self._lock:
            self._require("lock")
            self._forget()
            return self.status()

    def _forget(self) -> None:
        secretbox.lock()
        self._canary_seen = None
        self._pending = None

    def set_storage(self, mode: str) -> dict[str, Any]:
        """Switch between storing no API key (``memory``) and storing them
        encrypted, moving the keys along. The status gains ``moved``: how many
        keys changed place.

        To ``memory``: the encrypted keys are opened (raises SecretLocked when
        there are some and the master key is not entered), held in memory and
        erased from the database with the check value; the master key is then
        forgotten, a legacy ``secret.key`` removed. To ``encrypted``: needs a
        master key (from ``EKTE_SECRET_KEY``, else SecretLocked until one is
        created or entered); the keys held in memory are sealed into the database.
        """
        if mode not in watches.STORAGE_MODES:
            raise VaultError("mode must be one of: " + ", ".join(watches.STORAGE_MODES), 400)
        with self._lock:
            if mode == watches.get_key_storage():
                return {**self.status(), "moved": 0}
            if mode == watches.STORAGE_MEMORY:
                box = secretbox.current() if self.verify() else None
                moved = watches.keys_to_memory(box)
                self._forget()
                self._env_error = None
                secretbox.remove_legacy_key_file()
            else:
                self._load_known()
                box = secretbox.current()
                if box is None:
                    raise secretbox.SecretLocked("create or enter the master key first")
                moved = watches.keys_to_store(box)
            return {**self.status(), "moved": moved}

    def reset(self) -> int:
        """The key is lost: drop every encrypted API key and start over.

        Returns how many keys were dropped. Callers stop running monitors first.
        """
        with self._lock:
            self._require("reset")
            n = watches.forget_keys()
            secretbox.remove_legacy_key_file()
            self._pending = None
            return n


vault = Vault()
