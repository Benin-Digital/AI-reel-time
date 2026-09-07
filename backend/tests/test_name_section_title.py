"""Tests : la detection de nom rejette les titres de section (bug du nom).

Sur des CV a mise en page complexe, _extract_name_rule_based prenait un
titre de section en gras/majuscules pour le nom de la personne :
"MISSIONS EFFECTUEES", "Connaissances Techniques", ou — quand l'extraction
multi-colonnes desordonne le texte — un mot d'action comme "Developpement
Deploiement".

Deux mecanismes renforces :
- _NAME_SECTION_RE : ajout de mission/connaissance/technique/realisation/
  parcours/diplome/savoir/responsabilite/objectif/domaine/presentation.
- _NAME_STOP_WORDS : ajout des mots d'action/section courants
  (developpement, deploiement, analyse, gestion...).

Objectif : ne plus JAMAIS afficher un faux nom. Quand le vrai nom n'est
pas atteignable (colonne laterale non prioritaire a l'extraction), renvoyer
None est acceptable — un champ vide vaut mieux qu'un faux nom pour le RH.
Les vrais noms deja detectes ne doivent pas etre perdus.
"""
from __future__ import annotations

from app.services.structured import _extract_name_rule_based


# ── Titres de section : ne doivent plus etre pris pour un nom ─────────────────

def test_section_title_is_not_a_name():
    assert _extract_name_rule_based(["MISSIONS EFFECTUÉES", "Chef de Projet"]) is None
    assert _extract_name_rule_based(["RÉALISATIONS PROFESSIONNELLES", "..."]) is None
    assert _extract_name_rule_based(["DOMAINES DE COMPÉTENCES", "..."]) is None


def test_action_words_are_not_a_name():
    """Extraction multi-colonnes desordonnee : un mot d'action en tete ne
    doit pas devenir un nom."""
    assert _extract_name_rule_based(["Développement Déploiement", "des flux ETL"]) is None
    assert _extract_name_rule_based(["Analyse Conception", "..."]) is None


# ── Vrais noms : ne doivent pas etre perdus ──────────────────────────────────

def test_real_names_still_detected():
    assert _extract_name_rule_based(["Laurent BOSSELY", "07 88 37 89 65"]) == "Laurent BOSSELY"
    assert _extract_name_rule_based(["Samuel DENIS", "email@x.fr"]) == "Samuel DENIS"
    assert _extract_name_rule_based(["Rachida OMARI", "Chef de projets"]) == "Rachida OMARI"
    assert _extract_name_rule_based(["Sabrina CHERGUI", "121 avenue"]) == "Sabrina CHERGUI"
    assert _extract_name_rule_based(["Marie Curie", "Chercheuse"]) == "Marie Curie"
