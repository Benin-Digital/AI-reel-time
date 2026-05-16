from app.services import scoring


def test_score_with_synonyms_and_skills(monkeypatch):
    monkeypatch.setattr(scoring.settings, "scoring_skill_keywords", "python,fastapi,api design")
    monkeypatch.setattr(scoring.settings, "scoring_skill_weight", 2.0)
    monkeypatch.setattr(scoring.settings, "scoring_synonyms", "api=interface")
    monkeypatch.setattr(scoring.settings, "scoring_stopwords_languages", "en")
    monkeypatch.setattr(scoring.settings, "scoring_stopwords", "")
    monkeypatch.setattr(scoring.settings, "scoring_phrase_bonus", 0.1)
    monkeypatch.setattr(scoring.settings, "scoring_max_bonus", 0.2)
    monkeypatch.setattr(scoring.settings, "scoring_experience_bonus", 0.1)
    monkeypatch.setattr(scoring.settings, "scoring_experience_penalty", 0.05)

    cv = "Python engineer with FastAPI. 5 years experience."
    job = "Looking for python and interface design. 3 years."

    score, keywords = scoring.score_texts(cv, job)

    assert score > 0
    assert "python" in keywords


def test_score_zero_when_empty():
    score, keywords = scoring.score_texts("", "job")
    assert score == 0.0
    assert keywords == []
