import io
from pathlib import Path

from dam.extract.base import ExtractedText, UnsupportedContent

NO_MSG = "Outlook .msg files need the optional package: install dam[msg]"


class MsgExtractor:
    name = "msg"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".msg"

    def extract(self, path: Path, data: bytes | None = None) -> ExtractedText:
        try:
            import extract_msg
        except ImportError:
            raise UnsupportedContent(NO_MSG) from None

        message = extract_msg.Message(io.BytesIO(data) if data is not None else str(path))
        try:
            parts = [
                message.subject,
                message.sender,
                message.to,
                str(message.date) if message.date else None,
                message.body,
            ]
        finally:
            message.close()
        return ExtractedText(text="\n".join(p for p in parts if p), extractor=self.name)
