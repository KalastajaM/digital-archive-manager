"""Errors services and the ops layer raise for problems the caller caused (interfaces
report them as such).

Anything else escaping a service is a bug or an environment failure, not a user error.
"""


class NotFound(KeyError):
    """The requested file, folder or batch does not exist (or is missing/parked)."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else "not found"


class InvalidRequest(ValueError):
    """The request itself is invalid (bad name, duplicate file, bad origin)."""


class ArchiveUnavailable(InvalidRequest):
    """The configured archive folder is not an existing folder (Drive not running?)."""


class NotConfigured(InvalidRequest):
    """No ``archive_root`` is set yet (first-run setup has not happened)."""


class StalePreview(InvalidRequest):
    """What would happen now is not what was previewed (the caller previews again)."""


class Conflict(InvalidRequest):
    """The request is valid but the target's state does not allow it (HTTP 409)."""


class TooLarge(InvalidRequest):
    """A file is over the size limit for adding it to the archive (HTTP 413)."""


class NotSupported(Exception):
    """The request needs something this platform lacks (macOS ``open``): HTTP 501."""
