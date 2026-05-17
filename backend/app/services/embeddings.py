from __future__ import annotations

import threading
from typing import Iterable

from sentence_transformers import SentenceTransformer

from ..settings import get_settings

settings = get_settings()
_embedder: SentenceTransformer | None = None
_lock = threading.Lock()


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        with _lock:
            if _embedder is None:
                _embedder = SentenceTransformer(
                    settings.embedding_model_name,
                    device=settings.embedding_device,
                )
    return _embedder


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    items = list(texts)
    if not items:
        return []
    model = get_embedder()
    embeddings = model.encode(
        items,
        batch_size=settings.embedding_batch_size,
        normalize_embeddings=True,
    )
    if hasattr(embeddings, "tolist"):
        return embeddings.tolist()
    return [list(vector) for vector in embeddings]


def embed_text(text: str) -> list[float]:
    vectors = embed_texts([text])
    return vectors[0] if vectors else []
