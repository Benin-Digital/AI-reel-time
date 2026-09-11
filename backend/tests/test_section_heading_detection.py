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


def test_bullet_label_with_a_skill_alias_word_is_not_a_heading():
    """Regression reelle (production, 2026-09-11) : "Technologies et outils
    utilises :" est un libelle de puce PAR POSTE ("les technologies que
    j'ai utilisees pour CE poste"), pas un titre de section Competences --
    meme s'il contient "technologies"/"outils" (tous deux alias de
    Competences). Le mot "utilises" n'etant ni un connecteur ni un autre
    alias du meme groupe, la ligne entiere doit etre rejetee."""
    assert _match_section("Technologies et outils utilises") is None
    assert _match_section("Outils utilises") is None


def test_heading_with_a_qualifier_word_still_matches():
    """A l'inverse, un vrai titre etendu d'un simple qualificatif generique
    ("professionnelles", "principales"...) doit toujours etre reconnu."""
    assert _match_section("Experiences professionnelles") == "experience"
    assert _match_section("Competences principales") == "skills"


def test_compound_heading_of_same_section_aliases_still_matches():
    """Deux mots-alias du MEME groupe cote a cote restent un vrai titre
    ("Competences et connaissances" = Competences + Connaissances, tous
    deux alias de Competences) -- contrairement a un alias mele a un mot
    de contenu qui n'en est pas un ("outils utilises")."""
    assert _match_section("Competences et connaissances") == "skills"


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
