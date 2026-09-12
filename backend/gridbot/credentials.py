"""Secrets persist only in macOS Keychain; other platforms are memory-only."""

import json
import sys
import threading
from typing import Any

from gridbot.errors import ValidationError
from gridbot.models import Credentials, Environment


class CredentialsStore:
    """Synchronous interface. API handlers should call it through to_thread.

    Never select an arbitrary keyring backend: plaintext keyrings are rejected.
    On Linux development credentials disappear when the process exits.
    """

    service = "Grid Hedge Bot Bybit"

    def __init__(self, *, keychain_backend: Any | None = None) -> None:
        self._lock = threading.RLock()
        self._memory: dict[Environment, Credentials] = {}
        self._keychain = keychain_backend
        if self._keychain is None and sys.platform == "darwin":
            try:
                from keyring.backends.macOS import Keyring

                self._keychain = Keyring()
            except Exception as exc:
                raise ValidationError(
                    "macOS Keychain non disponibile: nessun secret salvato"
                ) from exc

    @property
    def persistent(self) -> bool:
        return self._keychain is not None

    @property
    def storage_description(self) -> str:
        return "macOS Keychain" if self.persistent else "Memory only (development)"

    def save(self, credentials: Credentials) -> None:
        key = credentials.api_key.get_secret_value()
        secret = credentials.api_secret.get_secret_value()
        if not key.strip() or not secret.strip():
            raise ValidationError("API Key e API Secret sono obbligatori")
        if len(key) > 512 or len(secret) > 4096:
            raise ValidationError("Formato credenziali non valido")
        if any(char in key + secret for char in "\r\n\x00"):
            raise ValidationError("Formato credenziali non valido")
        with self._lock:
            if self._keychain is None:
                self._memory[credentials.environment] = credentials.model_copy(deep=True)
                return
            payload = json.dumps({"api_key": key, "api_secret": secret}, separators=(",", ":"))
            try:
                self._keychain.set_password(self.service, credentials.environment.value, payload)
            except Exception as exc:
                raise ValidationError("Salvataggio macOS Keychain fallito") from exc

    def load(self, environment: Environment) -> Credentials | None:
        environment = Environment(environment)
        with self._lock:
            if self._keychain is None:
                saved = self._memory.get(environment)
                return saved.model_copy(deep=True) if saved is not None else None
            try:
                payload = self._keychain.get_password(self.service, environment.value)
                if payload is None:
                    return None
                parsed = json.loads(payload)
                return Credentials(environment=environment, **parsed)
            except Exception as exc:
                raise ValidationError("Lettura macOS Keychain fallita") from exc

    def delete(self, environment: Environment) -> None:
        environment = Environment(environment)
        with self._lock:
            self._memory.pop(environment, None)
            if self._keychain is not None:
                try:
                    if self._keychain.get_password(self.service, environment.value) is not None:
                        self._keychain.delete_password(self.service, environment.value)
                except Exception as exc:
                    raise ValidationError("Rimozione macOS Keychain fallita") from exc


class MemoryCredentialsStore(CredentialsStore):
    """Explicit nonpersistent fixture for automated tests and backtests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._memory = {}
        self._keychain = None
