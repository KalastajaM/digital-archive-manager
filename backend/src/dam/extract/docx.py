import io
import zipfile
from pathlib import Path

from dam.extract import zip_guard
from dam.extract.base import ExtractedText, UnsupportedContent

NOT_WORD = "not a valid Word file"
NOT_WORD_DOCUMENT = "not a Word document"
PASSWORD_WORD = "password-protected Word file"
# an encrypted .docx is an OLE compound file (not a zip) holding the encrypted package
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _head(path: Path, data: bytes | None) -> bytes:
    if data is not None:
        return data[:8]
    try:
        with open(path, "rb") as fh:
            return fh.read(8)
    except OSError:
        return b""


class DocxExtractor:
    name = "docx"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".docx"

    def extract(self, path: Path, data: bytes | None = None) -> ExtractedText:
        import docx
        from docx.opc.exceptions import PackageNotFoundError

        zip_guard.check(path, data)
        try:
            document = docx.Document(io.BytesIO(data) if data is not None else str(path))
        except (zipfile.BadZipFile, PackageNotFoundError) as exc:
            # not a zip: a retry cannot help, so it is unsupported rather than an error
            if _head(path, data) == _OLE_MAGIC:
                raise UnsupportedContent(PASSWORD_WORD) from exc
            raise UnsupportedContent(NOT_WORD) from exc
        except (KeyError, ValueError) as exc:
            # a zip, but not a Word package (no document part, another content type)
            raise UnsupportedContent(NOT_WORD_DOCUMENT) from exc
        text = "\n".join(p.text for p in document.paragraphs)
        return ExtractedText(text=text, extractor=self.name)
