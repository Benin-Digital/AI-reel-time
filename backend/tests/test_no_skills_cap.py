"""Un CV sans aucune competence detectee ne doit jamais depasser un CV pertinent.

Avant : _skill_score() renvoyait (0.0, has_signal=False) quand rien n'etait
extrait du CV. La composante etait exclue de la moyenne ET du plafond de
couverture, donc le CV recevait la seule composante semantique (~0.73 pour
presque tout le monde : la sortie du cross-encoder varie tres peu d'un candidat
a l'autre, voir _DEFAULT_W) et passait devant des profils pertinents a
couverture partielle. Constate le 2026-10-12 sur la plateforme soeur (Keoni) :
~40 CV mal extraits (police PDF sans table Unicode, corps du CV en image)
occupaient le haut de chaque classement.
"""
from __future__ import annotations

from app.services.explain import build_match_explanation
from app.services.matcher import match_cv_to_job

JOB = (
    "Poste Developpeur DevOps.\n"
    "Competences requises: Python, Docker, Kubernetes, Linux, PostgreSQL.\n"
)
CV_PARTIAL = "Developpeur. Competences: Python, Docker, Linux."
CV_UNREADABLE = "DWDDQDO\\VW 3\\WKRQ64/ DQVG H[S«ULHQFH)UDQFH 3URILOSURIHVVLRQQHO"


def test_cv_without_detected_skills_is_capped():
    result = match_cv_to_job(CV_UNREADABLE, JOB)
    assert result.score <= 30.0
    assert "skills" not in result.low_confidence_components


def test_cv_without_detected_skills_never_outranks_a_partial_match():
    unreadable = match_cv_to_job(CV_UNREADABLE, JOB)
    partial = match_cv_to_job(CV_PARTIAL, JOB)
    assert partial.score > unreadable.score


def test_explanation_warns_when_no_skill_is_detected_in_the_cv():
    result = match_cv_to_job(CV_UNREADABLE, JOB)
    explanation = build_match_explanation(CV_UNREADABLE, JOB, result.score, result.common_skills)
    assert any("Aucune competence detectee dans le CV" in line for line in explanation["vigilance"])


def test_explanation_does_not_warn_when_the_cv_has_skills():
    result = match_cv_to_job(CV_PARTIAL, JOB)
    explanation = build_match_explanation(CV_PARTIAL, JOB, result.score, result.common_skills)
    assert not any("Aucune competence detectee dans le CV" in line for line in explanation["vigilance"])
