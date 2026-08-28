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
