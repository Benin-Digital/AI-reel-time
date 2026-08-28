from __future__ import annotations

from collections.abc import Iterable

from ..settings import get_settings
from .parser import parse_document
from .structured import fold_text

settings = get_settings()


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    chunks = text.replace("\r", "\n")
    chunks = chunks.replace("•", "\n")
    parts = chunks.split("\n")
    sentences: list[str] = []
    for part in parts:
        for sentence in part.split("."):
            fragment = sentence.strip()
            if fragment:
                sentences.append(fragment)
    return sentences


def _pick_evidence(text: str, keywords: Iterable[str], label: str, limit: int = 4) -> list[str]:
    if not text:
        return []
    keyset = [folded for folded in (fold_text(keyword) for keyword in keywords) if folded]
    if not keyset:
        return []
    results: list[str] = []
    for sentence in _split_sentences(text):
        lower_sentence = fold_text(sentence)
        if any(keyword in lower_sentence for keyword in keyset):
            results.append(f"{label}: {sentence}")
        if len(results) >= limit:
            break
    return results


def _format_keywords(keywords: Iterable[str], limit: int = 8) -> str:
    items = [kw for kw in keywords if kw]
    return ", ".join(items[:limit]) if items else "aucun"


def _language_label(items: list[str]) -> str:
    return ", ".join(items) if items else "aucune langue identifiee"


def build_match_explanation(
    cv_text: str,
    job_text: str,
    score: float,
    keywords: list[str],
) -> dict[str, object]:
    # Use the exact same parsing pipeline as matcher.py (the engine that
    # actually computed and persisted `score`), so the narrative below is
    # never built from a different set of extracted skills/sections than
    # the number it's explaining.
    cv_profile = parse_document(cv_text or "", kind="cv")
    job_profile = parse_document(job_text or "", kind="job")

    cv_skill_terms = set(cv_profile.skill_terms)
    required_terms = set(job_profile.required_skill_terms or job_profile.skill_terms)

    keyword_hits = [kw for kw in keywords if kw]
    matched_required = [term for term in job_profile.required_skill_terms if term in cv_skill_terms]
    matched_nice = [term for term in job_profile.nice_skill_terms if term in cv_skill_terms]
    missing_required = sorted(required_terms - cv_skill_terms)

    summary = (
        f"Score {round(score, 2)}% construit sur des sections structurees: "
        f"competences, experience, langues, contrat et signaux lexicaux. "
        f"Mots-cles principaux: {_format_keywords(keyword_hits)}."
    )

    why_match: list[str] = []
    vigilance: list[str] = []

    if matched_required:
        why_match.append(f"Competences requises alignees: {_format_keywords(matched_required)}.")
    if matched_nice:
        why_match.append(f"Competences complementaires detectees: {_format_keywords(matched_nice)}.")
    if not matched_required and not matched_nice:
        vigilance.append("Peu de competences structurees concordantes detectees.")

    if job_profile.contract_type:
        if cv_profile.contract_type == job_profile.contract_type:
            why_match.append(f"Type de contrat compatible: {job_profile.contract_type}.")
        else:
            vigilance.append(f"Type de contrat attendu: {job_profile.contract_type}.")

    if job_profile.language_terms:
        language_overlap = sorted(set(cv_profile.language_terms).intersection(job_profile.language_terms))
        if language_overlap:
            why_match.append(f"Langues compatibles: {_language_label(language_overlap)}.")
        else:
            vigilance.append(f"Langues attendues: {_language_label(job_profile.language_terms)}.")

    if job_profile.experience_years:
        cv_years = cv_profile.experience_years
        job_years = job_profile.experience_years
        if cv_years >= job_years:
            why_match.append(f"Experience detectee: {cv_years} ans pour {job_years} requis.")
        else:
            vigilance.append(f"Experience detectee: {cv_years} ans pour {job_years} requis.")
    elif cv_profile.experience_years:
        why_match.append(f"Experience CV estimee a {cv_profile.experience_years} ans.")

    if missing_required:
        vigilance.append(f"Competences manquantes cote offre: {_format_keywords(missing_required)}.")

    cv_len = len((cv_text or "").strip())
    job_len = len((job_text or "").strip())
    if cv_len < settings.ocr_min_text_length:
        vigilance.append("Texte CV extrait partiel, verifier le document complet.")
    if job_len < settings.ocr_min_text_length:
        vigilance.append("Texte de l'offre extrait partiel, verifier le document complet.")

    evidence: list[str] = []
    evidence.extend(_pick_evidence(cv_profile.skills_text or cv_text or "", keyword_hits, "CV"))
    evidence.extend(_pick_evidence(job_profile.skills_text or job_text or "", keyword_hits, "Offre"))
    evidence.extend(_pick_evidence(cv_profile.experience_text or cv_text or "", matched_required or keyword_hits, "CV"))
    evidence.extend(_pick_evidence(job_profile.job_required_text or job_text or "", matched_required or keyword_hits, "Offre"))

    if not evidence:
        evidence.append("Aucune phrase probante n'a pu etre isolee.")

    if not why_match:
        why_match.append("Correspondance basee sur des signaux structurels faibles mais coherents.")

    return {
        "summary": summary,
        "why_match": why_match,
        "vigilance": vigilance,
        "evidence": evidence,
        "keyword_hits": keyword_hits,
    }
