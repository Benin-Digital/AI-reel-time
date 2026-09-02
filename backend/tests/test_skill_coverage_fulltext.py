"""Tests de non-regression : couverture des competences (F10, F11).

F10 : quand un CV n'a pas de section "Competences" dediee et disperse ses
outils dans des lignes "Environnement technique:" au fil des experiences,
la classification de section pouvait ranger ce contenu hors de skill_src,
et des competences (Git, SQL, ServiceNow...) etaient silencieusement
perdues. find_skills tourne desormais aussi sur le texte nettoye complet
en filet de securite (dedup -> ne peut qu'ajouter, jamais retirer).

F11 : l'alias "vue" (mot francais tres courant : "point de vue", "en vue
de") declenchait un faux positif "Vue.js". Retire ; les formes
specifiques (vue.js, vuejs, vue js) restent detectees.
"""
from __future__ import annotations

from app.services.parser import parse_document
from app.services.taxonomy import find_skills

# ── F11 : faux positif "vue" ─────────────────────────────────────────────────

def test_french_word_vue_is_not_vuejs():
    assert find_skills("point de vue") == []
    assert find_skills("en vue des sprints") == []
    assert find_skills("revue de code") == []


def test_real_vuejs_still_detected():
    assert "Vue.js" in find_skills("developpeur vue.js")
    assert "Vue.js" in find_skills("vuejs et react")
    assert "Vue.js" in find_skills("stack : vue js, pinia")


# ── F10 : competences dispersees hors section dediee ─────────────────────────

CV_TOOLS_IN_EXPERIENCE = """Samuel Exemple
Années d'expérience : 11 ans
Expériences
Manager de Transition IT - Norauto
Management d'une équipe, Agile, Scrum
Environnement technique : Confluence, Jira, Google Workspace
Ingénieur Support - Doxense
Support technique niveau 2 et 3
Environnement technique : Windows serveur, SQL, Jira, GIT, Zendesk, Office 365
Technicien - Scalair
Traitements des incidents ServiceNow
"""


def test_tools_scattered_in_experience_are_captured():
    """Un CV sans section Competences dediee, avec les outils dans des
    lignes 'Environnement technique:', doit quand meme voir ses outils
    extraits (Git, SQL, ServiceNow...)."""
    parsed = parse_document(CV_TOOLS_IN_EXPERIENCE, kind="cv")
    for skill in ("Git", "SQL", "ServiceNow", "Jira", "Confluence"):
        assert skill in parsed.skill_terms, (
            f"{skill} manquant dans {parsed.skill_terms}"
        )


def test_full_text_scan_does_not_lose_section_skills():
    """Le filet de securite (scan du texte complet) ne doit jamais faire
    PERDRE une competence qui etait deja captee via les sections."""
    cv = """Jean Dupont
Compétences : Python, Django, PostgreSQL
Expériences
Développeur - ACME
Environnement : Docker, Kubernetes
"""
    parsed = parse_document(cv, kind="cv")
    for skill in ("Python", "Django", "PostgreSQL", "Docker", "Kubernetes"):
        assert skill in parsed.skill_terms, (
            f"{skill} manquant dans {parsed.skill_terms}"
        )
