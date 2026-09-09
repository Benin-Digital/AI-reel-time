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
        # Maps a FAISS row -> index into self.skills. Needed because each
        # skill embeds multiple rows (preferredLabel + every altLabel), so
        # FAISS row index != skill index once altLabels are embedded too.
        self._index_to_skill: list[int] = []

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

        # Embed every altLabel too, not just preferredLabel: ESCO ships
        # synonyms we were downloading but never using for semantic search
        # (only for the exact-match shortcut in label_to_skill above). A
        # free-text snippet that phrases a skill the way an altLabel does,
        # but not like the preferredLabel, previously had no chance of
        # surfacing via the embedding search at all.
        texts: list[str] = []
        self._index_to_skill = []
        for skill_idx, skill in enumerate(self.skills):
            texts.append(skill.preferred_label)
            self._index_to_skill.append(skill_idx)
            for alt in skill.alt_labels:
                texts.append(alt)
                self._index_to_skill.append(skill_idx)

        embeddings = self._model.encode(
            texts, batch_size=64, show_progress_bar=False, normalize_embeddings=True
        )
        arr = np.asarray(embeddings, dtype="float32")
        dim = arr.shape[1]
        self._faiss = faiss.IndexFlatIP(dim)
        self._faiss.add(arr)
        logger.info(
            "ESCO FAISS index ready: %d skills, %d vectors (incl. altLabels), dim=%d",
            len(self.skills), len(texts), dim,
        )

    def find_skills(
        self, text: str, top_k: int = 5, min_score: float | None = None
    ) -> list[tuple[EscoSkill, float]]:
        """Return up to top_k ESCO skills matching `text`. Exact alias match short-circuits."""
        if not text:
            return []
        exact = self.label_to_skill.get(text.lower().strip())
        if exact:
            return [(exact, 1.0)]
        if self._faiss is None or self._model is None:
            return []
        if min_score is None:
            min_score = get_settings().esco_min_score
        import numpy as np
        vec = self._model.encode([text], normalize_embeddings=True)
        # Multiple rows can point to the same skill (preferredLabel + N
        # altLabels), so over-fetch raw candidates and dedupe by skill below
        # to still return up to top_k *distinct* skills.
        raw_k = min(top_k * 5, self._faiss.ntotal)
        scores, idx = self._faiss.search(np.asarray(vec, dtype="float32"), raw_k)
        results: list[tuple[EscoSkill, float]] = []
        seen: set[str] = set()
        for score, i in zip(scores[0], idx[0]):
            if i < 0 or float(score) < min_score:
                continue
            skill = self.skills[self._index_to_skill[i]]
            if skill.uri in seen:
                continue
            seen.add(skill.uri)
            results.append((skill, float(score)))
            if len(results) >= top_k:
                break
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


def warn_if_esco_missing() -> None:
    """Log a loud warning at app startup if ESCO enrichment is enabled but no
    skills_*.csv is present, instead of waiting for get_esco_index() to warn
    lazily on the first document processed.

    Why this matters operationally: ESCO's CSV download used to be
    auto-fetched at Docker build time, but that download is now gated behind
    a manual request form + CAPTCHA (see backend/Dockerfile's ESCO comment)
    and can no longer be automated. esco_taxonomy.py itself degrades
    gracefully with no crash when the files are missing — which is correct
    for scoring, but means a missing/forgotten manual step reads as a silent
    capability gap discovered days later during testing, easily mistaken for
    a scoring bug instead of a missing file. Surfacing it once, loudly, at
    startup (call from main.py's lifespan) closes that gap.
    """
    settings = get_settings()
    if not getattr(settings, "esco_enrich_skills", False):
        return
    raw = (getattr(settings, "esco_dir", "") or "").strip()
    if not raw:
        return
    esco_dir = Path(raw)
    if esco_dir.is_dir() and list(esco_dir.glob("skills_*.csv")):
        return
    logger.warning(
        "ESCO enrichment is enabled (esco_enrich_skills=true) but no "
        "skills_*.csv found in %s -- ESCO-to-skill mapping will silently "
        "return no matches for every document. This is NOT a scoring bug: "
        "ESCO's dataset download now requires a manual request (email + "
        "CAPTCHA) at https://esco.ec.europa.eu/en/use-esco/download -- "
        "request it yourself, then drop the resulting skills_fr.csv/"
        "skills_en.csv onto this path.",
        esco_dir,
    )
