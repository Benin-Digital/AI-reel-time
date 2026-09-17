"""Tests de non-regression : import cible du referentiel O*NET 31.0
(software_skills.csv, telechargement public sans cle API, filtre a
Hot Technology=="Y") dans taxonomy.py.

Contexte : contrairement a ROME/ESCO (milliers d'entrees, import en
masse impossible a relire une par une), ce sous-ensemble ne compte que
~100 entrees -- assez petit pour etre mappe a la main comme le
dictionnaire fait main _SKILLS, avec un bien meilleur controle qualite.
Les libelles source sont en anglais (organisme americain), mais ce sont
des noms de produits/marques (Kubernetes, Snowflake, Terraform...), pas
des descriptions traduites -- ils matchent identiquement dans un CV/
offre en francais.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.taxonomy import find_skills, normalize_skill

_ONET_PATH = Path(__file__).parent.parent / "app" / "services" / "onet_skills_data.json"


def test_onet_data_file_loads_and_is_non_trivial():
    data = json.loads(_ONET_PATH.read_text(encoding="utf-8"))
    assert len(data) > 50, "l'import O*NET semble avoir ete tronque ou vide"


def test_real_onet_hot_technology_terms_are_now_recognized():
    """Echantillon de vrais outils absents de ROME/ESCO/du dictionnaire
    fait main avant cet import (verifie manuellement pendant l'audit)."""
    cases = {
        "kubernetes": "Kubernetes",
        "snowflake": "Snowflake",
        "terraform": "Terraform",
        "grafana": "Grafana",
        "apache airflow": "Apache Airflow",
        "salesforce": "Salesforce",
        "pytorch": "PyTorch",
    }
    for text, expected in cases.items():
        assert expected in find_skills(text), f"{text!r} devrait resoudre a {expected!r}"


def test_ambiguous_single_letter_languages_were_not_reintroduced():
    """O*NET liste "C", "R" et "Go" comme technologies -- tous les trois
    deja geres en toute securite par le dictionnaire fait main via des
    alias non-ambigus uniquement (C# ["c#"...], R ["r stats",
    "langage r"], Golang ["golang"...]), JAMAIS sous leur forme brute a
    une lettre/mot courant (meme risque que le "c" deja exclu pour ROME :
    "c'est"/"c'etait" perd son apostrophe au tokenizing). Cet import ne
    doit pas reintroduire cette forme brute."""
    assert normalize_skill("c") is None
    assert normalize_skill("r") is None
    assert normalize_skill("go") is None
    result = find_skills("On va aller au marche, c'est prevu, puis on ira au travail.")
    assert "C" not in result
    assert "R" not in result


def test_low_value_social_and_us_specific_software_excluded():
    """Facebook/TikTok (signal professionnel trop faible et ambigu) et le
    logiciel metier americain tres specifique (sante/dentaire/immobilier)
    ont ete ecartes au moment de la generation -- voir le script de
    generation, non commite (meme convention que ROME/ESCO)."""
    for word in ("facebook", "tiktok", "meditech", "yardi"):
        assert normalize_skill(word) is None, f"{word!r} ne doit pas resoudre a une competence"


def test_hand_curated_and_bulk_layers_always_win_over_onet():
    """Les acronymes courts deja geres ailleurs (AWS, SQL, HTML, CSS)
    doivent continuer a resoudre via leur alias existant -- l'import
    O*NET ne doit jamais les court-circuiter."""
    assert normalize_skill("aws") == "AWS"
    assert normalize_skill("sql") == "SQL"


def test_words_colliding_with_common_french_usage_are_excluded():
    """Regression reelle la plus severe de cet import, trouvee par
    validation sur le corpus de 13 715 CV (2026-09-17) :
    - "Chef" (l'outil DevOps de gestion de configuration) collisionnait
      avec le mot francais "chef" ("chef de projet", "chef d'equipe"...) :
      540 CV sur 1491 (36%!) declenchaient une fausse competence.
    - "SAS" (le logiciel d'analyse) collisionnait avec la forme juridique
      d'entreprise francaise la plus courante ("Societe par Actions
      Simplifiee", ex: "ACME SAS") : "la societe ACME SAS recherche un
      developpeur" detectait a tort "SAS" comme competence.
    - "Eclipse" seul (sans "IDE") collisionne avec le mot francais
      "eclipse" (phenomene astronomique) : 146 CV/1491 declenchaient une
      fausse competence pour un IDE Java bien moins utilise aujourd'hui.
    Aucune des trois n'a de forme d'alias sure : elles sont exclues, sauf
    "Eclipse IDE" en phrase complete (bien plus specifique)."""
    assert normalize_skill("chef") is None
    assert normalize_skill("sas") is None
    assert normalize_skill("eclipse") is None
    assert normalize_skill("eclipse ide") == "Eclipse IDE"

    assert find_skills("La société ACME SAS recherche un Chef de projet.") == ["Gestion de projet"]


def test_nursing_ide_alias_no_longer_collides_with_the_tech_acronym():
    """Bug pre-existant trouve par ricochet en testant cet import (pas
    introduit par lui) : le dictionnaire fait main avait "ide" comme
    alias de "Soins infirmiers" (Infirmier Diplome d'Etat), qui
    collisionnait avec l'acronyme IDE (Integrated Development
    Environment) desormais tres present via ROME/ESCO/O*NET
    ("Eclipse IDE", "un bon IDE"...)."""
    assert normalize_skill("ide") is None
    assert "Eclipse IDE" in find_skills("Experience avec Eclipse IDE et IntelliJ.")
    assert "Soins infirmiers" not in find_skills("Experience avec Eclipse IDE et IntelliJ.")
