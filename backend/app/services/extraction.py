"""
Text extraction from PDF, DOCX and TXT files.

Fixes vs previous version:
- clean_text() is called AFTER the page loop, not inside it (was O(N²))
- DOCX table cells in the same row are joined with a tab separator
- OCR uses psm=3 (auto-detect page columns) instead of psm=6
"""
import logging
import re
import unicodedata
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document
from pdf2image import convert_from_path
import pytesseract

from ..settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def clean_text(text: str) -> str:
    """
    Normalize extracted text:
    - fix hyphenated line breaks
    - strip bullet/dash prefixes
    - deduplicate repeated lines
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Rejoin words split by a hyphen at line break
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Fix PDF font ligature substitutions that PyMuPDF can't decode
    # U+25A0 (■) is used as a stand-in for the fi ligature (fiabilité → ■abilité)
    text = text.replace("\u25a0", "fi")
    # A "?" between two letters is an unmapped ti-ligature glyph (conception → concep?on)
    text = re.sub(r"(?<=[a-zA-Z\u00c0-\u024f])\?(?=[a-zA-Z\u00c0-\u024f])", "ti", text)

    lines: list[str] = []
    seen: dict[str, int] = {}
    prev = ""

    for raw in text.split("\n"):
        # Remove soft hyphens and bullet characters, collapse whitespace
        line = re.sub(r"\u00ad", "", raw)
        line = re.sub(r"\s+", " ", line.strip())
        # also strip Wingdings/Symbol bullet chars (ü→U+00FC, ð→U+00F0) used as list markers in some PDFs
        line = re.sub(r"^[\-*•·\u2022\u25e6ü°ð►▪▫●○◦]+\s*", "", line).strip()

        if not line or len(line) < 2:
            prev = ""
            continue

        key = unicodedata.normalize("NFKD", line).encode("ascii", "ignore").decode().lower()
        if key == prev:
            continue
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 2:
            continue

        lines.append(line)
        prev = key

    return "\n".join(lines).strip()


# Keep the old name as an alias so structured.py keeps working without changes
clean_document_text = clean_text


def extract_text_from_pdf(path: Path) -> str:
    """Extract PDF text via PyMuPDF with layout-aware sorting; OCR fallback for scanned PDFs.

    sort=True makes PyMuPDF order text spans by reading position (y then x),
    which correctly reconstructs multi-column CVs that pypdf/pdfminer mangles.
    """
    try:
        doc = fitz.open(str(path))
        parts: list[str] = []
        for page in doc:
            t = page.get_text("text", sort=True)
            if t.strip():
                parts.append(t)
        doc.close()
        extracted = clean_text("\n".join(parts))

        if len(extracted.strip()) >= settings.ocr_min_text_length:
            return extracted

        logger.info(
            "PDF %s below OCR threshold (%d chars), running OCR",
            path.name,
            settings.ocr_min_text_length,
        )
        ocr = clean_text(_ocr_pdf(path))
        return ocr if len(ocr) > len(extracted) else extracted

    except Exception as exc:
        logger.exception("PDF extraction failed for %s: %s", path.name, exc)
        return ""


def _ocr_pdf(path: Path) -> str:
    """Tesseract OCR on each page image; uses psm=3 for multi-column layouts.

    OCR runs synchronously in the single event worker thread, so an unbounded
    document (scanned, many pages, or a misdetected non-CV/job file) can pin
    the CPU for minutes and starve the whole process. Cap the number of pages
    OCR'd and give each page a hard timeout so a pathological file degrades
    to partial/no text instead of hanging the pipeline.
    """
    try:
        images = convert_from_path(str(path), dpi=settings.ocr_dpi)
        if len(images) > settings.ocr_max_pages:
            logger.warning(
                "PDF %s has %d pages, OCR-ing only the first %d (AI_REALTIME_OCR_MAX_PAGES)",
                path.name,
                len(images),
                settings.ocr_max_pages,
            )
            images = images[: settings.ocr_max_pages]

        # psm 3 = fully automatic page segmentation (handles multi-column CVs)
        config = f"--psm 3 --oem {settings.ocr_oem}"
        parts: list[str] = []
        for page_num, img in enumerate(images, start=1):
            try:
                t = pytesseract.image_to_string(
                    img,
                    lang=settings.ocr_languages,
                    config=config,
                    timeout=settings.ocr_page_timeout_seconds,
                )
            except RuntimeError:
                logger.warning(
                    "OCR timed out on page %d/%d of %s (> %ds), skipping this page",
                    page_num, len(images), path.name, settings.ocr_page_timeout_seconds,
                )
                continue
            if t.strip():
                parts.append(t)
        return "\n".join(parts)
    except Exception as exc:
        logger.exception("OCR failed for %s: %s", path.name, exc)
        return ""


def extract_text_from_docx(path: Path) -> str:
    """Extract DOCX paragraphs and tables with proper cell separation."""
    try:
        doc = Document(path)
        parts: list[str] = []

        for para in doc.paragraphs:
            t = para.text.strip()
            if t:
                parts.append(t)

        for table in doc.tables:
            for row in table.rows:
                # FIX: join cells in same row with tab so columns stay readable
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append("\t".join(cells))

        return clean_text("\n".join(parts))
    except Exception as exc:
        logger.exception("DOCX extraction failed for %s: %s", path.name, exc)
        return ""


def extract_text_from_txt(path: Path) -> str:
    """Extract plain text, trying UTF-8 then latin-1."""
    for encoding in ("utf-8", "latin-1"):
        try:
            return clean_text(path.read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            logger.exception("TXT extraction failed for %s: %s", path.name, exc)
            return ""
    return ""


def extract_text(path: Path) -> str:
    """Dispatch extraction by file extension. Returns '' on any failure."""
    if not path.exists() or not path.is_file():
        logger.warning("File not found: %s", path)
        return ""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    if suffix == ".docx":
        return extract_text_from_docx(path)
    if suffix == ".txt":
        return extract_text_from_txt(path)
    logger.warning("Unsupported file format: %s for %s", suffix, path.name)
    return ""
