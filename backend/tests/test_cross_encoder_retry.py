"""Test : un echec de chargement du cross-encoder ne doit pas se mettre en
cache pour toujours.

Contexte reel (production, 2026-09-10) : la chaine d'import
sentence_transformers -> transformers -> torch -> sympy est assez lourde
pour echouer une fois au tout premier appel (contention CPU/memoire au
demarrage), alors que le meme import reussit sans probleme quelques
secondes plus tard sur le meme conteneur. L'ancienne version de
_get_cross_encoder() mettait ce premier echec en cache de facon permanente
("unavailable") pour toute la duree de vie du process : le composant
semantique (40% du poids total du score) restait bloque a 0.5 pour TOUTES
les correspondances jusqu'a un redemarrage manuel de l'API -- personne ne
s'en apercevait tant qu'un humain ne comparait pas le score a son propre
jugement.

Desormais un echec est reessaye apres un delai (_CROSS_ENCODER_RETRY_COOLDOWN_S)
au lieu d'etre fige pour toujours -- seul settings.crossencoder_enabled=False
(un choix delibere, pas un echec) reste permanent.
"""
from __future__ import annotations

import sys
import types

from app.services import matcher
from app.settings import get_settings


def _install_fake_sentence_transformers(monkeypatch, cross_encoder_cls):
    """sentence_transformers isn't installed in this lightweight dev/CI venv
    (it's a heavy ML dependency only present in the Docker image) --
    _get_cross_encoder() imports it lazily inside a try/except, so injecting
    a fake module into sys.modules lets that import succeed without the
    real package, exactly like monkeypatching an attribute on it would if
    it existed."""
    fake_module = types.ModuleType("sentence_transformers")
    fake_module.CrossEncoder = cross_encoder_cls
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)


def test_failed_load_is_retried_after_cooldown_not_cached_forever(monkeypatch):
    monkeypatch.setattr(matcher, "_cross_encoder", None)
    monkeypatch.setattr(matcher, "_cross_encoder_disabled", False)
    monkeypatch.setattr(matcher, "_cross_encoder_last_failure", None)
    monkeypatch.setattr(get_settings(), "crossencoder_enabled", True)

    calls = {"n": 0}

    class FakeCrossEncoder:
        def __init__(self, model_name):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("cannot import name 'CrossEncoder'")

    _install_fake_sentence_transformers(monkeypatch, FakeCrossEncoder)

    fake_now = {"t": 1_000.0}
    monkeypatch.setattr(matcher.time, "monotonic", lambda: fake_now["t"])

    assert matcher._get_cross_encoder() is None, "premier chargement echoue -- doit retomber a None"
    assert calls["n"] == 1

    # Toujours dans la fenetre de cooldown -- ne doit PAS retenter tout de suite.
    fake_now["t"] += 10
    assert matcher._get_cross_encoder() is None
    assert calls["n"] == 1, "aucune nouvelle tentative avant la fin du cooldown"

    # Cooldown ecoule -- doit retenter, et reussir cette fois.
    fake_now["t"] += matcher._CROSS_ENCODER_RETRY_COOLDOWN_S
    result = matcher._get_cross_encoder()
    assert isinstance(result, FakeCrossEncoder)
    assert calls["n"] == 2, "doit avoir retente le chargement apres le cooldown"

    # Une fois charge avec succes, les appels suivants reutilisent l'instance
    # sans repasser par sentence_transformers.CrossEncoder.
    assert matcher._get_cross_encoder() is result
    assert calls["n"] == 2


def test_disabled_by_settings_is_permanent_not_a_retryable_failure(monkeypatch):
    monkeypatch.setattr(matcher, "_cross_encoder", None)
    monkeypatch.setattr(matcher, "_cross_encoder_disabled", False)
    monkeypatch.setattr(matcher, "_cross_encoder_last_failure", None)
    monkeypatch.setattr(get_settings(), "crossencoder_enabled", False)

    calls = {"n": 0}

    class FailIfCalled:
        def __init__(self, model_name):
            calls["n"] += 1
            raise AssertionError("CrossEncoder should never be instantiated when disabled")

    _install_fake_sentence_transformers(monkeypatch, FailIfCalled)

    fake_now = {"t": 1_000.0}
    monkeypatch.setattr(matcher.time, "monotonic", lambda: fake_now["t"])

    assert matcher._get_cross_encoder() is None
    fake_now["t"] += matcher._CROSS_ENCODER_RETRY_COOLDOWN_S * 10
    assert matcher._get_cross_encoder() is None
    assert calls["n"] == 0, "un flag disabled=False deliberer ne doit jamais tenter de charger le modele"
