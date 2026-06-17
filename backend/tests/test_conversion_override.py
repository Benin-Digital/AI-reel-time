"""Smoke tests for the POC v2 conversion/override_sections path."""
from app.services import structured
from app.services.conversion import ConvertedDocument, _classify_section, _split_markdown_sections


def test_override_sections_short_circuits_heading_detection():
    # Raw text deliberately has NO section headings — the heuristic would dump
    # everything into "other". With override_sections, we feed the boundaries
    # in directly and expect them to land in the right buckets.
    raw_text = "Python Docker FastAPI - some unstructured paragraph"
    override = {
        "summary": "Senior backend engineer.",
        "skills": "Python, Docker, FastAPI",
        "experience": "5 ans chez ACME.",
    }
    profile = structured.build_document_profile(
        raw_text,
        kind="cv",
        enable_ner=False,
        override_sections=override,
    )
    # summary, skills, experience should be populated from the override
    assert profile.summary_text and "Senior backend engineer" in profile.summary_text
    assert "Python" in (profile.skills_text or "") or "Docker" in (profile.skills_text or "")
    assert "ACME" in (profile.experience_text or "")


def test_override_sections_unknown_key_lands_in_other():
    profile = structured.build_document_profile(
        "irrelevant",
        kind="cv",
        enable_ner=False,
        override_sections={"random_bucket": "this is mystery content"},
    )
    # Unknown section name should not crash the parser; content should land in "other"
    # We test indirectly via the absence of "this is mystery" from summary/skills/experience.
    for field in ("summary_text", "skills_text", "experience_text"):
        assert "mystery" not in (getattr(profile, field, "") or "")


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
