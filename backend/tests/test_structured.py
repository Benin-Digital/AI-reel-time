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