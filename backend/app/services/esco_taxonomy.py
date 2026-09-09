"""
POC layer 3: ESCO skills taxonomy with semantic lookup.

ESCO (European Skills/Competences/Qualifications/Occupations) is an EU-maintained
multilingual (FR/EN/DE/ES/...) taxonomy of ~13 500 skills and ~3 000 occupations.
Download: https://esco.ec.europa.eu/en/use-esco/download (CSV bundle).

This module loads ESCO `skills_*.csv` files into a FAISS index using a
multilingual embedding model. Lookup returns the best-matching ESCO concept(s)
for a free-text snippet (a CV phrase, a job offer requirement, etc.).

Expected CSVs in AI_REALTIME_ESCO_DIR:
  - skills_fr.csv, skills_en.csv (one or both)
  - columns: conceptUri, preferredLabel, altLabels, description

The index is built lazily on first call and cached for the process lifetime.
If ESCO_DIR is empty or invalid, lookups return [] (no crash, safe fallback).

Install: pip install -r backend/requirements-poc.txt
"""
import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class EscoSkill:
    uri: str
    preferred_label: str
    alt_labels: list[str]
    description: str


_index_singleton: Optional["EscoIndex"] = None


class EscoIndex:
    """FAISS-backed semantic lookup over ESCO skills."""

    def __init__(self, esco_dir: Path, model_name: str):
        self.esco_dir = esco_dir
        self.model_name = model_name
        self.skills: list[EscoSkill] = []
        self.label_to_skill: dict[str, EscoSkill] = {}
        self._faiss = None
        self._model = None

    def load(self) -> None:
        self._load_csv()
        if not self.skills:
            logger.warning("No ESCO skills loaded from %s", self.esco_dir)
            return
        self._build_index()

    def _load_csv(self) -> None:
        for csv_path in sorted(self.esco_dir.glob("skills_*.csv")):
            try:
                with csv_path.open(encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        label = (row.get("preferredLabel") or "").strip()
                        if not label:
                            continue
                        alts_raw = row.get("altLabels") or ""
                        alts = [a.strip() for a in alts_raw.split("\n") if a.strip()]
                        skill = EscoSkill(
                            uri=row.get("conceptUri") or "",
                            preferred_label=label,
                            alt_labels=alts,
                            description=row.get("description") or "",
                        )
                        self.skills.append(skill)
                        self.label_to_skill.setdefault(label.lower(), skill)
                        for a in alts:
                            self.label_to_skill.setdefault(a.lower(), skill)
                logger.info("Loaded ESCO file %s, total skills now %d", csv_path.name, len(self.skills))
            except Exception as exc:
                logger.exception("Failed to read ESCO file %s: %s", csv_path, exc)

    def _build_index(self) -> None:
        try:
            import faiss
            import numpy as np
            from .embeddings import get_sentence_transformer
        except ImportError as exc:
            logger.error("ESCO index needs sentence-transformers + faiss-cpu: %s", exc)
            return

        # Shared with embeddings.py's get_embedder(): same default model
        # (intfloat/multilingual-e5-base), so this avoids loading a second
        # ~1GB+ copy into the process. See embeddings.py's _model_registry.
        self._model = get_sentence_transformer(self.model_name)
        labels = [s.preferred_label for s in self.skills]
        embeddings = self._model.encode(
            labels, batch_size=64, show_progress_bar=False, normalize_embeddings=True
        )
        arr = np.asarray(embeddings, dtype="float32")
        dim = arr.shape[1]
        self._faiss = faiss.IndexFlatIP(dim)
        self._faiss.add(arr)
        logger.info("ESCO FAISS index ready: %d vectors, dim=%d", len(self.skills), dim)

    def find_skills(
        self, text: str, top_k: int = 5, min_score: float = 0.55
    ) -> list[tuple[EscoSkill, float]]:
        """Return up to top_k ESCO skills matching `text`. Exact alias match short-circuits."""
        if not text:
            return []
        exact = self.label_to_skill.get(text.lower().strip())
        if exact:
            return [(exact, 1.0)]
        if self._faiss is None or self._model is None:
            return []
        import numpy as np
        vec = self._model.encode([text], normalize_embeddings=True)
        scores, idx = self._faiss.search(np.asarray(vec, dtype="float32"), top_k)
        results: list[tuple[EscoSkill, float]] = []
        for score, i in zip(scores[0], idx[0]):
            if i < 0 or float(score) < min_score:
                continue
            results.append((self.skills[i], float(score)))
        return results


def get_esco_index() -> Optional[EscoIndex]:
    """Lazy-load and cache the ESCO index. Returns None if ESCO_DIR is not configured."""
    global _index_singleton
    if _index_singleton is not None:
        return _index_singleton
    settings = get_settings()
    raw = getattr(settings, "esco_dir", "") or ""
    if not raw:
        logger.info("AI_REALTIME_ESCO_DIR not set, ESCO lookup disabled")
        return None
    esco_dir = Path(raw)
    if not esco_dir.is_dir():
        logger.warning("ESCO dir not found: %s", esco_dir)
        return None
    model_name = getattr(settings, "esco_model_name", "intfloat/multilingual-e5-base")
    idx = EscoIndex(esco_dir, model_name)
    idx.load()
    _index_singleton = idx
    return idx


def find_skills_esco(text: str, top_k: int = 5) -> list[tuple[EscoSkill, float]]:
    """Convenience wrapper: lookup ESCO skills for free-text input."""
    idx = get_esco_index()
    if idx is None:
        return []
    return idx.find_skills(text, top_k=top_k)
