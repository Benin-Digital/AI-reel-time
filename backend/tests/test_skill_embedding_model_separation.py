"""Regression : le credit semantique de competences (matcher.py's
_semantic_skill_credit, via embeddings.py's best_skill_similarities/
_embed_one) partageait le meme modele que l'embedder general de document
(settings.embedding_model_name).

Quand celui-ci est passe a intfloat/multilingual-e5-base (validation:
document/domaine, texte francais complet), ca a silencieusement casse le
credit de competences : mesure reelle (voir settings.py), ce modele ne
discrimine PAS les noms d'outils techniques courts -- "Python" vs
"Photoshop" scorent 0.85 de similarite cosinus (au-dessus du seuil de
0.6), donnant du credit semantique a un mismatch total de domaine. Attrape
par la CI (test_validation_dataset.py::test_total_mismatch_scores_low),
pas localement, faute de vrai modele disponible en environnement de test.

all-MiniLM-L6-v2 discrimine correctement cette meme paire (0.35, bien sous
le seuil) -- son entrainement STS/NLI est lui-meme base sur des paires de
phrases courtes, le regime exact de cette tache.

Ce test ne peut pas verifier la QUALITE de la discrimination (pas de vrai
modele en local), seulement que le CABLAGE utilise bien le modele dedie
(skill_embedding_model_name) et non l'embedder general
(embedding_model_name) -- pour empecher une regression future qui
refusionnerait silencieusement les deux.
"""
from __future__ import annotations

from app.services import embeddings


class _FakeModel:
    def encode(self, texts, normalize_embeddings=True):
        return [[0.1, 0.2, 0.3]]


def test_settings_use_two_distinct_models():
    """Garde-fou explicite : si ces deux settings sont un jour refusionnes
    (meme valeur), le probleme redevient invisible en local."""
    assert embeddings.settings.skill_embedding_model_name != embeddings.settings.embedding_model_name


def test_embed_one_uses_the_dedicated_skill_model_not_the_general_embedder(monkeypatch):
    embeddings._embed_one.cache_clear()
    calls: list[str] = []

    def fake_get_sentence_transformer(model_name, device=None):
        calls.append(model_name)
        return _FakeModel()

    monkeypatch.setattr(embeddings, "get_sentence_transformer", fake_get_sentence_transformer)

    embeddings._embed_one("Python")

    assert calls == [embeddings.settings.skill_embedding_model_name]
    embeddings._embed_one.cache_clear()


def test_embed_one_returns_none_gracefully_when_model_unavailable(monkeypatch):
    def raising_get_sentence_transformer(model_name, device=None):
        raise RuntimeError("sentence-transformers unavailable")

    monkeypatch.setattr(embeddings, "get_sentence_transformer", raising_get_sentence_transformer)
    embeddings._embed_one.cache_clear()

    assert embeddings._embed_one("Python") is None
    embeddings._embed_one.cache_clear()
