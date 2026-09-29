"""
PDF text extraction. Primary: pdfplumber (better layout handling).
Fallback: pypdf, for PDFs pdfplumber can't parse.
Returns a list of {page: int, text: str} - never fabricates content for pages
that fail to extract (an empty/failed page is recorded, not skipped silently).
"""
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class PDFExtractionError(Exception):
    pass


def extract_pages(pdf_path: str) -> List[Dict]:
    pages = []
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages.append({"page": i, "text": text})
        if any(p["text"].strip() for p in pages):
            return pages
        logger.info("pdfplumber extracted no text for %s, trying pypdf fallback", pdf_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pdfplumber failed for %s: %s. Trying pypdf fallback.", pdf_path, exc)

    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append({"page": i, "text": text})
        return pages
    except Exception as exc:  # noqa: BLE001
        raise PDFExtractionError(
            f"Could not extract text from this PDF. It may be a scanned image "
            f"without an embedded text layer, encrypted, or corrupted. ({exc})"
        ) from exc
