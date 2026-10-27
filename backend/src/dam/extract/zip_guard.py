"""Limits for zip-based documents (Word, Excel, PowerPoint, iWork) before they are read.

The readers (python-docx, python-pptx, openpyxl, the iWork preview) unpack parts into
memory, and the input cap (``index.content.MAX_BYTES``) limits only the packed size, so a
crafted file that unpacks to many GB could take the server down. ``check`` reads only the
zip's directory: the declared sizes are the ones that count, as ``zipfile`` never unpacks
a member past its declared size.
"""

import io
import zipfile
from pathlib import Path

from dam.extract.base import UnsupportedContent

MAX_MEMBERS = 10_000
MAX_TOTAL = 512 * 1024 * 1024  # bytes unpacked, all members together
MAX_RATIO = 200  # unpacked / packed, for members over RATIO_FROM
RATIO_FROM = 1024 * 1024
_CHUNK = 1 << 20


def _too_big() -> UnsupportedContent:
    return UnsupportedContent(f"too large to read: over {MAX_TOTAL // 2**20} MB unpacked")


def check(path: Path, data: bytes | None) -> None:
    """Raise ``UnsupportedContent`` when the zip at ``path`` (or ``data``, its bytes) has
    too many members, unpacks to too much in all, or has a member packed suspiciously
    tightly. Anything that is not a readable zip passes: its reader says what it is."""
    try:
        with zipfile.ZipFile(io.BytesIO(data) if data is not None else str(path)) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile:
        return
    if len(infos) > MAX_MEMBERS:
        raise UnsupportedContent(f"too many parts inside the file (over {MAX_MEMBERS})")
    total = 0
    for info in infos:
        total += info.file_size
        if total > MAX_TOTAL:
            raise _too_big()
        if info.file_size > RATIO_FROM and info.file_size > MAX_RATIO * info.compress_size:
            raise UnsupportedContent(
                "compressed too tightly to be a normal document (a possible zip bomb)"
            )


def read_member(zf: zipfile.ZipFile, name: str) -> bytes:
    """The bytes of member ``name``, read in chunks and refused past ``MAX_TOTAL``
    whatever its declared size says."""
    buf = bytearray()
    with zf.open(name) as fh:
        while chunk := fh.read(_CHUNK):
            buf += chunk
            if len(buf) > MAX_TOTAL:
                raise _too_big()
    return bytes(buf)
