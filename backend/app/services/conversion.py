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
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .extraction import extract_text

logger = logging.getLogger(__name__)

# Docling's DocumentConverter loads ML layout/table models (DocLayNet,
# TableFormer) on construction. Building a fresh one per document — as this
# module used to — pays that load cost on every single ingest instead of
# once per process, and with several worker threads (AI_REALTIME_WORKER_
# CONCURRENCY > 1) each document event could end up constructing its own
# copy concurrently, multiplying both the load time and the memory/CPU cost.
_converter = None
_converter_lock = threading.Lock()


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


# Docling injects HTML comments for non-text regions (e.g. `<!-- image -->`,
# `<!-- formula -->`) and leaves unfilled form placeholders like `[Date]` or
# `[image]` in the markdown export. They pollute downstream extraction —
# strip them at the source.
_DOCLING_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_DOCLING_PLACEHOLDER_RE = re.compile(
    r"\[\s*(?:date|image|table|formula|figure|signature|logo)\s*\]",
    re.IGNORECASE,
)


def _strip_docling_artifacts(text: str) -> str:
    if not text:
        return text
    text = _DOCLING_HTML_COMMENT_RE.sub("", text)
    text = _DOCLING_PLACEHOLDER_RE.sub("", text)
    # Collapse runs of blank lines created by removals.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_DOCLING_SUPPORTED = {".pdf", ".docx", ".pptx", ".html", ".htm"}


def convert_document(path: Path) -> ConvertedDocument:
    """Convert a document to structured form using Docling.

    Raises RuntimeError if the format is unsupported or Docling is not installed.
    No silent fallback — callers must handle the error explicitly.
    """
    if path.suffix.lower() not in _DOCLING_SUPPORTED:
        raise RuntimeError(f"Unsupported format for Docling: {path.suffix}")
    return _convert_with_docling(path)


def _get_converter():
    """Build (once) and cache the Docling DocumentConverter for this process."""
    global _converter
    if _converter is None:
        with _converter_lock:
            if _converter is None:
                import os
                from docling.document_converter import DocumentConverter, PdfFormatOption
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import PdfPipelineOptions
                from docling.datamodel.settings import settings as docling_settings

                # The Dockerfile sets DOCLING_ARTIFACTS_PATH=/app/.cache/docling but
                # download_models() actually writes to the HuggingFace Hub cache
                # (/app/.cache/huggingface/...). Docling reads the env var at import
                # time into a global settings singleton, and base_pipeline.py falls
                # back to settings.artifacts_path even when pipeline_options.artifacts_path
                # is None. We need to clear all three: env var, singleton, and explicit
                # kwarg. Then Docling falls back to HF Hub lazy-loading.
                os.environ.pop("DOCLING_ARTIFACTS_PATH", None)
                docling_settings.artifacts_path = None

                # CVs and job offers are text-based PDFs — OCR is unnecessary and
                # pulls in heavy model dependencies (RapidOCR, EasyOCR) that are
                # not installed.
                pipeline_options = PdfPipelineOptions(do_ocr=False, artifacts_path=None)

                logger.info("Loading Docling DocumentConverter (layout + table models)")
                _converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                    }
                )
                logger.info("Docling DocumentConverter ready")
    return _converter


def _convert_with_docling(path: Path) -> ConvertedDocument:
    """Use Docling for layout-aware extraction. Requires `pip install docling`."""
    converter = _get_converter()
    result = converter.convert(str(path))
    doc = result.document

    markdown = _strip_docling_artifacts(doc.export_to_markdown())
    raw_text = doc.export_to_text() if hasattr(doc, "export_to_text") else markdown
    full_text = _strip_docling_artifacts(raw_text)
    sections = _split_markdown_sections(markdown)
    tables = _extract_tables(doc)

    return ConvertedDocument(
        full_text=full_text,
        markdown=markdown,  # already stripped
        sections=sections,
        tables=tables,
        backend="docling",
    )


def _classify_section(title: str) -> str:
    """Map a section header to a canonical section name.

    Matches the LONGEST alias found across all categories, not the first
    dict entry that matches — sinon un alias court comme "profil" (summary)
    l'emporte sur le plus spécifique "profil recherché" (job_required)
    simplement parce que "summary" est listé en premier dans _SECTION_ALIASES.

    Un alias d'un seul mot doit correspondre à un token entier (délimité par
    des espaces), pas à une simple sous-chaîne — sinon "stack" matche à
    l'intérieur du mot composé "Full-Stack" et un titre de poste comme
    "Développeur Full-Stack" est classifié à tort comme section "skills".
    Les alias à plusieurs mots ("profil recherché") restent testés en
    sous-chaîne car ils ne peuvent pas correspondre à un unique token.
    """
    t = title.lower().strip()
    words = {w.strip(":,.;()[]") for w in t.split()}
    best_canonical = "other"
    best_len = 0
    for canonical, aliases in _SECTION_ALIASES.items():
        for alias in aliases:
            matched = alias in t if " " in alias else alias in words
            if matched and len(alias) > best_len:
                best_canonical = canonical
                best_len = len(alias)
    return best_canonical


def _split_markdown_sections(md: str) -> dict[str, str]:
    """Split Markdown by # / ## / ### headers into canonical sections.

    Also captures the first H1/H2 heading as a reserved "_doc_title" key so
    downstream consumers can recover the document title (e.g. the job offer
    title that would otherwise be classified as "other" and lost).
    """
    sections: dict[str, list[str]] = {}
    current = "header"
    buffer: list[str] = []
    doc_title: str | None = None
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("#"):
            if buffer:
                sections.setdefault(current, []).append("\n".join(buffer).strip())
                buffer = []
            title = s.lstrip("#").strip()
            level = len(s) - len(s.lstrip("#"))
            classified = _classify_section(title)
            # Only the first H1/H2 that is NOT itself a known section header
            # ("Profil recherché", "Compétences", …) qualifies as document title.
            # Un H1 est sans ambiguïté le titre du document dans ce schéma —
            # jamais un marqueur de section — donc il qualifie même si son
            # libellé contient un alias court par accident (ex. "stack" dans
            # "Full-Stack"). Un H2 doit toujours échouer la classification
            # pour qualifier, car H2 sert aussi de vrai en-tête de section.
            if doc_title is None and title and classified == "other":
                doc_title = title
            current = classified
        else:
            buffer.append(line)
    if buffer:
        sections.setdefault(current, []).append("\n".join(buffer).strip())
    result = {k: "\n\n".join(v).strip() for k, v in sections.items() if any(x.strip() for x in v)}
    if doc_title:
        result["_doc_title"] = doc_title
    return result


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
