"""Write a config file the user may also edit: back up, write, read back, restore."""

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def write_config_file(path: Path, text: str, verify: Callable[[], bool]) -> None:
    """Replace ``path`` with ``text`` (UTF-8). The file it replaces is kept as
    ``<name>.bak-<time>``. ``verify`` reads the new file back; if it returns False or
    anything raises, the old content is written back (an empty file when there was none:
    files are never deleted) and the error is raised (``OSError`` for a failed check). If
    the restore fails too, that is logged and the original error is still raised."""
    original = path.read_bytes() if path.exists() else None
    if original is not None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            with open(path.with_name(f"{path.name}.bak-{stamp}"), "xb") as fh:
                fh.write(original)
        except FileExistsError:
            pass  # a backup from this very second exists already
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if not verify():
            raise OSError(f"{path.name} did not read back as written")
    except Exception:
        try:
            with open(path, "wb") as f:
                f.write(original or b"")
        except OSError:
            log.exception("could not restore %s", path)  # the first error is the one raised
        raise
