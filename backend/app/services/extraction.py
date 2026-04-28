import logging
from pathlib import Path

from docx import Document
from pdf2image import convert_from_path
from pypdf import PdfReader
import pytesseract

logger = logging.getLogger(__name__)


def extract_text_from_pdf(path: Path) -> str:
    """Extract text from PDF using pypdf, fallback to OCR if empty."""
    try:
        reader = PdfReader(path)
        text_content = []
        for page_num, page in enumerate(reader.pages):
            try:
                text = page.extract_text()
                if text.strip():
                    text_content.append(text)
            except Exception as exc:
                logger.warning(f"Failed to extract text from PDF page {page_num}: {exc}")

        if text_content:
            return "\n".join(text_content)

        # Fallback to OCR if PDF extraction yielded no text
        logger.info(f"PDF {path.name} has no extractable text, attempting OCR...")
        return _ocr_pdf(path)
    except Exception as exc:
        logger.exception(f"PDF extraction failed for {path.name}: {exc}")
        return ""


def _ocr_pdf(path: Path) -> str:
    """Use OCR (tesseract) on PDF images."""
    try:
        images = convert_from_path(str(path))
        text_content = []
        for img in images:
            ocr_text = pytesseract.image_to_string(img)
            if ocr_text.strip():
                text_content.append(ocr_text)
        return "\n".join(text_content)
    except Exception as exc:
        logger.exception(f"OCR fallback failed for {path.name}: {exc}")
        return ""


def extract_text_from_docx(path: Path) -> str:
    """Extract text from DOCX file."""
    try:
        doc = Document(path)
        text_content = []
        for para in doc.paragraphs:
            if para.text.strip():
                text_content.append(para.text)
        return "\n".join(text_content)
    except Exception as exc:
        logger.exception(f"DOCX extraction failed for {path.name}: {exc}")
        return ""


def extract_text_from_txt(path: Path) -> str:
    """Extract text from plain text file."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="latin-1")
        except Exception as exc:
            logger.exception(f"TXT extraction failed for {path.name}: {exc}")
            return ""


def extract_text(path: Path) -> str:
    """
    Extract text from file based on extension.
    Returns empty string if extraction fails.
    """
    if not path.exists() or not path.is_file():
        logger.warning(f"File does not exist: {path}")
        return ""

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    elif suffix == ".docx":
        return extract_text_from_docx(path)
    elif suffix == ".txt":
        return extract_text_from_txt(path)
    else:
        logger.warning(f"Unsupported file format: {suffix} for {path.name}")
        return ""
