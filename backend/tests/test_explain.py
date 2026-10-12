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


def test_explanation_exposes_missing_skills_as_a_structured_list():
    """Demande (2026-10-05) : les competences manquantes cote general
    etaient uniquement noyees dans une phrase de la section 'vigilance' --
    desormais exposees comme leur propre liste structuree (comme
    priority_keywords_missing l'est deja), que le job ait ou non des
    mots-cles prioritaires configures."""
    match = match_cv_to_job(CV_TEXT, JOB_TEXT)
    details = build_match_explanation(CV_TEXT, JOB_TEXT, match.score, match.common_skills)

    assert set(details["missing_skills"]) == set(match.missing_skills)


def test_explanation_surfaces_priority_keywords_distinctly():
    """L'explication doit afficher la couverture des mots-cles prioritaires
    separement de la couverture generale de competences (ex: "2/3 trouves"),
    et lister ceux qui manquent en vigilance -- cote a cote avec la
    composante score_priority_keywords calculee par matcher.py."""
    cv = "Consultant gouvernance et TRM, tres experimente."
    job = "Poste: Analyste risque. Competences requises: gouvernance."
    priority_keywords = "gouvernance\nTRM\nISO 27001"

    match = match_cv_to_job(cv, job, priority_keywords)
    details = build_match_explanation(cv, job, match.score, match.common_skills, priority_keywords)

    assert set(details["priority_keywords_matched"]) == {"Gouvernance", "TRM"}
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


# ── Contrat API / interface : "Mots-cles communs" de la fenetre d'analyse ─────
#
# GET /matches/{id}/explain renvoie les mots-cles communs dans `keyword_hits`,
# mais l'interface lisait `common_keywords` / `top_keywords` (champs d'AUTRES
# reponses) : la section "Mots-cles communs" affichait donc toujours "Aucun
# mot-cle detecte", meme quand les mots-cles etaient bien detectes et stockes.

def test_explanation_returns_the_stored_keywords_as_keyword_hits():
    details = build_match_explanation(CV_TEXT, JOB_TEXT, 70.0, ["python", "django", ""])
    assert details["keyword_hits"] == ["python", "django"]


def test_frontend_reads_the_field_the_explain_endpoint_returns():
    from pathlib import Path

    from app.schemas import MatchExplainRead

    assert "keyword_hits" in MatchExplainRead.model_fields
    source = Path(__file__).resolve().parents[2].joinpath(
        "frontend", "js", "components", "matches.js"
    ).read_text(encoding="utf-8")
    # chaque lecture des mots-cles d'une explication doit inclure keyword_hits
    reads = [line for line in source.splitlines() if "data.common_keywords" in line]
    assert reads, "lecture des mots-cles de l'explication introuvable"
    assert all("data.keyword_hits" in line for line in reads)
