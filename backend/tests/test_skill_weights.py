"""Competences generiques ponderees, langues exclues, experience de l'offre.

Constate le 2026-10-12 sur la plateforme soeur (Keoni), sur une offre DevSecOps :
le candidat classe premier "alignait" 16 des 21 competences requises sans avoir
DevSecOps, Python ni OpenShift, parce que des termes generiques (Cycle, Compliance,
Product Owner, SGBD, Scrum, Agile...) valaient autant que "DevSecOps".
"""
from __future__ import annotations

from app.services import matcher
from app.services.parser import parse_document
from app.services.taxonomy import LANGUAGE_CANONICALS, WEAK_SKILL_CANONICALS, find_skills, partition_skills


# ── Poids des competences requises ───────────────────────────────────────────

def test_skill_weights_emphasize_title_skills_and_downweight_weak_ones():
    weights = matcher._build_skill_weights(
        {"DevSecOps", "Python", "Cycle", "Agile"}, {"DevSecOps"}, frozenset({"Cycle", "Agile"})
    )
    assert weights == {"DevSecOps": 3.0, "Python": 1.0, "Cycle": 0.25, "Agile": 0.25}


def test_a_weak_skill_in_the_title_keeps_full_emphasis():
    weights = matcher._build_skill_weights({"Product Owner", "Scrum"}, {"Product Owner"}, frozenset({"Product Owner", "Scrum"}))
    assert weights["Product Owner"] == 3.0
    assert weights["Scrum"] == 0.25


class _Doc:
    def __init__(self, skills, title_line=""):
        self.skill_terms = list(skills)
        self.required_skill_terms = list(skills)
        self.nice_skill_terms = []
        self.title_line = title_line


def test_generic_skills_no_longer_outweigh_the_offer_s_core_skill(monkeypatch):
    monkeypatch.setattr(matcher, "_semantic_skill_credit", lambda unmatched, cv_skills: 0.0)
    required = ["DevSecOps", "CI/CD", "Python", "Java", "SQL", "Linux", "OpenShift",
                "Cycle", "Compliance", "Parties prenantes", "Product Owner", "Scrum", "Agile", "SGBD"]
    job = _Doc(required, title_line="DevSecOps")
    generalist = _Doc(["CI/CD", "Java", "SQL", "Linux", "Cycle", "Compliance",
                       "Parties prenantes", "Product Owner", "Scrum", "Agile", "SGBD"])
    specialist = _Doc(["DevSecOps", "CI/CD", "Python", "Java", "Linux", "OpenShift", "Agile"])

    generalist_score, _ = matcher._skill_score(generalist, job)
    specialist_score, _ = matcher._skill_score(specialist, job)

    assert specialist_score > generalist_score


def test_without_title_or_weak_skills_the_coverage_is_unchanged(monkeypatch):
    monkeypatch.setattr(matcher, "_semantic_skill_credit", lambda unmatched, cv_skills: 0.0)
    score, ok = matcher._skill_score(_Doc(["Python"]), _Doc(["Python", "SQL"]))
    assert (score, ok) == (0.5, True)


# ── Langues ──────────────────────────────────────────────────────────────────

def test_language_names_are_not_hard_or_soft_skills():
    hard, soft = partition_skills(["Python", "Français", "Espagnol"])
    assert hard == ["Python"]
    assert soft == []
    assert "Français" in LANGUAGE_CANONICALS and "Français" in find_skills("Langues : Français")


def test_weak_skills_are_still_detected_so_they_can_be_down_weighted():
    found = set(find_skills("cycle de vie du projet, parties prenantes, compliance, SGBD, Scrum, Product Owner, Agile"))
    assert {"Cycle", "Parties prenantes", "Compliance", "SGBD", "Scrum", "Product Owner", "Agile"} <= found
    assert found & WEAK_SKILL_CANONICALS


# ── Experience de l'offre lue dans son texte (deja le cas ici : on le verrouille) ──

def test_job_experience_requirement_is_read_from_the_offer_text():
    job = parse_document(
        "DevSecOps\nExpérience nécessaire : minimum 7 années d’expérience\nMéthodologie : Agile", kind="job"
    )
    assert job.experience_years == 7
