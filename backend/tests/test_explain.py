"""Tests de non-regression pour explain.py.

build_match_explanation() generait sa narration ("Pourquoi ce match") via
l'ancien moteur scoring.py, qui s'appuie sur structured.py — un pipeline
d'extraction distinct de celui utilise par matcher.py pour calculer le
score persiste (parser.py). Consequence observee en production : le texte
affiche a l'utilisateur pouvait lister des competences "alignees" qui ne
correspondaient a aucune des competences realmente comptees dans le score
affiche a cote (ex: score de competences a 0% mais narration listant des
competences en commun).

Ce test verrouille le fait qu'explain.py et matcher.py partagent desormais
le meme pipeline d'extraction (parser.py) : toute competence que matcher.py
compte comme commune/manquante doit apparaitre dans la narration
correspondante, et reciproquement.
"""
from __future__ import annotations

from app.services.explain import build_match_explanation
from app.services.matcher import match_cv_to_job

CV_TEXT = "Competences: Python, Django, PostgreSQL.\nExperience: 5 ans en developpement backend."
JOB_TEXT = "Competences requises: Python, Django, Kubernetes, AWS.\nExperiences professionnelles: Minimum 3 ans d experience."


def test_explanation_common_skills_match_persisted_score():
    """Toute competence que matcher.py compte comme commune (common_skills,
    le champ persiste en base) doit etre mentionnee dans le 'why_match' de
    l'explication — sinon la narration et le score peuvent se contredire."""
    match = match_cv_to_job(CV_TEXT, JOB_TEXT)
    why_match_text = " ".join(
        build_match_explanation(CV_TEXT, JOB_TEXT, match.score, match.common_skills)["why_match"]
    )
    for skill in match.common_skills:
        assert skill in why_match_text, (
            f"'{skill}' compte comme competence commune par matcher.py "
            f"mais absent du texte 'why_match' de l'explication"
        )


def test_explanation_missing_skills_match_persisted_score():
    """Toute competence que matcher.py compte comme manquante (missing_skills)
    doit apparaitre dans la section 'vigilance' de l'explication."""
    match = match_cv_to_job(CV_TEXT, JOB_TEXT)
    details = build_match_explanation(CV_TEXT, JOB_TEXT, match.score, match.common_skills)
    vigilance_text = " ".join(details["vigilance"])
    for skill in match.missing_skills:
        assert skill in vigilance_text, (
            f"'{skill}' compte comme competence manquante par matcher.py "
            f"mais absent de la section 'vigilance' de l'explication"
        )


def test_explanation_surfaces_priority_keywords_distinctly():
    """L'explication doit afficher la couverture des mots-cles prioritaires
    separement de la couverture generale de competences (ex: "2/3 trouves"),
    et lister ceux qui manquent en vigilance -- cote a cote avec la
    composante score_priority_keywords calculee par matcher.py."""
    cv = "Consultant gouvernance et LOD2, tres experimente."
    job = "Poste: Analyste risque. Competences requises: gouvernance."
    priority_keywords = "gouvernance\nLOD2\nISO 27001"

    match = match_cv_to_job(cv, job, priority_keywords)
    details = build_match_explanation(cv, job, match.score, match.common_skills, priority_keywords)

    assert set(details["priority_keywords_matched"]) == {"Gouvernance", "LOD2"}
    assert details["priority_keywords_missing"] == ["ISO 27001"]

    why_match_text = " ".join(details["why_match"])
    assert "2/3" in why_match_text, f"attendu '2/3' dans le why_match, obtenu: {why_match_text!r}"
    vigilance_text = " ".join(details["vigilance"])
    assert "ISO 27001" in vigilance_text


def test_explanation_without_priority_keywords_omits_the_section():
    cv = "Développeur Python, Django."
    job = "Poste: Développeur. Compétences requises: Python."
    match = match_cv_to_job(cv, job)
    details = build_match_explanation(cv, job, match.score, match.common_skills)
    assert details["priority_keywords_matched"] == []
    assert details["priority_keywords_missing"] == []
    assert "mots-cles prioritaires" not in " ".join(details["why_match"]).lower()
