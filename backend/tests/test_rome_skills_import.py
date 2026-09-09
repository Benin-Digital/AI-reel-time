"""Tests de non-regression : import massif du referentiel 'savoir' de ROME 4.0
(France Travail, Licence Ouverte) dans taxonomy.py.

Contexte : taxonomy.py etait un dictionnaire de ~300-400 competences
maintenues a la main, insuffisant pour des CV couvrant tous les domaines
(banque, assurance, telecom, retail, tech...). ROME (contrairement a ESCO,
dont les libelles sont des phrases-taches type "gerer des demandes
d'indemnisation") utilise des libelles courts type mot-cle, compatibles
avec le matching exact de find_skills().

~8500 entrees ont ete importees automatiquement (impossible a relire une
par une) depuis unix_referentiel_savoir_v461_utf8.csv, filtrees aux
categories de connaissances professionnelles concretes (logiciels,
langages informatiques, normes/reglementations, techniques), en excluant
diplomes/certifications et domaines hors-sujet (agriculture, sport, arts).

Trois bugs trouves et corriges pendant l'import, couverts ici :
1. Des mots generiques de secteur ("Finance", "Assurances", "Marketing"...)
   reproduisaient exactement le faux-positif deja corrige une fois pour la
   liste blanche de scoring (voir test_finance_sector_false_positive.py) :
   toute mention du secteur ("experience en assurance") declenchait un faux
   hit de competence.
2. Les apostrophes/tirets ("E-commerce", "Systeme d'exploitation Windows")
   n'etaient pas normalises en espaces avant stockage, alors que le
   tokenizer de find_skills() les traite comme separateurs de mots a la
   lecture — l'alias stocke ne matchait donc jamais le meme texte recherche.
3. Deux alias courts de l'import ("c" -> "C", "son" -> "Son") collidaient
   avec des mots grammaticaux francais extremement courants une fois le
   texte tokenise : "c'est"/"c'etait" perd son apostrophe au tokenizing et
   redevient le bare token "c", et "son/sa/ses" (possessif) est un des mots
   les plus frequents du francais. Resultat : la phrase la plus banale
   ("...pour son equipe, c'etait...") declenchait deux fausses competences
   ("C" le langage, "Son"). Corrige dans _build_lookup() (taxonomy.py) en
   excluant les alias ROME a 1 caractere et un petit set nomme
   (_ROME_ALIAS_STOPWORDS) pour les cas >= 2 caracteres trouves. Les autres
   alias courts a risque moindre (grec, turc, taxi, moto...) n'ont pas ete
   touches : ce sont souvent des mentions legitimes (ex: "parle grec" est un
   vrai signal de competence linguistique), contrairement a "c"/"son" qui ne
   peuvent jamais l'etre dans un texte francais courant.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.taxonomy import _SKILLS, find_skills, normalize_skill

_ROME_PATH = Path(__file__).parent.parent / "app" / "services" / "rome_skills_data.json"


def test_rome_data_file_loads_and_is_substantial():
    data = json.loads(_ROME_PATH.read_text(encoding="utf-8"))
    assert len(data) > 5000, "l'import ROME semble avoir ete tronque ou vide"


def test_generic_sector_words_are_not_skills():
    """Reproduit le bug trouve pendant l'import : un secteur d'activite
    mentionne dans un CV/offre ne doit jamais devenir une 'competence'."""
    # Note: "presse" n'est pas teste ici — c'est un alias pre-existant du
    # dictionnaire fait main ("Relations presse": [..., "presse"]), sans
    # rapport avec cet import, et hors perimetre de ce correctif.
    for word in ("finance", "assurances", "industrie", "informatique",
                 "marketing", "design", "restauration", "medias"):
        assert normalize_skill(word) is None, f"{word!r} ne doit pas resoudre a une competence"

    result = find_skills("Expérience sectorielle : Banque, Finance, Transport, Telecom, RH")
    assert "Finance" not in result
    assert "Informatique" not in result


def test_apostrophe_and_hyphen_aliases_are_matchable():
    """Reproduit le second bug : un alias avec apostrophe/tiret stocke tel
    quel n'est jamais retrouve car le tokenizer les traite comme separateurs."""
    assert "E-commerce" in find_skills("E-commerce")
    assert "Système d'exploitation Windows" in find_skills("Système d'exploitation Windows")


def test_real_rome_terms_are_now_recognized():
    """Echantillon de vrais termes absents avant l'import (verifie manuellement
    pendant l'audit), desormais couverts."""
    cases = {
        "Cobol": "Cobol",
        "Delphi": "Delphi",
        "Microsoft Active Directory": "Microsoft Active Directory",
        "Réglementation de Bâle III": "Réglementation de Bâle III",
        "Cryptographie": "Cryptographie",
        "Science actuarielle": "Science actuarielle",
    }
    for text, expected in cases.items():
        assert expected in find_skills(text), f"{text!r} devrait resoudre a {expected!r}"


def test_common_french_function_words_do_not_trigger_rome_skills():
    """Reproduit le troisieme bug : des mots grammaticaux francais ordinaires
    ne doivent jamais devenir une 'competence' a cause d'un alias ROME court."""
    assert normalize_skill("c") is None
    assert normalize_skill("son") is None

    result = find_skills("C'était un projet passionnant pour son équipe.")
    assert "C" not in result
    assert "Son" not in result


def test_legitimate_short_rome_terms_still_resolve():
    """Garde-fou : le filtre anti-faux-positif ne doit pas etre trop large et
    supprimer des mentions de competence reelles a cote des mots-outils."""
    assert find_skills("Je parle couramment le grec et le turc.") == ["Grec", "Turc"]


def test_hand_curated_entry_always_wins_over_rome():
    """_SKILLS (curated a la main) doit toujours l'emporter sur la couche
    ROME en cas de conflit d'alias — verifie sur quelques ancres connues du
    dictionnaire existant plutot que de deviner un vrai conflit."""
    for canonical in ("Python", "SAP", "Gestion de projet", "Permis B"):
        assert canonical in _SKILLS
        # le premier alias de chaque entree doit toujours resoudre au bon canonical
        assert normalize_skill(_SKILLS[canonical][0]) == canonical
