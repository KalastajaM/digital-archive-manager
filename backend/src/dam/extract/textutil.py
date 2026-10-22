"""Old Word and other word-processor formats via macOS ``textutil``."""

import shutil
import subprocess
from pathlib import Path

from dam.extract.base import ExtractedText, UnsupportedContent

TEXTUTIL_TIMEOUT_S = 60
MAX_CHARS = 2_000_000


class TextutilExtractor:
    name = "textutil"
    suffixes = {".doc", ".dot", ".dotx", ".docm", ".odt", ".html", ".htm", ".webarchive"}

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def extract(self, path: Path, data: bytes | None = None) -> ExtractedText:
        exe = shutil.which("textutil")
        if exe is None:
            raise UnsupportedContent("textutil is not available on this system")
        try:
            done = subprocess.run(
                [exe, "-convert", "txt", "-stdout", "--", str(path)],
                capture_output=True,
                timeout=TEXTUTIL_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"textutil took longer than {TEXTUTIL_TIMEOUT_S} s") from exc
        if done.returncode != 0:
            err = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
            reason = err[-1] if err else "textutil failed"
            raise UnsupportedContent(f"cannot read document: {reason}")
        text = done.stdout.decode("utf-8", errors="replace")[:MAX_CHARS]
        return ExtractedText(text=text, extractor=self.name)
