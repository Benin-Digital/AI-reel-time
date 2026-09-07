"""Test : les mots de secteur generiques ne sont plus des competences.

Le mot "finance" figurait dans la liste blanche scoring_skill_keywords,
qui force un match exact en plus de la taxonomie. Resultat : toute mention
d'un secteur ("Experience sectorielle : Banque, Finance, Transport...")
produisait une fausse competence "finance". "procurement" y etait aussi,
en doublon de l'entree taxonomie "Approvisionnement" (plus precise).

Les deux ont ete retires de la liste blanche. Les vraies competences
finance restent couvertes par la taxonomie (SAP FI, Analyse financiere,
Controle de gestion...).
"""
from __future__ import annotations

from app.services.structured import _extract_skill_terms


def test_finance_sector_word_is_not_a_skill():
    result = _extract_skill_terms(
        "Expérience sectorielle : Banque, Finance, Transport, Telecom, RH"
    )
    assert "finance" not in [s.lower() for s in result]


def test_real_finance_skills_still_covered_by_taxonomy():
    """Les competences finance specifiques restent detectees (via taxonomie)."""
    from app.services.taxonomy import find_skills

    assert "Analyse financière" in find_skills("analyse financiere et modeles financiers")
    assert "SAP FI" in find_skills("parametrage SAP FICO")


def test_procurement_still_covered_by_taxonomy():
    """procurement retire de la whitelist mais toujours capte par la taxonomie."""
    from app.services.taxonomy import find_skills

    assert "Approvisionnement" in find_skills("procurement and purchasing")
