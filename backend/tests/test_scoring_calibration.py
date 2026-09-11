"""Tests de non-regression : recalibrage de la formule de score (F10,
2026-09-11), suite a un audit manuel de 16 CV reels contre une offre
"Data Analyst Expert SAS", avec un jugement humain de reference pour
chaque paire CV/offre.

Trois constats reels ont motive ce recalibrage :

1. Le plancher du plafond competences/mots-cles prioritaires (0.5 + 0.5 *
   couverture) tolerait jusqu'a 50% de score meme a couverture NULLE. Des
   candidats sans aucune competence pertinente scoraient 55-68% sur une
   offre technique specialisee -- tres au-dessus du jugement humain
   (10-20%). Le plancher est abaisse (voir _SKILL_CAP_FLOOR), avec
   l'invariant preserve : une couverture de 100% permet toujours d'atteindre
   100% (plafond = plancher + (1-plancher)*couverture).

2. Les mots-cles prioritaires n'etaient jamais dedupliques par canonique
   taxonomique : un recruteur tapant "SAS Enterprise Guide", "SAS Base",
   "SAS Grid" (3 lignes distinctes, meme outil reel) gonflait le score de
   quiconque mentionnait SAS une seule fois (credit multiplie) ET diluait
   la penalite pour qui ne le mentionnait pas du tout (perte noyee dans
   une douzaine d'autres mots-cles). _resolve_priority_keywords deduplique
   desormais par canonique avant de calculer la couverture.

3. Un plafond global bati sur la couverture moyenne ne peut pas refleter
   qu'un outil precis, repete plusieurs fois par le recruteur, est LE
   requis central du poste : un candidat avec une bonne couverture
   generique (SQL, reporting...) mais zero mention de l'outil-coeur restait
   surestime. Une penalite MULTIPLICATIVE (pas un plafond dur, qui
   ecraserait tous les candidats sans cet outil au meme niveau) est
   appliquee sur la couverture des mots-cles que le recruteur a exprimes
   via au moins 3 lignes distinctes (signal purement generique : aucun nom
   d'outil n'est code en dur).
"""
from __future__ import annotations

from app.services.matcher import (
    _core_keyword_coverage,
    _resolve_priority_keywords,
    match_cv_to_job,
)
from app.services.parser import parse_document


# ── Point 1 : plancher du plafond competences/mots-cles ──────────────────────

def test_zero_skill_coverage_no_longer_floors_at_fifty_percent():
    """Regression reelle : plusieurs CV sans aucune competence pertinente
    pour une offre technique specialisee scoraient 55-68% (bien au-dessus
    du jugement humain, 10-20%) a cause d'un plancher de 50% a couverture
    nulle. Le nouveau plancher est nettement plus bas."""
    cv = """
    Competences: Photoshop, Illustrator, InDesign, identite visuelle.
    Experience: 5 ans en tant que graphiste independant.
    Formation: BTS design graphique.
    """
    job = """
    Poste: Data Analyst Expert SAS.
    Competences requises: SAS, SQL, SGBD, Reporting, Data Engineering.
    Experience requise: Minimum 3 ans en analyse de donnees.
    """
    result = match_cv_to_job(cv, job)
    assert result.score_skills == 0.0
    assert result.score <= 35, (
        f"couverture nulle sur une offre technique doit rester loin en dessous de 50%, "
        f"obtenu {result.score}"
    )


def test_full_skill_coverage_still_reaches_full_score_range():
    """L'invariant du plafond doit tenir : une couverture parfaite ne doit
    jamais etre bridee par le nouveau plancher plus bas."""
    cv = """
    Competences: Python, Django, PostgreSQL, Docker, API REST.
    Experience: 5 ans en developpement backend Python.
    Formation: Master informatique.
    """
    job = """
    Poste: Developpeur Backend Python.
    Competences requises: Python, Django, PostgreSQL, Docker, API REST.
    Experience requise: Minimum 3 ans en developpement backend.
    Formation requise: Bac+5 informatique ou equivalent.
    """
    result = match_cv_to_job(cv, job)
    assert result.score_skills >= 0.9
    assert result.score >= 65, f"couverture quasi totale doit rester un match fort, obtenu {result.score}"


# ── Point 2 : deduplication des mots-cles prioritaires par canonique ─────────

def test_priority_keywords_are_deduplicated_by_taxonomy_canonical():
    """Regression reelle (offre "Data Analyst Expert SAS") : "SAS Enterprise
    Guide", "SAS Base" et "SAS Grid" normalisent tous vers le meme canonique
    "SAS (logiciel)". Sans deduplication, ces 3 lignes comptaient comme 3
    mots-cles distincts -- gonflant le credit d'un candidat qui mentionne
    SAS une seule fois, et diluant la perte pour qui ne le mentionne pas du
    tout dans une douzaine d'autres mots-cles."""
    pk_raw = (
        "SAS Enterprise Guide\n"
        "SAS Base\n"
        "SAS Grid\n"
        "SQL\n"
    )
    # "SAS Base" normalise vers le canonique "SAS (logiciel)" -- contrairement
    # au mot "SAS" seul, volontairement exclu de la taxonomie car trop
    # souvent un suffixe de raison sociale francaise (Societe par Actions
    # Simplifiee) plutot que le logiciel.
    cv_with_sas = parse_document("Competences: SAS Base, SQL, Python.", kind="cv")
    cv_without_sas = parse_document("Competences: SQL, Python.", kind="cv")
    job = parse_document("Offre SAS.", kind="job")
    from app.services.matcher import split_priority_keywords, _apply_priority_keywords

    job.priority_keyword_terms = split_priority_keywords(pk_raw)
    _apply_priority_keywords(cv_with_sas, job)
    matched, all_terms = _resolve_priority_keywords(cv_with_sas, job)
    assert len(all_terms) == 2, f"SAS (logiciel) + SQL, deduplique -- obtenu {all_terms}"
    assert len(matched) == 2

    job2 = parse_document("Offre SAS.", kind="job")
    job2.priority_keyword_terms = split_priority_keywords(pk_raw)
    _apply_priority_keywords(cv_without_sas, job2)
    matched2, all_terms2 = _resolve_priority_keywords(cv_without_sas, job2)
    assert len(all_terms2) == 2
    assert len(matched2) == 1, "seul SQL doit matcher, SAS (logiciel) manque completement"


# ── Point 3 : penalite multiplicative sur l'outil-coeur repete ───────────────

def test_repeated_keyword_with_zero_coverage_triggers_full_penalty():
    """Un canonique tape via >= 3 lignes distinctes et totalement absent du
    CV doit ramener _core_keyword_coverage a 0.0 (penalite maximale)."""
    from app.services.matcher import split_priority_keywords, _apply_priority_keywords

    cv = parse_document("Competences: SQL, Python.", kind="cv")
    job = parse_document("Offre SAS.", kind="job")
    job.priority_keyword_terms = split_priority_keywords(
        "SAS Enterprise Guide\nSAS Base\nSAS Grid\nSQL\n"
    )
    _apply_priority_keywords(cv, job)
    assert _core_keyword_coverage(cv, job) == 0.0


def test_keyword_repeated_only_twice_does_not_trigger_the_core_mechanism():
    """Le seuil est >= 3 repetitions distinctes : 2 lignes pour le meme
    canonique ne doivent pas declencher la penalite (evite les faux
    positifs sur des synonymes courants tapes deux fois par hasard)."""
    from app.services.matcher import split_priority_keywords, _apply_priority_keywords

    cv = parse_document("Competences: Python.", kind="cv")
    job = parse_document("Offre.", kind="job")
    job.priority_keyword_terms = split_priority_keywords(
        "tableaux de bord\nreporting\nSQL\n"
    )
    _apply_priority_keywords(cv, job)
    # "tableaux de bord" et "reporting" normalisent tous deux vers "Reporting"
    # (2 occurrences seulement) -- sous le seuil de 3, donc pas de coeur detecte.
    assert _core_keyword_coverage(cv, job) == 1.0


def test_no_repeated_keyword_means_no_penalty_at_all():
    """Une liste de mots-cles prioritaires ordinaire, sans repetition, ne
    doit jamais declencher ce mecanisme -- la grande majorite des offres."""
    from app.services.matcher import split_priority_keywords, _apply_priority_keywords

    cv = parse_document("Competences: Python.", kind="cv")
    job = parse_document("Offre.", kind="job")
    job.priority_keyword_terms = split_priority_keywords("SAS\nSQL\nReporting\n")
    _apply_priority_keywords(cv, job)
    assert _core_keyword_coverage(cv, job) == 1.0


def test_core_penalty_scales_the_score_instead_of_flooring_it():
    """La penalite est MULTIPLICATIVE (echelle relative), pas un plafond dur
    (min()) qui ecraserait tous les candidats manquant l'outil-coeur au
    meme niveau -- deux candidats differents sur les autres composantes
    doivent rester differents apres application de la penalite."""
    pk_raw = "SAS Enterprise Guide\nSAS Base\nSAS Grid\nSQL\nReporting\nAnalyse des besoins\n"
    job_text = "Offre SAS. Competences requises: SAS, SQL, Reporting, Analyse des besoins."

    strong_other_skills_cv = (
        "Competences: SQL, Reporting, Analyse des besoins, Data Engineering, SGBD.\n"
        "Experience: 10 ans en developpement.\n"
    )
    weak_other_skills_cv = (
        "Competences: SQL.\n"
        "Experience: 1 an.\n"
    )
    result_strong = match_cv_to_job(strong_other_skills_cv, job_text, priority_keywords=pk_raw)
    result_weak = match_cv_to_job(weak_other_skills_cv, job_text, priority_keywords=pk_raw)
    assert result_strong.score != result_weak.score, (
        "deux candidats manquant tous deux l'outil-coeur, mais tres differents "
        "sur le reste, ne doivent pas etre ecrases a un score identique"
    )
    assert result_strong.score > result_weak.score


# ── Point 4 (suite a l'audit) : titre du poste comme second signal "coeur" ──
# Le seuil de repetition (>= 3 lignes) rate un cas tres courant : un
# recruteur qui ne tape l'outil-coeur qu'UNE seule fois comme mot-cle
# prioritaire, mais le nomme dans le TITRE du poste ("Data Analyst Expert
# SAS"). Le titre d'une offre est redige par le recruteur dans un gabarit
# fixe et nomme quasi systematiquement le role/l'outil central -- un signal
# bien plus fiable que la repetition seule. Cote CV, la premiere ligne
# n'est PAS utilisee de la meme facon (souvent juste le nom du candidat).

def test_keyword_mentioned_once_but_present_in_job_title_becomes_core():
    """Regression reelle (offre "Data Analyst Expert SAS", 2026-09-11) :
    un candidat ecrivant simplement "SAS" (sans variante) restait en dehors
    du canonique "SAS (logiciel)" (bare "SAS" exclu de la taxonomie, voir
    taxonomy.py) meme quand le titre du poste nommait explicitement SAS.
    Le titre doit permettre de detecter ce candidat correctement."""
    from app.services.matcher import split_priority_keywords, _apply_priority_keywords

    # "SAS" est tape par le recruteur comme sa PROPRE ligne (en plus des
    # variantes) -- cas reel : le recruteur liste a la fois le nom court et
    # des variantes precises du meme outil.
    pk_raw = "SAS\nSAS Enterprise Guide\nSAS Base\nSAS Grid\n"
    job = parse_document("Data Analyst Expert SAS.\nOffre technique.", kind="job")
    job.priority_keyword_terms = split_priority_keywords(pk_raw)

    # Deux concepts-coeur distincts ici : le mot-cle court "SAS" (nomme
    # dans le titre) et le canonique "SAS (logiciel)" (issu des 3 variantes
    # repetees). Un candidat qui n'ecrit que "SAS" en satisfait un sur
    # deux -- c'est correct : il n'a demontre aucune des variantes
    # precises, seulement la mention generique.
    cv_bare_sas = parse_document("Competences: SAS, Python.", kind="cv")
    _apply_priority_keywords(cv_bare_sas, job)
    assert _core_keyword_coverage(cv_bare_sas, job) == 0.5, (
        "le mot-cle court 'SAS' (tape tel quel par le recruteur, nomme dans le titre) "
        "doit etre credite meme sans les variantes precises -- mais reste a 1 concept "
        "sur 2 puisque 'SAS (logiciel)' (issu des variantes repetees) n'est pas satisfait"
    )

    cv_no_sas = parse_document("Competences: Python.", kind="cv")
    job2 = parse_document("Data Analyst Expert SAS.\nOffre technique.", kind="job")
    job2.priority_keyword_terms = split_priority_keywords(pk_raw)
    _apply_priority_keywords(cv_no_sas, job2)
    assert _core_keyword_coverage(cv_no_sas, job2) == 0.0, (
        "le candidat sans aucune mention de SAS doit etre penalise plus fortement "
        "que celui qui ecrit au moins la forme simple"
    )


def test_job_title_does_not_affect_a_cv_without_repeated_or_titled_keywords():
    """Une offre dont le titre ne nomme aucun mot-cle prioritaire, et sans
    repetition, ne doit declencher aucune penalite -- cas le plus courant."""
    from app.services.matcher import split_priority_keywords, _apply_priority_keywords

    job = parse_document("Chef de Projet IT.\nOffre generaliste.", kind="job")
    job.priority_keyword_terms = split_priority_keywords("Gestion de projet\nAgile\n")
    cv = parse_document("Competences: Excel.", kind="cv")
    _apply_priority_keywords(cv, job)
    assert _core_keyword_coverage(cv, job) == 1.0


# ── Point 5 (suite a l'audit) : education_text inclus dans l'extraction ─────

def test_skill_mentioned_only_in_the_education_section_is_still_detected():
    """Regression reelle (Boubacar Mainassara, 2026-09-11) : son CV liste un
    veritable intitule de poste passe ("Data Analyst") sous un titre de
    section non-standard ("FORMATIONS PROFESSIONNELLES", utilise pour
    melanger postes et diplomes) qui se classe comme Education. Ce terme
    etait invisible pour la detection de competences car education_text
    n'etait pas inclus dans le texte source de find_skills()."""
    cv_text = (
        "Experience\n"
        "2020-2023 : Ingenieur logiciel chez ACME.\n"
        "Formations professionnelles\n"
        "2015 - Diplome d ingenieur\n"
        "Mai 2024 - Novembre 2024 : Data Analyst\n"
    )
    doc = parse_document(cv_text, kind="cv")
    assert "Data Analyst" in doc.skill_terms
