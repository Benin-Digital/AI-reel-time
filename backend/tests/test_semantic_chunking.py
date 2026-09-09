"""Tests pour le decoupage en fenetres du score semantique (matcher.py).

Contexte : le cross-encoder (CamemBERT) partage un budget d'environ 512
tokens entre les DEUX sequences de la paire. _semantic_repr() ne tronquait
avant qu'a 2000 caracteres -- mais un controle manuel sur 35 vrais
documents (CV de consultants seniors) a montre que 67% d'entre eux
depassaient deja cette fenetre unique, meme apres selection des sections
les plus pertinentes (competences + resume) : le cross-encoder ne voyait
alors qu'un fragment tronque, perdant parfois l'essentiel du texte de
competences ou tout le resume.

_cross_encode_best() decoupe chaque cote en fenetres de _CHUNK_CHARS
caracteres et garde le MEILLEUR score parmi toutes les combinaisons
(query_chunk, document_chunk), au lieu de parier sur une seule fenetre.
"""
from __future__ import annotations

from app.services import matcher
from app.services.matcher import _CHUNK_CHARS, _MAX_CHUNKS, _chunk_text, _cross_encode_best


def test_chunk_text_returns_single_chunk_for_short_text():
    text = "Un texte court."
    assert _chunk_text(text) == [text]


def test_chunk_text_returns_empty_list_for_empty_input():
    assert _chunk_text("") == []
    assert _chunk_text("   ") == []


def test_chunk_text_breaks_at_word_boundary_not_mid_word():
    # Un mot qui chevaucherait exactement la limite de decoupe ne doit
    # jamais etre coupe en deux.
    words = [f"mot{i}" for i in range(400)]  # largement > _CHUNK_CHARS
    text = " ".join(words)
    chunks = _chunk_text(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert not chunk.startswith(" ") and not chunk.endswith(" ")
        for token in chunk.split():
            assert token in words, f"mot tronque ou invente : {token!r}"


def test_chunk_text_is_capped_at_max_chunks():
    huge_text = "mot " * (_CHUNK_CHARS * (_MAX_CHUNKS + 10) // 4)
    chunks = _chunk_text(huge_text)
    assert len(chunks) <= _MAX_CHUNKS


def test_cross_encode_best_takes_the_max_across_chunk_pairs(monkeypatch):
    """Le meilleur fragment doit porter le score, pas le premier ni une
    moyenne -- sinon un CV avec une seule section tres pertinente noyee
    dans beaucoup de contenu neutre serait sous-note."""
    scores = {
        ("requete", "fragment-faible"): 0.1,
        ("requete", "fragment-fort"): 0.95,
    }
    monkeypatch.setattr(matcher, "_cross_encode", lambda q, d: scores[(q, d)])
    monkeypatch.setattr(matcher, "_chunk_text", lambda text, chunk_size=_CHUNK_CHARS: (
        ["requete"] if text == "requete" else ["fragment-faible", "fragment-fort"]
    ))

    result = _cross_encode_best("requete", "document long avec plusieurs fragments")
    assert result == 0.95


def test_cross_encode_best_matches_plain_cross_encode_for_short_pairs(monkeypatch):
    """Quand les deux cotes tiennent dans une seule fenetre, le resultat
    doit etre identique a un appel _cross_encode direct (pas de fenetre
    fantome introduite par le decoupage)."""
    monkeypatch.setattr(matcher, "_cross_encode", lambda q, d: 0.42 if (q, d) == ("courte requete", "court document") else 0.0)

    assert _cross_encode_best("courte requete", "court document") == 0.42
