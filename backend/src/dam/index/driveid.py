"""Read the Google Drive item id stored in an extended attribute (macOS and Linux)."""

from pathlib import Path

try:  # not installed on Windows
    import xattr
except ImportError:  # pragma: no cover - platform dependent
    xattr = None

DRIVE_ID_XATTR = "com.google.drivefs.item-id#S"


def read_drive_id(path: Path) -> str | None:
    """Return the Drive item id of ``path`` (symlinks not followed), or None. Without
    extended-attribute support (Windows) there is none: files keep their ``local:`` id."""
    if xattr is None:
        return None
    try:
        return xattr.getxattr(path, DRIVE_ID_XATTR, symlink=True).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
