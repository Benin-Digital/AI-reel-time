"""Tests de non-regression : import filtre du referentiel de competences
ESCO v1.2.1 (classification francaise) dans taxonomy.py.

Contexte : ESCO couvre ~13 960 competences, mais contrairement a ROME 4.0
(deja importe, voir test_rome_skills_import.py), la grande majorite de ses
libelles sont des phrases-taches completes ("gerer des demandes
d'indemnisation"), pas des termes courts type mot-cle -- inutilisables pour
le matching par sous-chaine de find_skills(). Seules les lignes
skillType=="knowledge" avec un libelle d'au plus 3 mots ont ete retenues
(~1944 competences), a l'exclusion d'une liste de mots generiques de
secteur/lieux qui reproduiraient le meme bug deja corrige une fois pour
ROME (voir test_generic_sector_words_are_not_skills).

Un vrai faux positif a ete trouve et corrige pendant cet import : "Paris"
est a la fois un concept de connaissance ESCO (sens "paris/pronostics",
prise de paris) et le nom de la capitale francaise -- toute offre
mentionnant "poste situe a Paris" declenchait une fausse competence.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.taxonomy import _SKILLS, find_skills, normalize_skill

_ESCO_PATH = Path(__file__).parent.parent / "app" / "services" / "esco_skills_data.json"


def test_esco_data_file_loads_and_is_substantial():
    data = json.loads(_ESCO_PATH.read_text(encoding="utf-8"))
    assert len(data) > 1000, "l'import ESCO semble avoir ete tronque ou vide"


def test_generic_sector_and_place_words_are_not_skills():
    """Meme invariant que pour ROME, plus les noms de lieux propres a ESCO."""
    for word in ("finance", "informatique", "marketing", "assurances",
                 "paris", "londres", "lyon"):
        assert normalize_skill(word) is None, f"{word!r} ne doit pas resoudre a une competence"

    result = find_skills("Le poste est situe a Paris, il faut etre disponible et motive.")
    assert "Paris" not in result


def test_high_frequency_false_positives_found_via_corpus_validation():
    """Regression reelle (validation sur le corpus de 13 715 CV,
    2026-09-16) : ces termes ESCO declenchaient des dizaines a plusieurs
    centaines de fois sur un echantillon de 1500 CV reels, pour des
    raisons distinctes :
    - "migration" (573 hits) : mot generique bien trop large en solo.
    - "anglais" : une LANGUE, pas une competence -- deja capturee par la
      detection de langues, la compter aussi comme skill est une erreur
      de categorie, pas seulement de precision.
    - "cartographie"/"consultation"/"football" : nom generique ou loisir
      (les concepts ESCO "sport/loisir" ne sont jamais des competences
      professionnelles dans ce contexte)."""
    for word in ("migration", "anglais", "cartographie", "consultation",
                 "football", "foot", "bourse", "devises"):
        assert normalize_skill(word) is None, f"{word!r} ne doit pas resoudre a une competence"


def test_two_letter_esco_acronyms_do_not_collide_with_ordinary_text():
    """Regression reelle la plus severe trouvee pendant la validation :
    "Circuits integres" portait les alias "CI"/"IC", qui matchaient
    n'importe quelle sequence de 2 lettres dans un texte ordinaire (257
    hits/1492 CV -- "ci-joint", "ci-dessous", etc.). Un alias ESCO doit
    desormais faire au moins 3 caracteres ; les autres alias legitimes de
    la meme competence (microprocesseur, puce...) restent, eux, valides."""
    assert normalize_skill("ci") is None
    assert normalize_skill("ic") is None
    assert find_skills("Ci-joint mon CV, merci de le lire.") == []
    assert "Circuits intégrés" in find_skills("Je maîtrise les microprocesseurs et circuits intégrés.")


def test_real_esco_terms_are_now_recognized():
    """Echantillon de vrais termes ESCO absents de ROME/du dictionnaire fait
    main avant cet import (verifie manuellement pendant l'audit)."""
    cases = {
        "géomatique": "Géomatique",
        "photogrammétrie": "Photogrammétrie",
    }
    for text, expected in cases.items():
        assert expected in find_skills(text), f"{text!r} devrait resoudre a {expected!r}"


def test_hand_curated_and_rome_entries_always_win_over_esco():
    """_SKILLS (fait main) doit toujours l'emporter sur la couche ESCO en
    cas de conflit d'alias, meme raison que pour ROME."""
    for canonical in ("Python", "SAP", "Gestion de projet"):
        assert canonical in _SKILLS
        assert normalize_skill(_SKILLS[canonical][0]) == canonical
    # "Cryptographie" existe deja via l'import ROME -- l'alias ESCO
    # identique ne doit pas creer de doublon ni de conflit silencieux.
    assert normalize_skill("cryptographie") == "Cryptographie"


def test_no_load_esco_csv_dead_code_left_behind():
    """L'ancienne fonction load_esco_csv() (jamais appelee nulle part,
    sans aucun filtre anti-faux-positif) a ete retiree au profit de
    _esco_skills(), sur le meme modele que _rome_skills()."""
    import app.services.taxonomy as taxonomy_module
    assert not hasattr(taxonomy_module, "load_esco_csv")
