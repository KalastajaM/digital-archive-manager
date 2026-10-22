from pathlib import Path

from dam.extract.base import ExtractedText


class TextExtractor:
    name = "text"
    suffixes = {".txt", ".md", ".csv", ".rtf"}

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def extract(self, path: Path, data: bytes | None = None) -> ExtractedText:
        if data is None:
            data = path.read_bytes()
        return ExtractedText(text=data.decode("utf-8", errors="replace"), extractor=self.name)
