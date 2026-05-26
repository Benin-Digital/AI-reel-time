from __future__ import annotations

import threading
from math import sqrt
from typing import Iterable

from ..settings import get_settings
from .structured import build_document_profile

settings = get_settings()
_embedder = None
_lock = threading.Lock()


def _load_sentence_transformer():
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer
    except Exception as exc:  # pragma: no cover - optional dependency
        return exc


def get_embedder():
    global _embedder
    if _embedder is None:
        with _lock:
            if _embedder is None:
                SentenceTransformer = _load_sentence_transformer()
                if not callable(SentenceTransformer):
                    raise RuntimeError(f"sentence-transformers unavailable: {SentenceTransformer}")
                _embedder = SentenceTransformer(
                    settings.embedding_model_name,
                    device=settings.embedding_device,
                )
    return _embedder


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    items = list(texts)
    if not items:
        return []
    try:
        model = get_embedder()
    except Exception:
        return []
    embeddings = model.encode(
        items,
        batch_size=settings.embedding_batch_size,
        normalize_embeddings=True,
    )
    if hasattr(embeddings, "tolist"):
        return embeddings.tolist()
    return [list(vector) for vector in embeddings]


def _average_vectors(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    length = len(vectors[0])
    if length == 0:
        return []
    totals = [0.0] * length
    for vector in vectors:
        if len(vector) != length:
            continue
        for index, value in enumerate(vector):
            totals[index] += value
    averaged = [value / max(len(vectors), 1) for value in totals]
    norm = sqrt(sum(value * value for value in averaged))
    if norm > 0:
        averaged = [value / norm for value in averaged]
    return averaged


def embed_text(text: str) -> list[float]:
    profile = build_document_profile(text)
    chunks = profile.embedding_chunks or ([profile.cleaned_text] if profile.cleaned_text else [])
    if not chunks:
        return []
    vectors = embed_texts(chunks)
    if len(vectors) == 1:
        return vectors[0]
    return _average_vectors(vectors)
