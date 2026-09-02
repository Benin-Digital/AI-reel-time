"""Test : competences dispersees hors section captees a l'import (F10).

build_document_profile agregait, pour un CV, skills_text + job_required +
job_nice + experience + certifications — mais pas le texte complet. Un CV
sans section "Competences" dediee, listant ses outils dans des lignes
"Environnement technique:" au fil des experiences, pouvait voir ces outils
classes (par Docling notamment) dans summary/education, hors des sources
ci-dessus, et donc perdus (Git/SQL/ServiceNow manquants).

cleaned_text a ete ajoute au filet de securite des skill_sources CV.
_extract_skill_terms deduplique, donc ceci ne peut qu'ajouter, jamais
retirer. Les tests de symetrie/self-match/validation existants garantissent
qu'on ne casse pas l'egalite CV/job.
"""
from __future__ import annotations

from app.services.structured import build_document_profile

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


def test_scattered_tools_are_captured_at_import():
    profile = build_document_profile(CV_TOOLS_IN_EXPERIENCE, kind="cv", enable_ner=False)
    for skill in ("Git", "SQL", "ServiceNow", "Jira", "Confluence"):
        assert skill in profile.skill_terms, (
            f"{skill} manquant dans {profile.skill_terms}"
        )


def test_dedicated_skills_section_not_lost():
    """Le filet de securite ne doit pas faire perdre les competences deja
    captees via une section Competences classique."""
    cv = """Jean Dupont
Compétences : Python, Django, PostgreSQL
Expériences
Développeur - ACME
Environnement : Docker, Kubernetes
"""
    profile = build_document_profile(cv, kind="cv", enable_ner=False)
    for skill in ("Python", "Django", "PostgreSQL", "Docker", "Kubernetes"):
        assert skill in profile.skill_terms, (
            f"{skill} manquant dans {profile.skill_terms}"
        )
