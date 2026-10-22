"""PDFium is not thread-safe: every PDFium call (open, text, render, close) must hold this lock."""

import threading

PDFIUM_LOCK = threading.Lock()
