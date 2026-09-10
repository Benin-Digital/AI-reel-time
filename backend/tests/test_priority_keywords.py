"""Tests : mots-cles prioritaires recrutant (JobDocument.priority_keywords).

Contexte : chaque offre reelle observee en production est accompagnee d'un
"Mots Cles.docx" -- une liste courte de termes que le recruteur a
manuellement juges prioritaires en relisant l'offre, souvent des acronymes
metier (DORA, TRM) absents du dictionnaire de competences (taxonomy.py).

Ces mots-cles ont leur PROPRE composante de score (score_priority_keywords,
poids dedie dans _DEFAULT_W), distincte de la couverture generale de
competences (score_skills) -- pas simplement ajoutes a required_skill_terms.
Premiere version (melangee a required_skill_terms) laissait un CV compenser
des mots-cles prioritaires manquants en couvrant suffisamment d'AUTRES
competences auto-detectees ; une composante a part, plafonnee comme
score_skills, rend ca impossible.
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
    assert "Python" in result.priority_keywords_matched
    assert result.score_priority_keywords == 1.0
    # La composante generale de competences reste independante : "Python"
    # n'est jamais ajoute a required_skill_terms.
    assert "Python" not in result.common_skills


def test_taxonomy_unknown_keyword_is_matched_via_literal_cv_text_scan():
    """"TRM" n'existe dans aucun dictionnaire de competences (exclu
    deliberement de taxonomy.py, acronyme trop ambigu pour le dictionnaire
    global) -- trouve en production sur une offre "Consultant Chef de projet
    DORA". Doit quand meme etre reconnu si le CV contient litteralement le
    mot."""
    cv = "Consultant risques bancaires. Experience TRM et gestion des tiers en conformite."
    job = "Poste: Analyste risque. Competences requises: gouvernance."
    result = match_cv_to_job(cv, job, priority_keywords="TRM")
    assert "TRM" in result.priority_keywords_matched
    assert result.score_priority_keywords == 1.0


def test_taxonomy_unknown_keyword_absent_from_cv_lowers_the_dedicated_score():
    cv = "Chef de projet generaliste, aucune mention de conformite bancaire."
    job = "Poste: Analyste risque. Competences requises: gouvernance."
    result = match_cv_to_job(cv, job, priority_keywords="DORA")
    assert "DORA" not in result.priority_keywords_matched
    assert result.score_priority_keywords == 0.0
    assert result.priority_keywords_total == 1


def test_missing_priority_keywords_cap_the_final_score():
    """Meme raisonnement que le plafond de score_skills (bug 1) : un CV qui
    rate la majorite des mots-cles prioritaires ne doit pas pouvoir
    compenser avec le reste (semantique, competences generales...)."""
    cv = "Consultant gouvernance et conformite bancaire, tres experimente, excellent communicant."
    job = "Poste: Analyste risque. Competences requises: gouvernance, conformite."
    without = match_cv_to_job(cv, job)
    with_priority = match_cv_to_job(cv, job, priority_keywords="gouvernance\nISO 27001\nLOD2\nTRM")
    assert with_priority.score < without.score, (
        "3 mots-cles prioritaires sur 4 absents du CV doivent faire baisser "
        f"le score final, obtenu sans={without.score} avec={with_priority.score}"
    )
    assert with_priority.score <= 62.5, (
        f"1/4 de couverture prioritaire doit plafonner le score (0.5 + 0.5*0.25 = 62.5%), "
        f"obtenu {with_priority.score}"
    )


def test_priority_keywords_score_is_none_without_any_keyword():
    cv = "Développeur Python, Django, PostgreSQL."
    job = "Poste: Développeur Backend. Compétences requises: Python, Django."
    result = match_cv_to_job(cv, job)
    assert result.score_priority_keywords is None
    assert result.priority_keywords_matched == []
    assert result.priority_keywords_total == 0


def test_no_priority_keywords_is_a_no_op():
    """Un job sans priority_keywords ne doit produire aucun changement de
    comportement par rapport a avant cette fonctionnalite."""
    cv = "Développeur Python, Django, PostgreSQL."
    job = "Poste: Développeur Backend. Compétences requises: Python, Django."
    a = match_cv_to_job(cv, job)
    b = match_cv_to_job(cv, job, priority_keywords=None)
    assert a.score == b.score
    assert a.score_skills == b.score_skills
