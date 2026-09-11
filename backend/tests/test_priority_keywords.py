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


def test_split_priority_keywords_strips_bullets_from_a_pasted_word_list():
    """Regression reelle (retour recruteur, 2026-09-11) : un "Mots
    Cles.docx" colle tel quel dans le champ garde le glyphe de puce Word
    ("•") devant chaque ligne -- laisse tel quel, "• Chef de projet"
    devient litteralement le "mot-cle", qui ne correspond alors plus a
    rien dans la taxonomie meme quand le CV demontre clairement la
    competence. Le recruteur rapportait devoir le supprimer lui-meme a
    chaque fois avant d'enregistrer."""
    raw = (
        "Mots Clés :\n\n"
        "• Chef de projet\n"
        "• MOA / AMOA\n"
        "• IARD\n"
        "• Assurance\n"
        "• gestion des sinistres / Sinistre\n"
        "• gestion des risques\n"
        "• cycle en V\n"
        "• Agile\n"
        "• Recette"
    )
    assert split_priority_keywords(raw) == [
        "Chef de projet", "MOA / AMOA", "IARD", "Assurance",
        "gestion des sinistres / Sinistre", "gestion des risques",
        "cycle en V", "Agile", "Recette",
    ]


def test_split_priority_keywords_strips_other_common_bullet_and_number_styles():
    assert split_priority_keywords("- SQL\n- Python\n") == ["SQL", "Python"]
    assert split_priority_keywords("* SQL\n* Python\n") == ["SQL", "Python"]
    assert split_priority_keywords("1. SQL\n2) Python\n(3) Java\n") == ["SQL", "Python", "Java"]
    # Un vrai terme technique contenant un tiret ou une barre, sans etre
    # une puce (pas d'espace juste apres), ne doit pas etre altere.
    assert split_priority_keywords("CI/CD\nFull-Stack\n") == ["CI/CD", "Full-Stack"]


def test_split_priority_keywords_header_variants_beyond_the_exact_hardcoded_set():
    """Le detecteur d'en-tete doit couvrir les variantes reelles courantes,
    pas seulement une poignee de chaines figees."""
    assert split_priority_keywords("MOTS CLES\nSQL\n") == ["SQL"]
    assert split_priority_keywords("Liste des mots-clés :\nSQL\n") == ["SQL"]
    assert split_priority_keywords("Mot clé recherché :\nSQL\n") == ["SQL"]


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


# ── Credit semantique partiel (2026-09-11) ───────────────────────────────────
#
# Regression reelle (offre "Data Analyst / Concepteur Decisionnel Senior",
# 2026-09-11) : un mot-cle prioritaire non trouve MOT POUR MOT ("architectures
# BI", "flux de donnees"...) ne recevait jamais aucun credit, contrairement a
# la couverture de competences generale (_skill_score) qui accorde deja un
# credit partiel via similarite d'embedding. Un candidat architecte
# Data/BI de 25 ans d'experience, faisant clairement ce travail mais le
# formulant differemment, voyait son plafond de score bloque a 65% (0.30 +
# 0.70 * 7/14) sans aucun moyen d'en sortir. _priority_keyword_score reutilise
# desormais _semantic_skill_credit, exactement comme _skill_score.

def test_semantic_credit_raises_priority_keyword_score_for_a_related_term(monkeypatch):
    from app.services import matcher

    monkeypatch.setattr(
        matcher, "_semantic_skill_credit",
        lambda unmatched, cv_skills: 0.5 if "Reporting" in unmatched else 0.0,
    )
    cv = "Développeur Python, Django."
    job = "Poste: Développeur Backend. Compétences requises: Python."
    without_credit = match_cv_to_job(cv, job, priority_keywords="Python\nReporting\nDjango")
    monkeypatch.setattr(matcher, "_semantic_skill_credit", lambda unmatched, cv_skills: 0.0)
    exact_only = match_cv_to_job(cv, job, priority_keywords="Python\nReporting\nDjango")
    assert without_credit.score_priority_keywords > exact_only.score_priority_keywords


def test_semantic_credit_never_exceeds_full_coverage(monkeypatch):
    from app.services import matcher

    monkeypatch.setattr(matcher, "_semantic_skill_credit", lambda unmatched, cv_skills: 999.0)
    cv = "Développeur Python."
    job = "Poste: Développeur Backend."
    result = match_cv_to_job(cv, job, priority_keywords="Python\nKubernetes")
    assert result.score_priority_keywords == 1.0


def test_displayed_matched_count_is_unaffected_by_semantic_credit(monkeypatch):
    """Le compte affiche au recruteur ("X/Y mots-cles trouves") reste base
    sur les correspondances EXACTES uniquement -- seul le plafond de score
    beneficie du credit semantique, jamais le nombre affiche."""
    from app.services import matcher

    monkeypatch.setattr(matcher, "_semantic_skill_credit", lambda unmatched, cv_skills: 0.9)
    cv = "Développeur Python."
    job = "Poste: Développeur Backend."
    result = match_cv_to_job(cv, job, priority_keywords="Python\nKubernetes")
    assert result.priority_keywords_matched == ["Python"]
    assert result.priority_keywords_total == 2
    assert result.score_priority_keywords < 1.0  # credit partiel, pas un faux match exact
