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

from app.services import structured
from app.services.structured import _extract_name_rule_based, build_document_profile


# ── Titres de section : ne doivent plus etre pris pour un nom ─────────────────

def test_section_title_is_not_a_name():
    assert _extract_name_rule_based(["MISSIONS EFFECTUÉES", "Chef de Projet"]) is None
    assert _extract_name_rule_based(["RÉALISATIONS PROFESSIONNELLES", "..."]) is None
    assert _extract_name_rule_based(["DOMAINES DE COMPÉTENCES", "..."]) is None


def test_centres_dinterets_is_not_a_name():
    """Regression reelle (production, 2026-09-11) : un CV dont le nom
    n'apparait nulle part comme texte autonome (logo/bandeau non extrait)
    faisait remonter "CENTRES D'INTERETS" -- un titre de section usuel non
    couvert par _NAME_SECTION_RE (qui avait "loisir"/"hobby" mais pas
    "interet") -- comme faux nom du candidat, affiche tel quel dans toute
    l'interface (bibliotheque CV, correspondances)."""
    lines = [
        "PROFIL", "Chef de projet IT et Product Owner,",
        "CONTACT", "COMPETENCES (PRINCIPALES)", "LANGUES",
        "Français : Langue maternelle", "Anglais : Courant",
        "CENTRES D'INTERETS", "Passion pour le sport",
    ]
    assert _extract_name_rule_based(lines) is None


def test_action_words_are_not_a_name():
    """Extraction multi-colonnes desordonnee : un mot d'action en tete ne
    doit pas devenir un nom."""
    assert _extract_name_rule_based(["Développement Déploiement", "des flux ETL"]) is None
    assert _extract_name_rule_based(["Analyse Conception", "..."]) is None


# ── En-tete "espacee lettre par lettre" : ne doit jamais produire un faux nom ──

def test_letter_spaced_header_is_not_a_name():
    """Regression reelle (production, 2026-09-09 puis a nouveau 2026-09-11) :
    un CV dont le nom est mis en forme "P E L A G I E N J I K I" (une lettre
    par mot, style decoratif courant) faisait deux degats en cascade :
    1. Le vrai nom n'etait jamais lisible (chaque lettre seule < 2 caracteres
       est rejetee par _collect_name_words).
    2. Le titre de section "É D U C A T I O N", lui aussi espace, ne
       correspondait plus a _NAME_SECTION_RE (qui cherche "education" en
       continu) -- son contenu (diplome, ecole) redevenait alors une cible
       valide pour l'heuristique de nom, produisant successivement les faux
       noms "COMMERCE ET" puis "LYCÉE LOUIS ARMAND".

    Le fix du 09-09 a bien empeche _extract_name_rule_based lui-meme de
    renvoyer ce faux nom -- mais il renvoyait alors None, indiscernable de
    "aucun indice de nom nulle part, se fier au NER" : l'appelant
    (build_document_profile) laissait donc le NER (qui lit le meme texte
    espace-lettre-par-lettre et se trompe pareillement) imposer "LOUIS
    ARMAND" sans jamais etre corrige -- exactement le meme faux nom affiche
    en production le 09-11. Desormais "" (chaine vide, PAS None) signale
    specifiquement ce cas : l'appelant doit alors ignorer le NER aussi."""
    lines = [
        "P | N",
        "P E L A G I E N J I K I",
        "C O N S U LT A N T E G E S T I O N D E B A S E",
        "pelagienjiki@yahoo.fr",
        "É D U C A T I O N",
        "BACCALAURÉAT",
        "COMMERCE ET SERVICE",
        "LYCÉE LOUIS ARMAND /",
        "Eaubonne, France / 1995",
    ]
    assert _extract_name_rule_based(lines) == ""


def test_ner_false_name_is_cleared_when_header_is_letter_spaced(monkeypatch):
    """Integration : meme quand le NER (spaCy/CamemBERT) affirme avec
    confiance qu'un faux nom ("Louis Armand", lu depuis "Lycee Louis
    Armand") est le person_name, build_document_profile doit l'ignorer une
    fois que _extract_name_rule_based signale un en-tete espace-lettre-par-
    lettre non lisible -- pas seulement quand le NER est desactive."""
    fake_ner_payload = {
        "person_name": "Louis Armand",
        "organization_terms": [],
        "location_terms": [],
        "date_terms": [],
    }
    monkeypatch.setattr(structured, "_extract_ner_entities", lambda text: fake_ner_payload)

    text = "\n".join([
        "P E L A G I E N J I K I",
        "pelagienjiki@yahoo.fr",
        "É D U C A T I O N",
        "LYCÉE LOUIS ARMAND /",
    ])
    profile = build_document_profile(text, kind="cv", enable_ner=True)

    assert profile.person_name is None, (
        f"NER's 'Louis Armand' must be cleared, not surfaced as the candidate's name, got: {profile.person_name!r}"
    )


# ── Vrais noms : ne doivent pas etre perdus ──────────────────────────────────

def test_real_names_still_detected():
    assert _extract_name_rule_based(["Laurent BOSSELY", "07 88 37 89 65"]) == "Laurent BOSSELY"
    assert _extract_name_rule_based(["Samuel DENIS", "email@x.fr"]) == "Samuel DENIS"
    assert _extract_name_rule_based(["Rachida OMARI", "Chef de projets"]) == "Rachida OMARI"
    assert _extract_name_rule_based(["Sabrina CHERGUI", "121 avenue"]) == "Sabrina CHERGUI"
    assert _extract_name_rule_based(["Marie Curie", "Chercheuse"]) == "Marie Curie"
