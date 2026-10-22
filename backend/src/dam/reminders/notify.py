"""Sending due reminders: macOS notification and optional e-mail to self.

What leaves the app is the item's title, tray name, date and amount — never document
text. Every string goes through ``plain`` (no control or bidi characters).
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
import subprocess
import sys
import threading
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from typing import TYPE_CHECKING, Protocol

from dam.config import EmailSettings, Settings
from dam.core.fs import open_nofollow
from dam.reminders.engine import Due, collapse, due_reminders, latest_occasions, mark_sent

if sys.platform == "win32":
    import msvcrt

    fcntl = None
else:
    import fcntl

    msvcrt = None

if TYPE_CHECKING:
    from dam.app import App

log = logging.getLogger(__name__)

OSASCRIPT = "/usr/bin/osascript"
KEYRING_SERVICE = "dam-reminders"
ARCHIVE_NOTE = "files can't be opened right now"
MAX_TITLES = 3
KEYCHAIN_TIMEOUT = 10.0  # seconds
IMPLICIT_TLS_PORT = 465
LOCK_NAME = "remind.lock"
SKIPPED_BUSY = "another run in progress"
_BIDI = frozenset("؜‎‏‪‫‬‭‮⁦⁧⁨⁩")


class NotifyError(Exception):
    """A channel could not deliver; the message is shown to the user."""


class Notifier(Protocol):
    id: str

    def send(self, dues: list[Due], note: str | None = None) -> None:
        """Deliver ``dues`` as one message; raise on failure."""
        ...


def plain(text: str) -> str:
    """One line of plain text: line breaks/tabs become spaces, control and bidi
    characters are dropped, runs of spaces collapse."""
    out = []
    for ch in str(text):
        if ch in "\r\n\t\v\f  \x85":
            out.append(" ")
        elif ch in _BIDI or unicodedata.category(ch) == "Cc":
            continue
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def _date(d) -> str:
    return d.strftime("%d.%m.%Y")


def _money(amount) -> str:
    return f"{amount:.2f}".replace(".", ",") + " €"


def _by_date(dues: Sequence[Due]) -> list[Due]:
    """Soonest date first; undated ones (nudges) last."""
    return sorted(dues, key=lambda d: (d.date is None, d.date or d.occasion, d.item_id))


NO_NOTIFY = "not available on this platform"


def _lock(lock) -> None:
    """Exclusive non-blocking lock on the open file ``lock``; ``BlockingIOError`` if taken."""
    if fcntl is not None:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise BlockingIOError from None


def _unlock(lock) -> None:
    if fcntl is not None:
        fcntl.flock(lock, fcntl.LOCK_UN)
    else:
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


def _applescript(text: str) -> str:
    return '"' + plain(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


class MacNotifier:
    """One ``display notification`` per run: up to three titles, then "+N more".

    Off macOS ``send`` raises "not available on this platform" (on macOS without
    ``osascript``: "not available") instead of doing nothing: a channel that cannot
    deliver must never count as delivered.
    Failures are reported generically; osascript's own output is not passed on.
    """

    id = "mac"

    @classmethod
    def from_settings(cls, settings: Settings) -> MacNotifier | None:
        return cls() if settings.reminders.mac else None

    def send(self, dues: list[Due], note: str | None = None) -> None:
        if not dues:
            return
        if sys.platform != "darwin":
            raise NotifyError(NO_NOTIFY)
        if not os.access(OSASCRIPT, os.X_OK):
            raise NotifyError("not available")
        ordered = _by_date(dues)
        message = ", ".join(plain(d.title) for d in ordered[:MAX_TITLES])
        if len(ordered) > MAX_TITLES:
            message += f" +{len(ordered) - MAX_TITLES} more"
        script = f'display notification {_applescript(message)} with title "Archive"'
        dated = [d.date for d in ordered if d.date is not None]
        if dated:
            script += f" subtitle {_applescript('Due ' + _date(min(dated)))}"
        try:
            result = subprocess.run(
                [OSASCRIPT, "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
            )
        except subprocess.TimeoutExpired:
            raise NotifyError("osascript failed (timeout)") from None
        except OSError:
            raise NotifyError("osascript failed (not runnable)") from None
        if result.returncode != 0:
            raise NotifyError(f"osascript failed (exit {result.returncode})")


# set while a Keychain lookup runs (also one that hung past the timeout)
_keychain_busy = threading.Event()
_keychain_start = threading.Lock()


def keychain_password(user: str) -> str | None:
    import keyring  # imported on use: only the e-mail channel needs it

    return keyring.get_password(KEYRING_SERVICE, user)


def store_keychain_password(user: str, password: str) -> None:
    """Store the e-mail password in the macOS Keychain (``dam remind
    --set-email-password``); the e-mail channel reads it back by ``user``."""
    import keyring

    keyring.set_password(KEYRING_SERVICE, user, password)


def _lookup_with_timeout(lookup: Callable[[str], str | None], user: str) -> str | None:
    """Run ``lookup`` in a daemon thread; a Keychain that never answers (a prompt no one
    sees from launchd) must not hang the run. While an earlier lookup is still hung, no
    new one is started (hourly runs must not pile up threads)."""
    box: dict[str, object] = {}
    with _keychain_start:
        if _keychain_busy.is_set():
            raise NotifyError("keychain did not answer")
        _keychain_busy.set()

    def work() -> None:
        try:
            box["value"] = lookup(user)
        except BaseException as e:  # noqa: BLE001 - reported below
            box["error"] = e
        finally:
            _keychain_busy.clear()

    worker = threading.Thread(target=work, name="dam-keychain", daemon=True)
    try:
        worker.start()
    except BaseException:
        _keychain_busy.clear()
        raise
    worker.join(KEYCHAIN_TIMEOUT)
    if worker.is_alive():
        raise NotifyError("keychain did not answer")
    if "error" in box:
        raise NotifyError(f"keychain error ({type(box['error']).__name__})")
    value = box.get("value")
    return value if isinstance(value, str) else None


class EmailNotifier:
    """One plain-text e-mail per run to the configured address only (From = To).

    TLS is required for the login: port 465 means implicit TLS (``SMTP_SSL``), any
    other port needs ``starttls: true``; otherwise nothing is sent.
    """

    id = "email"

    def __init__(
        self,
        settings: EmailSettings,
        password_lookup: Callable[[str], str | None] = keychain_password,
    ) -> None:
        self.settings = settings
        self._password = password_lookup

    @classmethod
    def from_settings(cls, settings: Settings) -> EmailNotifier | None:
        email = settings.reminders.email
        return cls(email) if email is not None else None

    def body(self, dues: Sequence[Due], note: str | None = None) -> str:
        lines = []
        for d in _by_date(dues):
            parts = [plain(d.title)]
            if d.date is not None:
                parts.append(_date(d.date))
            if d.amount is not None:
                parts.append(_money(d.amount))
            lines.append(f"{plain(d.tray_name or d.tray_id)}: {', '.join(parts)}")
        if note:
            lines += ["", plain(note)]
        return "\n".join(lines) + "\n"

    def send(self, dues: list[Due], note: str | None = None) -> None:
        if not dues:
            return
        s = self.settings
        implicit_tls = s.smtp_port == IMPLICIT_TLS_PORT
        if not implicit_tls and not s.starttls:
            raise NotifyError("refusing to send the password without TLS")
        password = _lookup_with_timeout(self._password, s.smtp_user)
        if not password:
            raise NotifyError("password not set — run dam remind --set-email-password")
        msg = EmailMessage()
        msg["Subject"] = f"Archive reminders: {len(dues)} due"
        msg["From"] = s.to
        msg["To"] = s.to
        msg.set_content(self.body(dues, note))
        context = ssl.create_default_context()
        try:
            if implicit_tls:
                server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=context)
            else:
                server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
            with server:
                if not implicit_tls:
                    server.starttls(context=context)
                server.login(s.smtp_user, password)
                server.send_message(msg, from_addr=s.to, to_addrs=[s.to])
        except UnicodeError:
            # never echo the codec message: it quotes the offending (password) character
            raise NotifyError(
                "e-mail failed: the user name or password has characters the login "
                "cannot send (use ASCII)"
            ) from None
        except (OSError, smtplib.SMTPException) as e:
            raise NotifyError(f"e-mail failed: {e}") from e


# channel id -> notifier class; ``from_settings`` gives the configured notifier, or
# None when that channel is off
NOTIFIERS: dict[str, type] = {"mac": MacNotifier, "email": EmailNotifier}


def enabled_notifiers(settings: Settings) -> list[Notifier]:
    """The configured notifier of every registered channel that is on, in order."""
    out: list[Notifier] = []
    for cls in NOTIFIERS.values():
        notifier = cls.from_settings(settings)
        if notifier is not None:
            out.append(notifier)
    return out


TEST_TITLE = "dam test notification"


def send_test(settings: Settings, notifiers: list[Notifier] | None = None) -> dict[str, str | None]:
    """Send one harmless test message ("dam test notification": no item, no date, no
    amount) through each enabled channel; marks nothing. Returns channel id -> None
    when delivered, else the error message."""
    today = datetime.now().astimezone().date()
    test = Due(0, "test", TEST_TITLE, "test", today, None, None, "Test")
    out: dict[str, str | None] = {}
    for notifier in enabled_notifiers(settings) if notifiers is None else notifiers:
        try:
            notifier.send([test])
        except Exception as e:  # noqa: BLE001 - one channel never stops the others
            out[notifier.id] = str(e) or type(e).__name__
        else:
            out[notifier.id] = None
    return out


@dataclass
class RemindResult:
    sent: list[Due] = field(default_factory=list)
    silenced: list[Due] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # channel id -> message
    ran_at: datetime | None = None
    skipped: str | None = None  # why nothing was checked (another run holds the lock)


def run_reminders(
    app: App, now: datetime | None = None, notifiers: list[Notifier] | None = None
) -> RemindResult:
    """Send what is due now, once.

    Per item only its latest due occasion is sent; earlier ones are recorded silently.
    A due counts as sent as soon as at least one channel delivered it (so a broken
    channel never makes the others repeat); each channel's failure is recorded in
    ``errors``, never raised. If every channel failed, the next run tries again.

    One run at a time across processes (``dam serve``'s hourly check and the launchd
    helper): compute, send and mark happen under an exclusive ``flock`` on
    ``<data dir>/remind.lock``; a run that finds it taken is skipped (``skipped``).
    A completed run's result is kept on ``app.last_reminders``.
    """
    now = now or datetime.now().astimezone()
    lock_path = app.app_paths.data_dir / LOCK_NAME
    try:  # a fresh open file per run: flock is per open file
        fd = open_nofollow(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    except OSError as e:
        reason = f"cannot open lock: {e.strerror or type(e).__name__}"
        log.warning("reminders: skipped, %s", reason)
        return RemindResult(ran_at=now, skipped=reason)
    with os.fdopen(fd, "w", encoding="utf-8") as lock:
        try:
            _lock(lock)
        except BlockingIOError:
            log.info("reminders: skipped, %s", SKIPPED_BUSY)
            return RemindResult(ran_at=now, skipped=SKIPPED_BUSY)
        try:
            result = _run_locked(app, now, notifiers)
        finally:
            _unlock(lock)
    app.last_reminders = result
    return result


def due_now(app: App, now: datetime) -> list[Due]:
    """What a run at ``now`` would send (per item its latest due occasion); reads only:
    nothing is sent or marked (``dam remind --dry-run``)."""
    dues = due_reminders(app.engine, app.tray_defs, now, hour=app.settings.reminders.hour)
    send, _ = collapse(dues, latest_occasions(app.engine, app.tray_defs))
    return send


def _run_locked(app: App, now: datetime, notifiers: list[Notifier] | None) -> RemindResult:
    settings = app.settings.reminders
    dues = due_reminders(app.engine, app.tray_defs, now, hour=settings.hour)
    send, silenced = collapse(dues, latest_occasions(app.engine, app.tray_defs))
    mark_sent(app.engine, silenced, [], now)
    result = RemindResult(silenced=silenced, ran_at=now)
    delivered: list[str] = []
    if send:
        note = None if app.archive_available else ARCHIVE_NOTE
        for notifier in enabled_notifiers(app.settings) if notifiers is None else notifiers:
            try:
                notifier.send(send, note)
            except Exception as e:  # noqa: BLE001 - one channel never stops the others
                result.errors[notifier.id] = str(e) or type(e).__name__
            else:
                delivered.append(notifier.id)
        if delivered:
            mark_sent(app.engine, send, delivered, now)
            result.sent = send
    # titles are personal: the INFO summary has counts only, titles go to DEBUG
    log.info(
        "reminders: %d due, sent via %s, %d silenced; errors: %s",
        len(send),
        ", ".join(delivered) or "nothing",
        len(silenced),
        result.errors or "none",
    )
    log.debug("reminders sent: %s", [plain(d.title) for d in result.sent])
    return result
