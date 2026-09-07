"""Test de non-regression pour le split match_cv_to_job / match_parsed_documents.

Contexte : le pipeline d'ingestion (main.py::_score_against_counterparts et
_vector_match_cv/_vector_match_job) parsait le CV ou l'offre "fixe" une fois
par paire comparee, alors que ce cote ne change pas dans la boucle. matcher.py
expose maintenant match_parsed_documents(cv, job) pour parser une seule fois
et reutiliser le resultat sur plusieurs comparaisons ; match_cv_to_job reste
la facade texte-a-texte utilisee par le reste du code (routers, tests).

Ce test verifie que le split ne change aucun score : parser separement puis
appeler match_parsed_documents doit produire un MatchScore identique a
match_cv_to_job sur le meme texte.
"""
from __future__ import annotations

from app.services.matcher import match_cv_to_job, match_parsed_documents
from app.services.parser import parse_document

CV_TEXT = """Développeur Python 5 ans d'experience.
Competences : Python, Django, PostgreSQL, Docker.
Experience : Backend chez ACME, 2019-2024.
Formation : Master informatique."""

JOB_TEXT = """Poste Développeur Python, 3 ans requis.
Competences requises : Python, Django, PostgreSQL.
Mission : maintenance et evolution d'une API backend."""


def test_match_parsed_documents_matches_match_cv_to_job():
    via_text = match_cv_to_job(CV_TEXT, JOB_TEXT)

    cv_parsed = parse_document(CV_TEXT, kind="cv")
    job_parsed = parse_document(JOB_TEXT, kind="job")
    via_parsed = match_parsed_documents(cv_parsed, job_parsed)

    assert via_parsed.score == via_text.score
    assert via_parsed.score_semantic == via_text.score_semantic
    assert via_parsed.score_skills == via_text.score_skills
    assert via_parsed.score_experience == via_text.score_experience
    assert via_parsed.score_education == via_text.score_education
    assert via_parsed.score_languages == via_text.score_languages
    assert via_parsed.score_contract == via_text.score_contract
    assert via_parsed.common_skills == via_text.common_skills
    assert via_parsed.missing_skills == via_text.missing_skills
    assert via_parsed.domain == via_text.domain


def test_match_parsed_documents_reused_cv_across_two_jobs():
    """The scenario the ingestion pipeline actually relies on: parse the CV
    once, then score it against several different jobs without re-parsing."""
    cv_parsed = parse_document(CV_TEXT, kind="cv")

    other_job_text = """Poste Data Analyst, 2 ans requis.
Competences requises : SQL, Excel, PowerBI.
Mission : reporting et analyse de donnees."""

    result_a = match_parsed_documents(cv_parsed, parse_document(JOB_TEXT, kind="job"))
    result_b = match_parsed_documents(cv_parsed, parse_document(other_job_text, kind="job"))

    assert result_a.score == match_cv_to_job(CV_TEXT, JOB_TEXT).score
    assert result_b.score == match_cv_to_job(CV_TEXT, other_job_text).score
    # A Python/Django/PostgreSQL job should score meaningfully higher than an
    # unrelated Data Analyst posting for this CV.
    assert result_a.score > result_b.score
