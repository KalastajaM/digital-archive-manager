"""Logging for the interfaces (CLI and HTTP API): ``<logs_dir>/dam.log`` plus stderr.

``configure_logging`` attaches two handlers to the ``dam`` logger: a rotating file
(INFO and up, 5 MB x 3) and stderr (WARNING and up). ``log_internal_error`` writes
the traceback being handled to the log file only, never to stderr.
"""

import logging
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dam.config import AppPaths

LOG_NAME = "dam.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 3
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_logger = logging.getLogger("dam")


class _Stderr(logging.StreamHandler):
    """Writes to whatever ``sys.stderr`` is now (test runners swap it per command)."""

    def __init__(self) -> None:
        super().__init__()

    @property
    def stream(self):  # type: ignore[override]
        return sys.stderr

    @stream.setter
    def stream(self, value) -> None:
        pass


def _ours() -> list[logging.Handler]:
    return [h for h in _logger.handlers if getattr(h, "dam_handler", False)]


def _file_handler(logs_dir: Path) -> RotatingFileHandler | None:
    target = str(logs_dir / LOG_NAME)
    for h in _ours():
        if isinstance(h, RotatingFileHandler) and h.baseFilename == target:
            return h
    return None


def reset_logging() -> None:
    """Remove (and close) the handlers ``configure_logging`` added."""
    for h in _ours():
        _logger.removeHandler(h)
        h.close()
    _logger.setLevel(logging.NOTSET)


def configure_logging(app_paths: AppPaths) -> None:
    """Log ``dam.*`` to ``<logs_dir>/dam.log`` (INFO) and stderr (WARNING). Idempotent:
    calling it again for the same data dir adds nothing; another data dir replaces them."""
    logs_dir = app_paths.logs_dir
    if _file_handler(logs_dir) is not None:
        return
    reset_logging()
    logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(_FORMAT)
    file_handler = RotatingFileHandler(
        logs_dir / LOG_NAME, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    stderr = _Stderr()
    stderr.setLevel(logging.WARNING)
    for h in (file_handler, stderr):
        h.setFormatter(fmt)
        h.dam_handler = True  # type: ignore[attr-defined]
        _logger.addHandler(h)
    _logger.setLevel(logging.INFO)


def log_internal_error(logs_dir: Path, message: str = "internal error") -> Path:
    """Write the traceback being handled to ``<logs_dir>/dam.log``; return the log path.

    Call it from an ``except`` block. Uses the rotating file handler when
    ``configure_logging`` set one up for ``logs_dir`` (file only, not stderr), else
    appends to the file directly. Never raises: a failing log must not hide the error.
    """
    log_path = logs_dir / LOG_NAME
    try:
        handler = _file_handler(logs_dir)
        if handler is not None:
            record = _logger.makeRecord(
                _logger.name, logging.ERROR, __file__, 0, message, (), sys.exc_info()
            )
            handler.handle(record)
            return log_path
        logs_dir.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} {message}\n{traceback.format_exc()}\n")
    except Exception:  # noqa: BLE001 - logging is best effort here
        pass
    return log_path
