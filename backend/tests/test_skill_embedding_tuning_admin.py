"""Tests : reglage live (sans redeploiement) du seuil/plafond de credit
semantique (GET/PATCH /admin/skill-embedding-tuning).

Contexte : le seuil de similarite (0.6) et le plafond de credit (0.8)
utilises par _semantic_skill_credit (competences ET mots-cles prioritaires)
etaient des constantes de settings, modifiables seulement via un
redeploiement complet. Un admin veut pouvoir tester une valeur differente
en production sans passer par tout le cycle commit/push/CI/deploy. Le
reglage vit en memoire (comme matcher._learned_weights), reinitialise au
prochain redemarrage -- une fois une valeur validee, elle doit etre gravee
dans AI_REALTIME_SKILL_EMBEDDING_THRESHOLD/_MAX_CREDIT pour survivre a un
deploiement.
"""
from __future__ import annotations

import pytest

from app.schemas import SkillEmbeddingTuningUpdate
from app.services import matcher
import app.routers.feedback as feedback_router


class _User:
    role = "superadmin"


class _AdminRequest:
    class state:
        user = _User()


class _AnonRequest:
    class state:
        user = None


@pytest.fixture(autouse=True)
def _reset_override():
    matcher.set_skill_embedding_tuning(None, None)
    yield
    matcher.set_skill_embedding_tuning(None, None)


def test_default_reports_settings_values_not_overridden():
    result = feedback_router.get_skill_embedding_tuning_settings(_AdminRequest())
    assert result.is_overridden is False
    assert result.threshold == pytest.approx(0.6)
    assert result.max_credit == pytest.approx(0.8)


def test_patch_takes_effect_immediately_without_restart():
    feedback_router.update_skill_embedding_tuning_settings(
        _AdminRequest(), SkillEmbeddingTuningUpdate(threshold=0.45)
    )
    threshold, max_credit, overridden = matcher.get_skill_embedding_tuning()
    assert threshold == 0.45
    assert max_credit == pytest.approx(0.8), "max_credit inchange si non fourni"
    assert overridden is True

    result = feedback_router.get_skill_embedding_tuning_settings(_AdminRequest())
    assert result.threshold == 0.45
    assert result.is_overridden is True


def test_reset_reverts_to_settings_default():
    feedback_router.update_skill_embedding_tuning_settings(
        _AdminRequest(), SkillEmbeddingTuningUpdate(threshold=0.3, max_credit=0.5)
    )
    feedback_router.update_skill_embedding_tuning_settings(
        _AdminRequest(), SkillEmbeddingTuningUpdate(reset=True)
    )
    threshold, max_credit, overridden = matcher.get_skill_embedding_tuning()
    assert threshold == pytest.approx(0.6)
    assert max_credit == pytest.approx(0.8)
    assert overridden is False


def test_out_of_range_values_are_rejected():
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        feedback_router.update_skill_embedding_tuning_settings(
            _AdminRequest(), SkillEmbeddingTuningUpdate(threshold=1.5)
        )
    with pytest.raises(HTTPException):
        feedback_router.update_skill_embedding_tuning_settings(
            _AdminRequest(), SkillEmbeddingTuningUpdate(max_credit=0.0)
        )


def test_non_admin_cannot_change_the_tuning():
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        feedback_router.update_skill_embedding_tuning_settings(
            _AnonRequest(), SkillEmbeddingTuningUpdate(threshold=0.5)
        )


def test_semantic_skill_credit_uses_the_live_override(monkeypatch):
    """La modification live doit reellement changer le comportement de
    _semantic_skill_credit, pas seulement la valeur lue par l'endpoint."""
    from app.settings import get_settings
    import app.services.embeddings as embeddings_module

    monkeypatch.setattr(get_settings(), "skill_embedding_enabled", True)
    monkeypatch.setattr(embeddings_module, "best_skill_similarities", lambda *a, **k: {"Vue.js": 0.55})

    # Sous le seuil par defaut (0.6) : aucun credit.
    credit_default = matcher._semantic_skill_credit({"Vue.js"}, {"React"})
    assert credit_default == 0.0

    # Seuil abaisse a 0.5 : la meme similarite (0.55) doit desormais compter.
    matcher.set_skill_embedding_tuning(threshold=0.5, max_credit=None)
    credit_lowered = matcher._semantic_skill_credit({"Vue.js"}, {"React"})
    assert credit_lowered > 0.0
