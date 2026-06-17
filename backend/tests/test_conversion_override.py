"""Smoke tests for the POC v2 conversion/override_sections path."""
from app.services.conversion import ConvertedDocument, _classify_section, _split_markdown_sections, _strip_docling_artifacts


def test_strip_docling_artifacts_removes_html_comments_and_placeholders():
    raw = "## Skills\n<!-- image -->\nPython\n[Date]\nDocker"
    cleaned = _strip_docling_artifacts(raw)
    assert "<!-- image -->" not in cleaned
    assert "[Date]" not in cleaned
    assert "Python" in cleaned
    assert "Docker" in cleaned


def test_strip_docling_artifacts_handles_empty():
    assert _strip_docling_artifacts("") == ""
    assert _strip_docling_artifacts(None) is None  # type: ignore[arg-type]


def test_classify_section_aliases():
    assert _classify_section("Profil professionnel") == "summary"
    assert _classify_section("Expérience") == "experience"
    assert _classify_section("Compétences techniques") == "skills"
    assert _classify_section("Profil recherché") == "job_required"
    assert _classify_section("Random") == "other"


def test_split_markdown_sections_basic():
    md = "## Profil\nLead dev\n\n## Compétences\nPython\nDocker\n\n## Expérience\nACME 2022"
    sections = _split_markdown_sections(md)
    assert "summary" in sections
    assert "skills" in sections
    assert "experience" in sections
    assert "Lead dev" in sections["summary"]
    assert "Python" in sections["skills"]


def test_converted_document_dataclass_defaults():
    doc = ConvertedDocument(full_text="hello")
    assert doc.full_text == "hello"
    assert doc.sections == {}
    assert doc.tables == []
    assert doc.backend == "fallback"
