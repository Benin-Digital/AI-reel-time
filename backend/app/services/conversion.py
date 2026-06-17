"""
POC layer 1: Structured document conversion via Docling.

Docling (IBM, MIT) uses ML layout analysis (DocLayNet, TableFormer) to extract
*structured* content from PDFs — section boundaries, tables, lists — not just
raw text. This gives the rule-based parser clean section boundaries to attack,
which is the root cause of most current extraction errors (skills bleeding
into the name field, page footers polluting experience, etc.).

Falls back to the existing PyMuPDF extraction if Docling is not installed or
fails — so this layer is safe to enable incrementally.

Install: pip install -r backend/requirements-poc.txt
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .extraction import extract_text

logger = logging.getLogger(__name__)


@dataclass
class ConvertedDocument:
    """Result of structured conversion. Includes raw text + section map."""
    full_text: str
    sections: dict[str, str] = field(default_factory=dict)
    tables: list[list[list[str]]] = field(default_factory=list)
    markdown: str = ""
    backend: str = "fallback"  # "docling" | "fallback"


# Canonical names align with structured.py section keys so the dict can be
# fed directly into build_document_profile(override_sections=...).
_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "summary": ("profil", "profile", "summary", "about", "a propos", "à propos", "présentation", "presentation"),
    "experience": ("experience", "expérience", "professional", "career", "parcours", "emploi", "missions", "mission", "responsabilités", "responsabilites", "responsibilities"),
    "education": ("education", "formation", "etudes", "études", "diplôme", "academic"),
    "skills": ("competences", "compétences", "skills", "expertise", "stack", "technologies", "outils"),
    "languages": ("langues", "languages", "idiomas"),
    "certifications": ("certifications", "certificats"),
    "job_required": ("profil recherché", "profil recherche", "required", "requis", "requirements", "must have"),
    "job_nice": ("nice to have", "souhaitable", "plus", "bonus", "strength", "atout"),
    "contract": ("contrat", "contract", "type de contrat"),
}


_DOCLING_SUPPORTED = {".pdf", ".docx", ".pptx", ".html", ".htm"}


def convert_document(path: Path) -> ConvertedDocument:
    """Convert a document to structured form using Docling.

    Raises RuntimeError if the format is unsupported or Docling is not installed.
    No silent fallback — callers must handle the error explicitly.
    """
    if path.suffix.lower() not in _DOCLING_SUPPORTED:
        raise RuntimeError(f"Unsupported format for Docling: {path.suffix}")
    return _convert_with_docling(path)


def _convert_with_docling(path: Path) -> ConvertedDocument:
    """Use Docling for layout-aware extraction. Requires `pip install docling`."""
    import os
    from docling.document_converter import DocumentConverter

    # Always unset DOCLING_ARTIFACTS_PATH: the Docker volume mounts an empty
    # directory at /app/.cache/docling which shadows the baked-in models.
    # Without this env var, Docling downloads models to its default HuggingFace
    # cache (/app/.cache/huggingface) which IS persisted in the named volume.
    os.environ.pop("DOCLING_ARTIFACTS_PATH", None)

    converter = DocumentConverter()
    result = converter.convert(str(path))
    doc = result.document

    markdown = doc.export_to_markdown()
    full_text = doc.export_to_text() if hasattr(doc, "export_to_text") else markdown
    sections = _split_markdown_sections(markdown)
    tables = _extract_tables(doc)

    return ConvertedDocument(
        full_text=full_text,
        markdown=markdown,
        sections=sections,
        tables=tables,
        backend="docling",
    )


def _classify_section(title: str) -> str:
    """Map a section header to a canonical section name."""
    t = title.lower().strip()
    for canonical, aliases in _SECTION_ALIASES.items():
        if any(alias in t for alias in aliases):
            return canonical
    return "other"


def _split_markdown_sections(md: str) -> dict[str, str]:
    """Split Markdown by # / ## / ### headers into canonical sections."""
    sections: dict[str, list[str]] = {}
    current = "header"
    buffer: list[str] = []
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("#"):
            if buffer:
                sections.setdefault(current, []).append("\n".join(buffer).strip())
                buffer = []
            title = s.lstrip("#").strip()
            current = _classify_section(title)
        else:
            buffer.append(line)
    if buffer:
        sections.setdefault(current, []).append("\n".join(buffer).strip())
    return {k: "\n\n".join(v).strip() for k, v in sections.items() if any(x.strip() for x in v)}


def _extract_tables(doc: Any) -> list[list[list[str]]]:
    """Pull tables from a Docling document when present."""
    tables: list[list[list[str]]] = []
    try:
        for tbl in getattr(doc, "tables", []) or []:
            rows: list[list[str]] = []
            for row in getattr(tbl, "data", []) or []:
                cells = [getattr(c, "text", str(c)).strip() for c in row]
                if any(cells):
                    rows.append(cells)
            if rows:
                tables.append(rows)
    except Exception:
        pass
    return tables
