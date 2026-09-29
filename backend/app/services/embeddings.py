from __future__ import annotations

import threading
from functools import lru_cache
from math import sqrt
from typing import Iterable

from ..settings import get_settings
from .structured import build_document_profile

settings = get_settings()
_lock = threading.Lock()

# Shared registry keyed by (model_name, device): esco_taxonomy.py's EscoIndex
# loads its own sentence-transformer for skill-to-ESCO linking, and by default
# points at the same model as embedding_model_name (intfloat/multilingual-e5-base).
# Without sharing, both would load a separate ~1GB+ copy of the same model into
# the same process — real memory pressure on a mem-limited container. Callers
# that need a specific model (not necessarily settings.embedding_model_name)
# should go through get_sentence_transformer() rather than instantiating
# SentenceTransformer directly.
_model_registry: dict[tuple[str, str], object] = {}


def _load_sentence_transformer():
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer
    except Exception as exc:  # pragma: no cover - optional dependency
        return exc


def get_sentence_transformer(model_name: str, device: str | None = None):
    device = device or settings.embedding_device
    key = (model_name, device)
    if key not in _model_registry:
        with _lock:
            if key not in _model_registry:
                SentenceTransformer = _load_sentence_transformer()
                if not callable(SentenceTransformer):
                    raise RuntimeError(f"sentence-transformers unavailable: {SentenceTransformer}")
                _model_registry[key] = SentenceTransformer(model_name, device=device)
    return _model_registry[key]


def get_embedder():
    return get_sentence_transformer(settings.embedding_model_name, settings.embedding_device)


def _split_for_embedding(text: str, model) -> list[str]:
    """Split `text` into pieces that each fit within the model's
    max_seq_length, so a single long chunk is never silently truncated by
    the underlying tokenizer.

    Residual gap flagged 2026-09-29: structured.py already splits a
    document into per-section chunks (summary/skills/experience/etc.)
    before embedding, which keeps most chunks well under the limit -- but
    one section can still individually exceed it (e.g. a very verbose
    "Expérience" block for a long career), and that chunk's tail was
    silently dropped with no warning. This is the fallback safety net for
    that case, not a replacement for the section-based chunking.
    """
    max_len = getattr(model, "max_seq_length", None) or 512
    # Margin for special tokens ([CLS]/[SEP] etc.) the tokenizer adds on
    # top of the content tokens.
    budget = max(1, max_len - 2)
    try:
        token_ids = model.tokenizer.encode(text, add_special_tokens=False)
    except Exception:
        return [text]
    if len(token_ids) <= budget:
        return [text]
    pieces = [
        model.tokenizer.decode(token_ids[start : start + budget], skip_special_tokens=True)
        for start in range(0, len(token_ids), budget)
    ]
    return [p for p in pieces if p.strip()] or [text]


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    items = list(texts)
    if not items:
        return []
    try:
        model = get_embedder()
    except Exception:
        return []

    # Expand any item that's too long for the model into 1+ sub-pieces
    # (see _split_for_embedding), embed everything in one batch, then
    # average each item's own piece(s) back together so the return value
    # still has exactly len(items) vectors, one per input -- every caller
    # (embed_text, compute_domain_sim, main.py's _vector_match_cv/_job)
    # relies on that 1:1 correspondence.
    expanded: list[str] = []
    spans: list[tuple[int, int]] = []
    for text in items:
        pieces = _split_for_embedding(text, model)
        start = len(expanded)
        expanded.extend(pieces)
        spans.append((start, len(expanded)))

    raw = model.encode(
        expanded,
        batch_size=settings.embedding_batch_size,
        normalize_embeddings=True,
    )
    raw_vectors = raw.tolist() if hasattr(raw, "tolist") else [list(vector) for vector in raw]

    results: list[list[float]] = []
    for start, end in spans:
        piece_vectors = raw_vectors[start:end]
        results.append(piece_vectors[0] if len(piece_vectors) == 1 else _average_vectors(piece_vectors))
    return results


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


def compute_domain_sim(cv_profile: dict, job_profile: dict) -> float:
    """Cosine similarity between CV summary and job summary embeddings.

    Embeddings are L2-normalized by embed_texts, so dot product = cosine sim.
    Returns 0.0 when either summary is empty or the embedding model is unavailable.
    """
    cv_summary = (cv_profile.get("summary_text") or "").strip()
    job_summary = (job_profile.get("summary_text") or "").strip()
    if not cv_summary or not job_summary:
        return 0.0
    try:
        vectors = embed_texts([cv_summary, job_summary])
        if len(vectors) != 2:
            return 0.0
        return float(sum(a * b for a, b in zip(vectors[0], vectors[1])))
    except Exception:
        return 0.0


@lru_cache(maxsize=4096)
def _embed_one(label: str) -> tuple[float, ...] | None:
    """Embed a single skill label, cached. Returns None if unavailable.

    Uses settings.skill_embedding_model_name, NOT the general document
    embedder (settings.embedding_model_name) -- see the comment on
    skill_embedding_model_name in settings.py for why these two are
    deliberately different models.
    """
    try:
        model = get_sentence_transformer(settings.skill_embedding_model_name, settings.embedding_device)
        vectors = model.encode([label], normalize_embeddings=True)
    except Exception:
        return None
    if vectors is None or len(vectors) == 0:
        return None
    return tuple(float(x) for x in vectors[0])


def best_skill_similarities(
    missing: tuple[str, ...],
    cv_skills: tuple[str, ...],
) -> dict[str, float]:
    """For each skill in `missing`, the max cosine similarity to any skill in
    `cv_skills`.

    Both inputs are canonical skill labels. Returns {skill: best_sim in [0,1]}.
    Returns an empty dict when the embedding model is unavailable or either
    side is empty — callers must treat "no data" as "fall back to lexical",
    never as "similarity 0". Inputs are tuples so results can be memoised by
    the caller if desired.
    """
    if not missing or not cv_skills:
        return {}
    cv_vecs: list[tuple[str, tuple[float, ...]]] = []
    for s in cv_skills:
        v = _embed_one(s)
        if v is not None:
            cv_vecs.append((s, v))
    if not cv_vecs:
        return {}

    result: dict[str, float] = {}
    for m in missing:
        mv = _embed_one(m)
        if mv is None:
            continue
        best = 0.0
        for _, cvv in cv_vecs:
            # vectors are L2-normalized -> dot product == cosine similarity
            sim = sum(a * b for a, b in zip(mv, cvv))
            best = max(best, sim)
        result[m] = float(best)
    return result
