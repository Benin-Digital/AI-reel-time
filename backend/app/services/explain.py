from __future__ import annotations

import re
from typing import Iterable

from ..settings import get_settings

settings = get_settings()


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    chunks = re.split(r"[\n\r\.\!\?]+", text)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _extract_years(text: str) -> int:
    matches = re.findall(
        r"(\d{1,2})\s*(?:\+|\-)?\s*(?:years|year|ans|annee|annees)",
        text.lower(),
    )
    values = [int(value) for value in matches if value.isdigit()]
    return max(values) if values else 0


def _pick_evidence(text: str, keywords: Iterable[str], label: str, limit: int = 3) -> list[str]:
    if not text:
        return []
    keyset = [kw.lower() for kw in keywords if kw]
    if not keyset:
        return []
    results: list[str] = []
    for sentence in _split_sentences(text):
        lower_sentence = sentence.lower()
        if any(kw in lower_sentence for kw in keyset):
            results.append(f"{label}: {sentence}")
        if len(results) >= limit:
            break
    return results


def _format_keywords(keywords: Iterable[str], limit: int = 8) -> str:
    items = [kw for kw in keywords if kw]
    return ", ".join(items[:limit]) if items else "aucun"


def build_match_explanation(
    cv_text: str,
    job_text: str,
    score: float,
    keywords: list[str],
) -> dict[str, object]:
    cv_len = len((cv_text or "").strip())
    job_len = len((job_text or "").strip())
    keyword_hits = [kw for kw in keywords if kw]

    summary = (
        f"Score {round(score, 2)}% calcule a partir des mots-cles communs "
        f"et d'une analyse lexicale et vectorielle. "
        f"Mots-cles principaux: {_format_keywords(keyword_hits)}."
    )

    why_match: list[str] = []
    vigilance: list[str] = []

    if keyword_hits:
        why_match.append(
            f"Mots-cles partages detectes: {_format_keywords(keyword_hits)}."
        )
    else:
        vigilance.append("Peu de mots-cles communs detectes dans les textes extraits.")

    required_years = _extract_years(job_text or "")
    cv_years = _extract_years(cv_text or "")
    if required_years:
        if cv_years >= required_years:
            why_match.append(
                f"Experience detectee: {cv_years} ans pour {required_years} requis."
            )
        else:
            vigilance.append(
                f"Experience detectee: {cv_years} ans pour {required_years} requis."
            )
    else:
        vigilance.append("Experience requise non identifiee dans l'offre.")

    if cv_len < settings.ocr_min_text_length:
        vigilance.append("Texte CV extrait partiel, verifier le document complet.")
    if job_len < settings.ocr_min_text_length:
        vigilance.append("Texte de l'offre extrait partiel, verifier le document complet.")

    evidence = []
    evidence.extend(_pick_evidence(cv_text or "", keyword_hits, "CV"))
    evidence.extend(_pick_evidence(job_text or "", keyword_hits, "Offre"))

    if not evidence:
        evidence.append("Aucune phrase probante n'a pu etre isolee.")

    if not why_match:
        why_match.append("Correspondance basee sur des signaux faibles et lexicaux.")

    return {
        "summary": summary,
        "why_match": why_match,
        "vigilance": vigilance,
        "evidence": evidence,
        "keyword_hits": keyword_hits,
    }
