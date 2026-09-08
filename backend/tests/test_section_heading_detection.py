"""Tests de non-regression : _match_section()/_is_heading() detectaient un
alias de section par simple sous-chaine, sans frontiere de mot ni garde de
longueur. Consequence : une phrase normale contenant par hasard un mot-alias
- meme COLLE a l'interieur d'un autre mot ("role" dans "controle") - etait
classee comme un changement de section, et son propre contenu etait
silencieusement efface (jamais rattache a aucune section).

Les alias couverts (role, experience, formation, universite, ecole...) sont
des mots tres courants du CV francais : le risque etait eleve sur du texte
reel, pas un cas exotique.
"""
from __future__ import annotations

from app.services.parser import _match_section, parse_document


def test_alias_glued_inside_unrelated_word_is_not_a_heading():
    """'role' est un alias de job_required, mais 'controle' n'a rien a voir."""
    assert _match_section("Controle de gestion et suivi budgetaire mensuel.") is None


def test_long_sentence_containing_an_alias_word_is_not_a_heading():
    assert _match_section(
        "J'ai acquis une solide experience en gestion de projet sur plusieurs annees."
    ) is None


def test_real_short_headings_still_match():
    assert _match_section("Expérience") == "experience"
    assert _match_section("Formation") == "education"
    assert _match_section("Compétences requises") == "job_required"


def test_education_section_survives_a_sentence_containing_universite():
    """Repro reelle : 'Universite' (alias education) glisse dans une phrase
    normale et effacait toute la section Formation."""
    cv_text = (
        "Formation\n"
        "Master en Litterature Francaise, obtenu avec mention "
        "a l Universite de Lyon en 2015."
    )
    doc = parse_document(cv_text, kind="cv")
    assert "Litterature" in doc.education_text
    assert "Lyon" in doc.education_text
