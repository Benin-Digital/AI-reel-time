"""Tests : indicateur de confiance par composante (F7).

Chaque composante du score peut renvoyer une valeur neutre (0.5) pour deux
raisons tres differentes :
  - legitime : l'offre n'exige rien sur ce point (pas de langue requise,
    pas de type de contrat precise) ;
  - echec : l'information n'a pas pu etre extraite (section formation
    illisible, annees d'experience non detectees).

Avant, les deux cas donnaient un 0.5 identique, indistinguable pour le RH.
match_cv_to_job() expose desormais low_confidence_components : la liste des
composantes dont le score neutre/par defaut vient d'une ABSENCE d'info
plutot que d'une vraie comparaison. Les scores eux-memes sont inchanges
(garanti par les tests de scoring existants).
"""
from __future__ import annotations

from app.services.matcher import match_cv_to_job

CV_COMPLETE = """Développeur Python 5 ans d'expérience.
Compétences: Python, Django, PostgreSQL, Docker.
Formation: Master informatique Université de Paris.
Langues: Français courant, Anglais courant."""

JOB_COMPLETE = """Poste Développeur Python. 3 ans requis.
Compétences requises: Python, Django, PostgreSQL.
Formation: Bac+5 informatique.
Langues: Français, Anglais."""

CV_MINIMAL = "Développeur Python. Compétences: Python, Django."
JOB_MINIMAL = "Cherche développeur. Compétences: Python, Django, Kubernetes."


def test_low_confidence_field_exists_and_is_a_list():
    result = match_cv_to_job(CV_COMPLETE, JOB_COMPLETE)
    assert isinstance(result.low_confidence_components, list)


def test_minimal_job_flags_missing_components():
    """Une offre sans exigence de langue/contrat/formation et un CV sans
    annees explicites -> ces composantes doivent etre signalees."""
    result = match_cv_to_job(CV_MINIMAL, JOB_MINIMAL)
    for comp in ("experience", "education", "languages", "contract"):
        assert comp in result.low_confidence_components, (
            f"{comp} devrait etre en faible confiance : "
            f"{result.low_confidence_components}"
        )


def test_skills_present_is_not_low_confidence():
    """Quand des competences sont extraites des deux cotes, 'skills' repose
    sur une vraie comparaison et ne doit pas etre signale."""
    result = match_cv_to_job(CV_MINIMAL, JOB_MINIMAL)
    assert "skills" not in result.low_confidence_components


def test_semantic_never_flagged():
    """La composante semantique n'est jamais dans la liste (le
    cross-encoder produit toujours une vraie comparaison quand dispo, et
    la liste ne couvre que les composantes structurees)."""
    result = match_cv_to_job(CV_MINIMAL, JOB_MINIMAL)
    assert "semantic" not in result.low_confidence_components


def test_complete_pair_has_fewer_low_confidence_than_minimal():
    """Un couple riche en infos doit avoir moins de composantes en faible
    confiance qu'un couple minimal."""
    complete = match_cv_to_job(CV_COMPLETE, JOB_COMPLETE)
    minimal = match_cv_to_job(CV_MINIMAL, JOB_MINIMAL)
    assert len(complete.low_confidence_components) < len(minimal.low_confidence_components)


def test_scores_unchanged_by_confidence_tracking():
    """Garde-fou : l'ajout du suivi de confiance ne doit PAS modifier les
    scores. On verifie que les composantes restent dans [0, 1] et le score
    global dans [0, 100] — les valeurs exactes sont verrouillees par les
    tests de scoring existants (test_matcher, test_validation_dataset)."""
    result = match_cv_to_job(CV_COMPLETE, JOB_COMPLETE)
    assert 0.0 <= result.score <= 100.0
    for comp in (result.score_skills, result.score_experience,
                 result.score_education, result.score_languages,
                 result.score_contract, result.score_semantic):
        assert 0.0 <= comp <= 1.0
