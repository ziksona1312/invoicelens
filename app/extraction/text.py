"""Get text out of a document: the PDF text layer first, OCR only when there is none."""

from __future__ import annotations

import os
from pathlib import Path

import pdfplumber
import pytesseract

from app.extraction.preprocess import prepare_for_ocr

# One OCR thread per process: the eval already runs one process per CPU core.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

MIN_TEXT_CHARS = 30  # fewer characters than this means "scanned image, no text layer"


def read_text(path: str | Path, dpi: int = 200) -> tuple[str, str]:
    """Return (text, source) where source is "text" or "ocr". Only page 1 is read."""
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        text = page.extract_text() or ""
        if len(text.strip()) >= MIN_TEXT_CHARS:
            return text, "text"
        image = page.to_image(resolution=dpi).original
    text = pytesseract.image_to_string(prepare_for_ocr(image), lang="eng", config="--psm 6")
    return text, "ocr"
