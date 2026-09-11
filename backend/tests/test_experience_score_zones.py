"""Tests : les 4 zones du score d'experience (_experience_score).

Contexte (regression reelle, offre "Developpeur Full Stack PHP/Laravel/
VueJS", 5 ans requis, 2026-09-11) : l'ancienne formule traitait "pile la
bonne experience" et "un peu plus" de facon identique (1.0), puis
appliquait un plafond brutal (seuil a 3x -> 0.85, sans rien entre les
deux) pour la sur-qualification. Demande explicite : distinguer
INFERIEUR / EGAL / LEGEREMENT SUPERIEUR / TROP SUPERIEUR, avec une
degradation progressive plutot qu'un seuil abrupt pour la derniere zone.
"""
from __future__ import annotations

from app.services.matcher import _experience_score
from app.services.parser import ParsedDocument


def _doc(years: int) -> ParsedDocument:
    return ParsedDocument(
        kind="job", domain="tech", raw_text="", cleaned_text="",
        experience_years=years,
    )


def test_inferieur_applies_a_linear_shortfall_penalty():
    score, ok = _experience_score(_doc(3), _doc(5))
    assert ok is True
    assert score == 0.6  # 1 - (5-3)/5


def test_egal_gives_full_credit():
    score, ok = _experience_score(_doc(5), _doc(5))
    assert ok is True
    assert score == 1.0


def test_legerement_superieur_gives_full_credit_up_to_double_the_requirement():
    """Un poste "au moins 5 ans" -- une exigence PLANCHER, pas une fenetre
    cible -- ne doit pas penaliser un candidat avec un peu plus
    d'experience : ni 6 ans (1.2x) ni meme 10 ans (2x, la limite haute de
    cette zone) ne sont un defaut ici."""
    for years in (6, 7, 10):
        score, ok = _experience_score(_doc(years), _doc(5))
        assert ok is True
        assert score == 1.0, f"{years} ans pour 5 requis devrait rester a 1.0, obtenu {score}"


def test_trop_superieur_tapers_gradually_instead_of_a_hard_cliff():
    """Au-dela de 2x, le score doit degrader PROGRESSIVEMENT (pas un saut
    brutal a une valeur fixe) jusqu'a un plancher a 4x."""
    just_over, _ = _experience_score(_doc(11), _doc(5))  # ratio 2.2
    mid, _ = _experience_score(_doc(15), _doc(5))  # ratio 3.0
    far_over, _ = _experience_score(_doc(20), _doc(5))  # ratio 4.0 (plancher)
    way_beyond, _ = _experience_score(_doc(50), _doc(5))  # ratio 10 (au-dela du plancher)

    assert 1.0 > just_over > mid > far_over, (
        "la degradation doit etre strictement progressive entre 2x et 4x, "
        f"obtenu just_over={just_over} mid={mid} far_over={far_over}"
    )
    assert far_over == 0.85
    assert way_beyond == 0.85, "au-dela du plancher (4x), le score reste stable, pas de chute supplementaire"


def test_real_production_comparison_hilama_stays_at_full_credit():
    """Regression reelle : Hilama (8 ans reels) contre l'offre PHP/Laravel/
    VueJS (5 ans requis, ratio 1.6) est un cas "legerement superieur" --
    doit rester a 1.0, pas etre traite comme une sur-qualification."""
    score, ok = _experience_score(_doc(8), _doc(5))
    assert ok is True
    assert score == 1.0
