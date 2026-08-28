"""Tests : score de competences hybride lexical + embeddings (F6).

Quand une competence requise n'est pas trouvee litteralement dans le CV,
_skill_score() ajoute un credit PARTIEL base sur la similarite d'embedding
avec les competences du CV ("Vue.js" requis vs "React" au CV -> un peu de
credit au lieu de 0), plafonne pour qu'un match semantique ne depasse
jamais un match exact.

Invariants verifies :
- sans modele d'embeddings (ou feature desactivee) -> comportement lexical
  strictement identique (fallback) ;
- le credit hybride ne peut que MONTER le score, jamais le baisser ;
- un match exact reste a 1.0 ; un mismatch total reste bas.

Le vrai modele n'est pas disponible en environnement de test, donc la
partie semantique est testee en injectant un best_skill_similarities
factice (deterministe).
"""
from __future__ import annotations

import pytest

from app.services import matcher


class _Doc:
    """Stand-in for ParsedDocument with only the fields _skill_score reads."""

    def __init__(self, skills, required=None, nice=None):
        self.skill_terms = list(skills)
        self.required_skill_terms = list(required) if required is not None else list(skills)
        self.nice_skill_terms = list(nice or [])


# ── Fallback : sans embeddings, comportement lexical exact ───────────────────

def test_exact_match_is_full_score():
    cv = _Doc(["Python", "Django"])
    job = _Doc(["Python", "Django"])
    score, ok = matcher._skill_score(cv, job)
    assert score == 1.0
    assert ok is True


def test_no_cv_skills_is_zero():
    cv = _Doc([])
    job = _Doc(["Python"])
    score, ok = matcher._skill_score(cv, job)
    assert score == 0.0
    assert ok is False


def test_semantic_credit_disabled_falls_back_to_lexical(monkeypatch):
    """Feature off -> pur lexical : 1 skill exact sur 2 requis = 0.5."""
    monkeypatch.setattr(
        matcher, "_semantic_skill_credit", lambda unmatched, cv_skills: 0.0
    )
    cv = _Doc(["Python"])
    job = _Doc(["Python", "Kubernetes"])
    score, _ = matcher._skill_score(cv, job)
    assert score == pytest.approx(0.5)


# ── Hybride : credit partiel pour competences proches ────────────────────────

def test_semantic_credit_raises_score_for_related_skills(monkeypatch):
    """React au CV, Vue.js requis : credit partiel > 0 mais < match exact."""
    monkeypatch.setattr(
        matcher, "_semantic_skill_credit",
        lambda unmatched, cv_skills: 0.2 if "Vue.js" in unmatched else 0.0,
    )
    cv = _Doc(["React"])
    job = _Doc(["Vue.js"])
    score, _ = matcher._skill_score(cv, job)
    assert 0.0 < score < 1.0


def test_semantic_credit_never_lowers_lexical_score(monkeypatch):
    """Le credit semantique s'ajoute : il ne peut jamais faire baisser un
    score deja acquis par match exact."""
    monkeypatch.setattr(
        matcher, "_semantic_skill_credit",
        lambda unmatched, cv_skills: 0.3,
    )
    cv = _Doc(["Python", "React"])
    job = _Doc(["Python", "Vue.js"])  # Python exact + Vue.js semantique
    score, _ = matcher._skill_score(cv, job)
    # Au moins le lexical seul (1 exact / 2 = 0.5)
    assert score >= 0.5


def test_total_mismatch_stays_low(monkeypatch):
    """Aucune similarite -> aucun credit -> score reste 0."""
    monkeypatch.setattr(
        matcher, "_semantic_skill_credit", lambda unmatched, cv_skills: 0.0
    )
    cv = _Doc(["Photoshop", "Illustrator"])
    job = _Doc(["Python", "Kubernetes"])
    score, _ = matcher._skill_score(cv, job)
    assert score == 0.0


def test_semantic_credit_is_capped(monkeypatch):
    """Meme avec un credit sature, le score total reste borne a 1.0."""
    monkeypatch.setattr(
        matcher, "_semantic_skill_credit",
        lambda unmatched, cv_skills: 999.0,  # credit absurde
    )
    cv = _Doc(["React"])
    job = _Doc(["Vue.js"])
    score, _ = matcher._skill_score(cv, job)
    assert score <= 1.0


# ── _semantic_skill_credit : robustesse ──────────────────────────────────────

def test_semantic_credit_empty_inputs_returns_zero():
    assert matcher._semantic_skill_credit(set(), {"Python"}) == 0.0
    assert matcher._semantic_skill_credit({"Python"}, set()) == 0.0
