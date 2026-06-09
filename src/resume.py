"""M1 step 1: turn a PDF resume into plain text."""
from __future__ import annotations

from pathlib import Path

import pdfplumber


def extract_text(pdf_path: str | Path) -> str:
    """Extract all text from a PDF resume, page by page."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Resume not found: {pdf_path}")

    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")

    text = "\n\n".join(pages).strip()
    if not text:
        raise ValueError(
            f"No text extracted from {pdf_path}. "
            "It may be a scanned/image PDF (would need OCR)."
        )
    return text
