"""Tests : seniorite implicite (titre/texte du poste) quand aucun chiffre
d'annees explicite n'existe.

Contexte (audit reel, 2026-09-11) : 5 des 6 offres reelles echantillonnees
dans le dossier de test n'enoncent AUCUN chiffre d'annees ("Chef de Projet
MOA - Indemnisation IARD", "Data Analyst / Concepteur Decisionnel Senior"...
disent juste "senior"/"expert"/"experience confirmee") -- la composante
experience etait alors totalement exclue du score (has_signal=False),
quel que soit son poids. _infer_seniority_years() recupere un seuil
approximatif depuis le langage de seniorite du titre, avec un impact
DAMPENED (moitie moins fort qu'un vrai chiffre) puisque "senior" est un
signal bien plus ambigu qu'un recruteur ecrivant "5 ans minimum".
"""
from __future__ import annotations

from app.services.matcher import _experience_score, _infer_seniority_years
from app.services.parser import ParsedDocument


def _job(title: str, years: int = 0) -> ParsedDocument:
    return ParsedDocument(
        kind="job", domain="tech", raw_text=title, cleaned_text=title,
        experience_years=years,
    )


def _cv(years: int) -> ParsedDocument:
    return ParsedDocument(
        kind="cv", domain="tech", raw_text="", cleaned_text="",
        experience_years=years,
    )


def test_infer_seniority_years_recognizes_common_french_levels():
    assert _infer_seniority_years(_job("Consultant Expert Décisionnel")) == 8
    assert _infer_seniority_years(_job("Data Analyst Sénior H/F")) == 5
    assert _infer_seniority_years(_job("Profil confirmé recherché")) == 3
    assert _infer_seniority_years(_job("Développeur Junior")) == 1
    assert _infer_seniority_years(_job("Chef de Projet IT")) == 0


def test_no_explicit_years_but_senior_title_activates_the_component():
    """Cas reel : offre "Data Analyst / Concepteur Decisionnel Senior",
    aucun chiffre d'annees enonce -- avant ce correctif, has_signal
    restait False (composante totalement exclue du score)."""
    job = _job("Concepteur Décisionnel Sénior")
    junior_cv = _cv(1)
    score, ok = _experience_score(junior_cv, job)
    assert ok is True, "le titre 'senior' doit activer la composante experience"
    assert score < 0.75, (
        f"un junior (1 an) sur un poste 'senior' (seuil implicite ~5 ans) "
        f"doit etre penalise, obtenu {score}"
    )


def test_no_explicit_years_and_no_seniority_signal_stays_excluded():
    """Non-regression : une offre generaliste sans aucun signal de
    seniorite reste exclue du score, comme avant ce correctif."""
    job = _job("Chef de Projet IT")
    cv = _cv(1)
    score, ok = _experience_score(cv, job)
    assert ok is False


def test_inferred_requirement_is_dampened_versus_an_explicit_one():
    """Un seuil INFERE (mot 'senior') doit peser moins fort qu'un vrai
    chiffre explicite pour le meme ecart junior/senior -- 'senior' est un
    signal bien plus ambigu qu'un recruteur ecrivant '5 ans minimum'."""
    explicit_job = _job("Concepteur Décisionnel", years=5)
    inferred_job = _job("Concepteur Décisionnel Sénior")
    junior_cv = _cv(1)

    explicit_score, _ = _experience_score(junior_cv, explicit_job)
    inferred_score, _ = _experience_score(junior_cv, inferred_job)
    assert inferred_score > explicit_score, (
        "le score sous un seuil INFERE doit rester plus proche de la "
        f"neutralite qu'un vrai chiffre explicite -- explicite="
        f"{explicit_score} infere={inferred_score}"
    )


def test_inferred_requirement_still_gives_full_credit_to_a_comfortable_match():
    """Un candidat clairement au niveau (ou au-dessus) du seuil implicite
    ne doit jamais etre penalise par ce mecanisme."""
    job = _job("Concepteur Décisionnel Sénior")  # seuil implicite ~5 ans
    senior_cv = _cv(8)
    score, ok = _experience_score(senior_cv, job)
    assert ok is True
    # L'amortissement s'applique uniformement (meme a un bon match) --
    # 0.5*1.0 + 0.5*0.75 = 0.875, pas 1.0 pile, mais tres largement au
    # dessus de la neutralite : aucune penalite reelle n'est appliquee ici.
    assert score >= 0.85
