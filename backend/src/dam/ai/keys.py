"""The Anthropic API key in the macOS Keychain (service ``dam-anthropic``, account
``api-key``). It is read only when a call is made or its presence is asked; it is never
logged, never returned by the API and never written to a file.

Lookups run in a daemon thread with a timeout: a Keychain prompt no one sees (``dam
serve`` under launchd) must not hang a request.
"""

import threading
from collections.abc import Callable

from dam.errors import InvalidRequest

SERVICE = "dam-anthropic"
ACCOUNT = "api-key"
KEYCHAIN_TIMEOUT = 10.0  # seconds


class KeychainError(Exception):
    """The Keychain did not answer or refused (details stay out of messages)."""


def _with_timeout[T](work: Callable[[], T]) -> T:
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["value"] = work()
        except BaseException as e:  # noqa: BLE001 - reported as a KeychainError
            box["error"] = e

    worker = threading.Thread(target=run, name="dam-keychain", daemon=True)
    worker.start()
    worker.join(KEYCHAIN_TIMEOUT)
    if worker.is_alive():
        raise KeychainError("the Keychain did not answer")
    if "error" in box:
        raise KeychainError(f"Keychain error ({type(box['error']).__name__})")
    return box["value"]  # type: ignore[return-value]


def get_key() -> str | None:
    """The stored key, or None. ``KeychainError`` if the Keychain cannot be asked."""
    import keyring

    value = _with_timeout(lambda: keyring.get_password(SERVICE, ACCOUNT))
    return value if isinstance(value, str) and value else None


def has_key() -> bool:
    return get_key() is not None


def set_key(key: str) -> None:
    """Store ``key`` (one printable line, no spaces). ``InvalidRequest`` for anything else."""
    import keyring

    if not key or key != key.strip() or not key.isprintable() or any(c.isspace() for c in key):
        raise InvalidRequest("The key must be one line of printable text without spaces")
    _with_timeout(lambda: keyring.set_password(SERVICE, ACCOUNT, key))


def clear_key() -> None:
    """Remove the key; nothing happens if there is none."""
    import keyring
    import keyring.errors

    def work() -> None:
        try:
            keyring.delete_password(SERVICE, ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            pass

    _with_timeout(work)
