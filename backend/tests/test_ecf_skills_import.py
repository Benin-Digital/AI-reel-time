"""Tests de non-regression : import du referentiel europeen des
e-Competences (e-CF 3.0, CWA 16234-1:2014, CEN) dans taxonomy.py.

Contexte : contrairement a ROME/ESCO, l'e-CF est un petit referentiel
officiel FIXE de seulement 40 competences TIC (5 domaines : PLANIFIER,
DEVELOPPER, UTILISER, FACILITER, GERER) -- extrait directement de
l'edition francaise du PDF officiel, assez petit pour etre relu
entierement a la main comme le sous-ensemble O*NET Hot Technology.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.taxonomy import normalize_skill

_ECF_PATH = Path(__file__).parent.parent / "app" / "services" / "ecf_skills_data.json"


def test_ecf_data_file_loads_and_has_most_of_the_40_competences():
    data = json.loads(_ECF_PATH.read_text(encoding="utf-8"))
    # 40 total minus "Innovation"/"Tests" (excluded) minus those already
    # covered by the hand-curated dictionary/ROME/ESCO.
    assert 25 <= len(data) <= 35


def test_real_ecf_competences_are_now_recognized():
    """Echantillon de vrais titres e-CF absents du dictionnaire fait
    main/ROME/ESCO avant cet import."""
    cases = {
        "gouvernance du si": "Gouvernance du SI",
        "marketing numérique": "Marketing numérique",
        "gestion des projets et du portefeuille de projets":
            "Gestion des projets et du portefeuille de projets",
        "identification des besoins": "Identification des besoins",
    }
    for text, expected in cases.items():
        assert normalize_skill(text) == expected, f"{text!r} devrait resoudre a {expected!r}"


def test_bare_generic_titles_are_excluded():
    """"Innovation" et "Tests" sont les deux seuls titres e-CF a n'etre
    qu'un mot isole -- bien trop generiques en solo (meme risque que
    "informatique"/"migration" deja exclus pour ROME/ESCO)."""
    assert normalize_skill("innovation") is None
    assert normalize_skill("tests") is None
