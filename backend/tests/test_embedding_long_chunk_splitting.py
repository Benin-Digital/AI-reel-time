"""Test de non-regression pour le risque residuel signale (2026-09-29) :
structured.py decoupe deja un document en chunks par section (resume,
competences, experience, etc.) avant embedding, ce qui evite la plupart
des troncatures silencieuses du modele intfloat/multilingual-e5-base
(limite 512 tokens) -- mais UNE section individuelle (ex: "Experience"
tres verbeuse pour une longue carriere) pouvait encore, a elle seule,
depasser la limite et se faire tronquer silencieusement par le tokenizer
interne du modele, sans aucun avertissement.

Fix : embeddings.py::_split_for_embedding decoupe tout texte trop long en
sous-morceaux qui tiennent chacun dans max_seq_length (mesure avec le
VRAI tokenizer du modele, pas une heuristique de mots), et
embed_texts() les encode tous puis moyenne les vecteurs de chaque item
d'origine -- aucun caller n'a besoin de changer, le contrat "un vecteur
par texte en entree" est preserve.
"""
from __future__ import annotations

from app.services import embeddings


class _FakeTokenizer:
    """Un "token" = un mot, pour pouvoir controler precisement le nombre
    de tokens dans les tests sans dependre d'un vrai tokenizer HuggingFace."""

    def encode(self, text, add_special_tokens=False):
        return text.split()

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(ids)


class _FakeModel:
    def __init__(self, max_seq_length=5):
        self.max_seq_length = max_seq_length
        self.tokenizer = _FakeTokenizer()
        self.encoded_batches: list[list[str]] = []

    def encode(self, texts, batch_size=None, normalize_embeddings=True):
        texts = list(texts)
        self.encoded_batches.append(texts)
        # Un vecteur distinct par texte (base sur sa longueur) -- suffisant
        # pour verifier le nombre de vecteurs produits et la structure,
        # sans avoir besoin d'une vraie semantique.
        return [[float(len(t)), 0.0, 1.0] for t in texts]


def test_split_for_embedding_leaves_short_text_unchanged():
    model = _FakeModel(max_seq_length=10)
    text = "Python Django PostgreSQL"

    pieces = embeddings._split_for_embedding(text, model)

    assert pieces == [text]


def test_split_for_embedding_splits_long_text_without_dropping_any_word():
    model = _FakeModel(max_seq_length=5)  # budget = max(1, 5-2) = 3 mots/piece
    words = [f"mot{i}" for i in range(10)]
    text = " ".join(words)

    pieces = embeddings._split_for_embedding(text, model)

    assert len(pieces) > 1, "un texte de 10 mots avec un budget de 3 doit etre decoupe"
    reconstructed = " ".join(pieces).split()
    assert reconstructed == words, "aucun mot ne doit etre perdu lors du decoupage"


def test_embed_texts_returns_one_vector_per_input_even_when_split(monkeypatch):
    model = _FakeModel(max_seq_length=5)
    monkeypatch.setattr(embeddings, "get_embedder", lambda: model)

    short_text = "CV court"
    long_text = " ".join(f"mot{i}" for i in range(12))

    results = embeddings.embed_texts([short_text, long_text])

    assert len(results) == 2, "un vecteur par texte en entree, meme si l'un a ete decoupe en plusieurs morceaux"


def test_embed_texts_encodes_every_piece_of_a_long_chunk(monkeypatch):
    model = _FakeModel(max_seq_length=5)
    monkeypatch.setattr(embeddings, "get_embedder", lambda: model)

    words = [f"mot{i}" for i in range(12)]
    long_text = " ".join(words)

    embeddings.embed_texts([long_text])

    all_encoded_words = " ".join(model.encoded_batches[0]).split()
    assert all_encoded_words == words, (
        "chaque mot du chunk long doit atteindre model.encode() -- "
        "rien ne doit etre tronque silencieusement"
    )


def test_embed_texts_still_returns_one_vector_for_a_short_text(monkeypatch):
    model = _FakeModel(max_seq_length=512)
    monkeypatch.setattr(embeddings, "get_embedder", lambda: model)

    results = embeddings.embed_texts(["Développeur Python senior."])

    assert len(results) == 1
    assert len(model.encoded_batches[0]) == 1, "un texte court ne doit jamais etre decoupe"
