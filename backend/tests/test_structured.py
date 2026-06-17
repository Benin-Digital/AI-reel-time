from app.services import structured


def test_extract_skill_terms_basic(monkeypatch):
    monkeypatch.setattr(structured.settings, "scoring_skill_keywords", "python,fastapi,docker,postgresql,react")
    text = "Python, Docker, CI/CD, some random words, FastAPI experience"
    terms = structured._extract_skill_terms(text)
    assert "python" in terms
    assert "fastapi" in terms
    assert "docker" in terms
    # ensure noise words are not present
    assert "random" not in terms


def test_extract_skill_terms_fuzzy(monkeypatch):
    monkeypatch.setattr(structured.settings, "scoring_skill_keywords", "python,fastapi,postgresql")
    text = "Pyhton, postgresql, API design"
    terms = structured._extract_skill_terms(text)
    # 'Pyhton' fuzzy matches 'python'
    assert "python" in terms
    assert "postgresql" in terms


def test_job_skill_sources_include_missions_and_certifications(monkeypatch):
    """Job offers often list tech stack inside 'Missions' / 'Responsabilités'
    headings that Docling classifies as 'experience'. Those skills must end
    up in skill_terms — otherwise React/Vue/PHP get dropped on the floor."""
    monkeypatch.setattr(structured.settings, "ner_enabled", False)
    profile = structured.build_document_profile(
        "irrelevant raw text",
        kind="job",
        enable_ner=False,
        override_sections={
            "experience": "Maîtriser React, Vue.js et TypeScript",
            "certifications": "Connaissance de PostgreSQL et Redis exigée",
        },
    )
    for s in ("React", "Vue.js", "TypeScript", "PostgreSQL", "Redis"):
        assert s in profile.skill_terms, f"missing {s}"


def test_accessibility_taxonomy_recognises_wcag_rgaa():
    from app.services.taxonomy import find_skills
    cases = [
        "Respecter WCAG/RGAA niveau AA",
        "Connaissances WCAG 2.1",
        "Maîtriser le RGAA 4.1",
        "Accessibilité numérique",
        # Slash-stripped form (Docling sometimes produces "WCAGRGAA"):
        "Respecter WCAGRGAA",
    ]
    for text in cases:
        assert "Accessibilité web" in find_skills(text), f"missed in: {text!r}"


def test_job_title_from_docling_heading(monkeypatch):
    monkeypatch.setattr(structured.settings, "ner_enabled", False)
    profile = structured.build_document_profile(
        "Profil recherché\nRespecter WCAG/RGAA\nMaîtriser React",
        kind="job",
        enable_ner=False,
        override_sections={
            "_doc_title": "Développeur Full-Stack",
            "job_required": "Respecter WCAG/RGAA\nMaîtriser React",
        },
    )
    assert profile.job_title == "Développeur Full-Stack"


def test_job_title_heuristic_skips_constraint_verbs(monkeypatch):
    monkeypatch.setattr(structured.settings, "ner_enabled", False)
    text = (
        "Respecter WCAG/RGAA\n"
        "Maîtriser les frameworks modernes\n"
        "Ingénieur DevOps Senior\n"
        "Lieu : Paris\n"
    )
    profile = structured.build_document_profile(text, kind="job", enable_ner=False)
    assert profile.job_title == "Ingénieur DevOps Senior"


def test_job_title_not_set_for_cv(monkeypatch):
    monkeypatch.setattr(structured.settings, "ner_enabled", False)
    profile = structured.build_document_profile(
        "Développeur Full-Stack\nThierry Reynès",
        kind="cv",
        enable_ner=False,
    )
    assert profile.job_title is None


def test_soft_skills_partitioned_out_of_skill_terms(monkeypatch):
    monkeypatch.setattr(structured.settings, "scoring_skill_keywords", "")
    monkeypatch.setattr(structured.settings, "ner_enabled", False)
    profile = structured.build_document_profile(
        "irrelevant raw text",
        kind="cv",
        enable_ner=False,
        override_sections={
            "skills": "Python, Docker, Rigueur, Autonomie, Esprit d'analyse",
        },
    )
    assert "Python" in profile.skill_terms
    assert "Docker" in profile.skill_terms
    for soft in ("Rigueur", "Autonomie", "Esprit d'analyse"):
        assert soft not in profile.skill_terms
        assert soft in profile.soft_skill_terms