"""Extraction NER (Named Entity Recognition).

Logique de chargement des modeles spaCy (par langue) et d'extraction
d'entites (personne, organisations, locations, dates), avec fallback
optionnel sur CamemBERT via `ner_camembert`.

Extrait de `structured.py` pour separer la couche NER du profiling.
"""
from __future__ import annotations

from functools import lru_cache
import logging

from ..settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

try:
    import spacy

    _SPACY_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    spacy = None
    _SPACY_AVAILABLE = False

try:
    import langdetect

    _LANGDETECT_AVAILABLE = True
except Exception:
    langdetect = None
    _LANGDETECT_AVAILABLE = False


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


@lru_cache
def _load_ner_model():
    # Deprecated single-model loader retained for compatibility
    if not settings.ner_enabled or not _SPACY_AVAILABLE:
        return None
    model_name = settings.ner_model_name.strip()
    if not model_name:
        return None
    try:
        return spacy.load(model_name)
    except Exception as exc:  # pragma: no cover - depends on local model install
        logger.warning("NER model '%s' not available: %s", model_name, exc)
        return None


@lru_cache
def _load_ner_model_for(model_name: str):
    if not settings.ner_enabled or not _SPACY_AVAILABLE:
        return None
    if not model_name:
        return None
    try:
        return spacy.load(model_name)
    except Exception as exc:  # pragma: no cover - depends on local model install
        logger.warning("NER model '%s' not available: %s", model_name, exc)
        return None


def _is_valid_ner_entity(value: str) -> bool:
    """Filter NER org/location false positives.

    spaCy fr_core_news_sm often tags tech tools (Django, Express.js) and generic
    words (Freelance, Remote) as ORG or LOC entities. We reject:
    - values with no capital letter (not a proper noun)
    - values that are known skills in the taxonomy
    """
    if not value or not any(c.isupper() for c in value):
        return False
    try:
        from .taxonomy import find_skills as _tx
        if _tx(value):
            return False
    except Exception:
        pass
    return True


def _extract_ner_entities(text: str) -> dict[str, object]:
    if not text:
        return {
            "person_name": None,
            "organization_terms": [],
            "location_terms": [],
            "date_terms": [],
        }

    # POC v2: route to CamemBERT when configured. Falls back silently to spaCy
    # if the model can't be loaded.
    if (getattr(settings, "ner_backend", "spacy") or "spacy").lower() == "camembert":
        try:
            from .ner_camembert import extract_entities as _camembert_entities
            result = _camembert_entities(text)
            if result.get("person_name") or result.get("organization_terms") or result.get("location_terms"):
                return result
        except Exception as exc:
            logger.warning("CamemBERT NER failed, falling back to spaCy: %s", exc)

    # choose model: try per-document language detection and map to model
    model_name = None
    try:
        # parse mapping like "fr:fr_core_news_sm,en:en_core_web_sm"
        mapping = {}
        for chunk in (settings.ner_model_map or "").split(","):
            if ":" in chunk:
                lang, m = chunk.split(":", 1)
                mapping[lang.strip().lower()] = m.strip()
        # detect language if possible
        detected_lang = None
        if _LANGDETECT_AVAILABLE and text:
            try:
                detected_lang = langdetect.detect(text[:10000])
            except Exception:
                detected_lang = None

        if detected_lang and detected_lang in mapping:
            model_name = mapping[detected_lang]
        else:
            # fallback to single model name
            model_name = settings.ner_model_name
    except Exception:
        model_name = settings.ner_model_name

    nlp = _load_ner_model_for(model_name)
    if nlp is None:
        return {
            "person_name": None,
            "organization_terms": [],
            "location_terms": [],
            "date_terms": [],
        }

    trimmed = text[: settings.ner_max_chars]
    doc = nlp(trimmed)

    persons: list[str] = []
    orgs: list[str] = []
    locs: list[str] = []
    dates: list[str] = []

    for ent in doc.ents:
        label = ent.label_.upper()
        value = ent.text.strip()
        if not value:
            continue
        if label in {"PER", "PERSON"}:
            persons.append(value)
        elif label in {"ORG", "ORGANIZATION"}:
            orgs.append(value)
        elif label in {"LOC", "GPE", "LOCATION"}:
            locs.append(value)
        elif label in {"DATE", "TIME"}:
            dates.append(value)

    persons = _unique_preserve_order(persons)
    orgs = [v for v in _unique_preserve_order(orgs) if _is_valid_ner_entity(v)]
    locs = [v for v in _unique_preserve_order(locs) if _is_valid_ner_entity(v)]
    dates = _unique_preserve_order(dates)

    return {
        "person_name": persons[0] if persons else None,
        "organization_terms": orgs[: settings.ner_max_entities],
        "location_terms": locs[: settings.ner_max_entities],
        "date_terms": dates[: settings.ner_max_entities],
    }
