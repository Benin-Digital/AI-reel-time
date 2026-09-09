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
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pdf2image import convert_from_path
import pytesseract

from ..settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


# Lines longer than this are treated as candidates for the repeated-page-
# header/footer dedup below; short lines never are. A page header/footer
# ("Curriculum Vitae - Jean Dupont", "Document confidentiel") is almost
# always a full phrase, while a short recurring bullet ("Python", "SQL",
# "Rigueur") is exactly the kind of content that gets legitimately repeated
# across several job entries in a CV and must not be treated the same way.
_BOILERPLATE_MIN_LENGTH = 20


def clean_text(text: str) -> str:
    """
    Normalize extracted text:
    - fix hyphenated line breaks
    - strip bullet/dash prefixes
    - deduplicate repeated page headers/footers (long lines only)
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
        if len(line) > _BOILERPLATE_MIN_LENGTH:
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 2:
                continue

        lines.append(line)
        prev = key

    return "\n".join(lines).strip()


# Keep the old name as an alias so structured.py keeps working without changes
clean_document_text = clean_text


def _block_text(block: dict) -> str:
    """Join a get_text('dict') text block's lines/spans into a string."""
    lines = []
    for line in block.get("lines", []):
        line_text = "".join(span.get("text", "") for span in line.get("spans", []))
        if line_text.strip():
            lines.append(line_text)
    return "\n".join(lines)


def _order_blocks_by_column(blocks: list[dict], page_width: float) -> list[dict]:
    """Reorder text blocks to read a two-column layout column-by-column
    instead of interleaving by y-position.

    PyMuPDF's get_text(sort=True) orders spans by (y, x), which is correct
    for single-column text and for side-by-side columns of matching height,
    but scrambles the common CV template of a short sidebar (name/contact/
    skills) next to a much taller main body: a sidebar line and a main-body
    line that happen to sit at a similar y both get emitted at that point,
    interleaving two unrelated sections mid-sentence (see
    test_name_section_title.py for a real case this caused: an action verb
    from the interleaved main body was mistaken for the candidate's name).

    Detects a clean vertical split — every block sits entirely left of or
    entirely right of the page's horizontal midline, except full-width ones
    like a name/header banner — and only then reads full-width blocks in
    their natural top-to-bottom position, then the whole left column top-to-
    bottom, then the whole right column. Falls back to plain (y, x) order
    when no clean split exists, so ordinary single-column CVs are unaffected.
    """
    if not blocks:
        return []

    mid = page_width / 2
    left, right, full = [], [], []
    for b in blocks:
        x0, _, x1, _ = b["bbox"]
        if x1 <= mid:
            left.append(b)
        elif x0 >= mid:
            right.append(b)
        else:
            full.append(b)

    # Require both sides to carry a meaningful share of the page's text, not
    # just count blocks: a genuine sidebar column is very often ONE block
    # (a whole paragraph), while a single-column CV can have a small block
    # entirely right of the midline too (a right-aligned date, a page
    # number) without being a two-column layout at all. Gating on character
    # share instead avoids reordering (and scrambling) that common
    # single-column case.
    total_chars = sum(len(_block_text(b)) for b in blocks) or 1
    left_chars = sum(len(_block_text(b)) for b in left)
    right_chars = sum(len(_block_text(b)) for b in right)
    min_share = 0.15
    if left_chars < total_chars * min_share or right_chars < total_chars * min_share:
        return sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))

    left.sort(key=lambda b: b["bbox"][1])
    right.sort(key=lambda b: b["bbox"][1])
    full.sort(key=lambda b: b["bbox"][1])

    first_col_y = min(left[0]["bbox"][1], right[0]["bbox"][1])
    header = [b for b in full if b["bbox"][1] < first_col_y]
    trailer = [b for b in full if b["bbox"][1] >= first_col_y]
    return header + left + right + trailer


def extract_text_from_pdf(path: Path) -> str:
    """Extract PDF text via PyMuPDF with column-aware ordering; OCR fallback for scanned pages.

    Blocks are read via get_text('dict') (bounding boxes) and reordered by
    _order_blocks_by_column() rather than PyMuPDF's own sort=True, which
    handles single-column and matched-height side-by-side text but not an
    asymmetric sidebar template — see that function's docstring.

    The OCR threshold is checked per page, not on the document's combined
    text: a handful of real pages easily clear a document-wide threshold on
    their own, which silently skipped OCR — and therefore lost all content —
    for any purely-scanned page mixed into an otherwise text-based document
    (e.g. a scanned diploma/certificate appended to a Word-exported CV).
    """
    try:
        doc = fitz.open(str(path))
        page_texts: list[str] = []
        weak_pages: list[int] = []  # 0-indexed pages below the OCR threshold
        for i, page in enumerate(doc):
            raw = page.get_text("dict")
            blocks = [b for b in raw.get("blocks", []) if b.get("type") == 0]
            ordered = _order_blocks_by_column(blocks, raw.get("width") or page.rect.width)
            t = "\n".join(_block_text(b) for b in ordered)
            page_texts.append(t)
            if len(t.strip()) < settings.ocr_min_text_length:
                weak_pages.append(i)
        doc.close()

        if weak_pages:
            if len(weak_pages) > settings.ocr_max_pages:
                logger.warning(
                    "PDF %s has %d page(s) needing OCR, only OCR-ing the first %d (AI_REALTIME_OCR_MAX_PAGES)",
                    path.name,
                    len(weak_pages),
                    settings.ocr_max_pages,
                )
                weak_pages = weak_pages[: settings.ocr_max_pages]

            logger.info(
                "PDF %s: %d page(s) below OCR threshold (%d chars), running OCR on those pages only",
                path.name,
                len(weak_pages),
                settings.ocr_min_text_length,
            )
            ocr_by_page = _ocr_pdf_pages(path, weak_pages)
            for i in weak_pages:
                ocr_text = ocr_by_page.get(i, "")
                if len(ocr_text.strip()) > len(page_texts[i].strip()):
                    page_texts[i] = ocr_text

        return clean_text("\n".join(page_texts))

    except Exception as exc:
        logger.exception("PDF extraction failed for %s: %s", path.name, exc)
        return ""


def _ocr_pdf_pages(path: Path, page_numbers: list[int]) -> dict[int, str]:
    """Tesseract OCR on specific 0-indexed pages only; uses psm=3 for multi-column layouts.

    OCR runs synchronously in the single event worker thread, so an unbounded
    document (scanned, many pages, or a misdetected non-CV/job file) can pin
    the CPU for minutes and starve the whole process. Each page is rendered
    and OCR'd one at a time — rather than converting the whole PDF to images
    upfront — so memory/time cost scales with the pages that actually need
    OCR, not the document's total page count, and each page gets its own
    hard timeout so a pathological one degrades to partial text instead of
    hanging the pipeline.
    """
    results: dict[int, str] = {}
    config = f"--psm 3 --oem {settings.ocr_oem}"
    for page_num in page_numbers:
        try:
            images = convert_from_path(
                str(path),
                dpi=settings.ocr_dpi,
                first_page=page_num + 1,
                last_page=page_num + 1,
            )
        except Exception as exc:
            logger.exception("OCR page render failed for %s page %d: %s", path.name, page_num + 1, exc)
            continue
        if not images:
            continue
        try:
            t = pytesseract.image_to_string(
                images[0],
                lang=settings.ocr_languages,
                config=config,
                timeout=settings.ocr_page_timeout_seconds,
            )
        except RuntimeError:
            logger.warning(
                "OCR timed out on page %d of %s (> %ds), skipping this page",
                page_num + 1, path.name, settings.ocr_page_timeout_seconds,
            )
            continue
        if t.strip():
            results[page_num] = t
    return results


def _iter_docx_block_items(doc):
    """Yield each paragraph/table child of the document body, in document order.

    python-docx exposes `doc.paragraphs` and `doc.tables` as two separate
    flat lists that don't preserve their relative position — extracting
    "all paragraphs then all tables" moves every table to the end of the
    text regardless of where it actually sits in the document, scrambling
    a CV that mixes free text with an experience/skills table.
    """
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _docx_header_footer_lines(doc) -> tuple[list[str], list[str]]:
    """Return (header_lines, footer_lines) across all sections.

    `doc.paragraphs` only covers the document body — text placed in a
    header or footer (very often the candidate's name/contact details in a
    CV template) is otherwise silently dropped from extraction entirely.
    """
    headers: list[str] = []
    footers: list[str] = []
    for section in doc.sections:
        if section.header is not None:
            headers.extend(p.text.strip() for p in section.header.paragraphs if p.text.strip())
        if section.footer is not None:
            footers.extend(p.text.strip() for p in section.footer.paragraphs if p.text.strip())
    return headers, footers


def extract_text_from_docx(path: Path) -> str:
    """Extract DOCX headers/footers, paragraphs and tables (in document order)."""
    try:
        doc = Document(path)
        parts: list[str] = []

        header_lines, footer_lines = _docx_header_footer_lines(doc)
        parts.extend(header_lines)

        for block in _iter_docx_block_items(doc):
            if isinstance(block, Paragraph):
                t = block.text.strip()
                if t:
                    parts.append(t)
            elif isinstance(block, Table):
                for row in block.rows:
                    # join cells in same row with tab so columns stay readable
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append("\t".join(cells))

        parts.extend(footer_lines)

        return clean_text("\n".join(parts))
    except Exception as exc:
        logger.exception("DOCX extraction failed for %s: %s", path.name, exc)
        return ""


def extract_text_from_txt(path: Path) -> str:
    """Extract plain text, trying UTF-8, then cp1252, then latin-1.

    latin-1 accepts every byte value and never raises UnicodeDecodeError, so
    it used to be tried right after UTF-8 — but a .txt saved on Windows with
    "smart" quotes/dashes (extremely common from copy-pasting out of Word)
    is cp1252-encoded, and decoding that as latin-1 turns those characters
    into C1 control codes (mojibake) instead of failing loudly. cp1252 is
    tried first: it's a superset of latin-1 for the common Western-European
    case and still raises on the handful of byte values it leaves undefined,
    so latin-1 remains as the final, true last-resort fallback.
    """
    for encoding in ("utf-8", "cp1252", "latin-1"):
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
