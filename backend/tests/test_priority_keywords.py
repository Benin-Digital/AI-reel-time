"""Tests : mots-cles prioritaires recrutant (JobDocument.priority_keywords).

Contexte : chaque offre reelle observee en production est accompagnee d'un
"Mots Cles.docx" -- une liste courte de termes que le recruteur a
manuellement juges prioritaires en relisant l'offre, souvent des acronymes
metier (LOD2, DORA, TRM) absents du dictionnaire de competences (taxonomy.py).
Injecter ces termes tels quels dans le texte de l'offre ne suffit pas :
find_skills() ne les reconnaitrait toujours pas comme competence, quel que
soit le nombre de fois qu'ils apparaissent. Ces mots-cles doivent donc etre
ajoutes DIRECTEMENT a required_skill_terms, en contournant la taxonomie pour
les termes qu'elle ne connait pas.
"""
from __future__ import annotations

from app.services.matcher import match_cv_to_job, split_priority_keywords


def test_split_priority_keywords_drops_blank_lines_and_header():
    raw = "Mots Clés :\nChef de projet\n\nMOA / AMOA\n"
    assert split_priority_keywords(raw) == ["Chef de projet", "MOA / AMOA"]


def test_split_priority_keywords_handles_none_and_empty():
    assert split_priority_keywords(None) == []
    assert split_priority_keywords("") == []
    assert split_priority_keywords("   \n  \n") == []


def test_taxonomy_recognized_keyword_normalizes_to_canonical():
    """"python" est un alias taxonomy existant -- le mot-cle prioritaire
    (ecrit en minuscules, comme souvent dans un Mots Cles.docx) doit
    reprendre exactement le meme canonique ("Python") que celui que
    find_skills() produirait, pour matcher un CV qui le mentionne."""
    cv = "Développeur backend avec une solide expérience en Python."
    job = "Poste: Développeur. Compétences requises: gestion de projet."
    result = match_cv_to_job(cv, job, priority_keywords="python")
    assert "Python" in result.common_skills


def test_taxonomy_unknown_keyword_is_matched_via_literal_cv_text_scan():
    """"LOD2" n'existe dans aucun dictionnaire de competences -- trouve en
    production sur une offre "Consultant Chef de projet DORA". Doit quand
    meme etre reconnu si le CV contient litteralement le mot."""
    cv = "Consultant risques bancaires. Experience LOD2 et LOD1 en conformite."
    job = "Poste: Analyste risque. Competences requises: gouvernance."
    result = match_cv_to_job(cv, job, priority_keywords="LOD2")
    assert "LOD2" in result.common_skills


def test_taxonomy_unknown_keyword_absent_from_cv_is_flagged_missing():
    cv = "Chef de projet generaliste, aucune mention de conformite bancaire."
    job = "Poste: Analyste risque. Competences requises: gouvernance."
    result = match_cv_to_job(cv, job, priority_keywords="DORA")
    assert "DORA" in result.missing_skills
    assert "DORA" not in result.common_skills


def test_priority_keywords_widen_required_skill_set_and_can_lower_coverage():
    """Une offre qui, sans mots-cles prioritaires, semble parfaitement
    couverte doit refleter une couverture plus stricte une fois les
    priorites du recruteur prises en compte -- exactement le trou de score
    trouve en production (bug 1) sur des competences metier absentes de la
    taxonomie generale."""
    cv = "Consultant gouvernance et conformite bancaire, tres experimente."
    job = "Poste: Analyste risque. Competences requises: gouvernance, conformite."
    without = match_cv_to_job(cv, job)
    with_priority = match_cv_to_job(cv, job, priority_keywords="gouvernance\nISO 27001\nLOD2")
    assert without.score_skills == 1.0, "sans mots-cles prioritaires, couverture deja totale"
    assert with_priority.score_skills < without.score_skills, (
        "ISO 27001 et LOD2, absents du CV, doivent faire baisser la couverture "
        f"une fois pris en compte, obtenu {with_priority.score_skills}"
    )


def test_no_priority_keywords_is_a_no_op():
    """Un job sans priority_keywords ne doit produire aucun changement de
    comportement par rapport a avant cette fonctionnalite."""
    cv = "Développeur Python, Django, PostgreSQL."
    job = "Poste: Développeur Backend. Compétences requises: Python, Django."
    a = match_cv_to_job(cv, job)
    b = match_cv_to_job(cv, job, priority_keywords=None)
    assert a.score == b.score
    assert a.score_skills == b.score_skills
