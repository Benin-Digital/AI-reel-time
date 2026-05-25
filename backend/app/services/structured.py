from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re
import unicodedata

from ..settings import get_settings

settings = get_settings()

_SECTION_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    (
        "summary",
        (
            "profil",
            "profile",
            "about",
            "about me",
            "who am i",
            "resume",
            "résumé",
            "summary",
            "presentation",
            "présentation",
            "objectif",
        ),
    ),
    (
        "skills",
        (
            "competences",
            "compétences",
            "skills",
            "stack",
            "technologies",
            "outils",
            "expertise",
            "hard skills",
            "soft skills",
            "capabilities",
            "aptitudes",
            "technical skills",
        ),
    ),
    (
        "experience",
        (
            "experience",
            "expérience",
            "experiences",
            "expériences",
            "work experience",
            "professional experience",
            "parcours",
            "missions",
            "employment history",
        ),
    ),
    (
        "education",
        (
            "formation",
            "education",
            "études",
            "etudes",
            "diplome",
            "diplôme",
        ),
    ),
    (
        "certifications",
        (
            "certification",
            "certifications",
            "certificat",
        ),
    ),
    (
        "languages",
        (
            "langues",
            "languages",
            "language",
        ),
    ),
    (
        "job_required",
        (
            "competences requises",
            "compétences requises",
            "contrainte forte",
            "contraintes fortes",
            "contrainte forte du projet",
            "responsabilites",
            "responsabilités",
            "taches",
            "tâches",
            "activites",
            "activités",
            "qualifications",
            "profile wanted",
            "profil attendu",
            "profil ideal",
            "profil idéal",
            "requirements",
            "must have",
            "prérequis",
            "pre requis",
            "profil recherché",
            "profil recherche",
            "exigences",
        ),
    ),
    (
        "job_nice",
        (
            "nice to have",
            "atouts",
            "atout",
            "bonus",
            "souhaité",
            "souhaite",
            "apprécié",
            "apprecie",
            "appréciée",
        ),
    ),
    (
        "contract",
        (
            "contrat",
            "type de contrat",
        ),
    ),
    (
        "location",
        (
            "localisation",
            "location",
            "teletravail",
            "télétravail",
            "remote",
            "hybride",
        ),
    ),
]

_LANGUAGE_ALIASES: dict[str, str] = {
    "francais": "français",
    "french": "français",
    "anglais": "anglais",
    "english": "anglais",
    "espagnol": "espagnol",
    "spanish": "espagnol",
    "portugais": "portugais",
    "portuguese": "portugais",
    "allemand": "allemand",
    "german": "allemand",
    "arabe": "arabe",
    "arabic": "arabe",
}

_NOISE_TERMS = {
    "year",
    "years",
    "annee",
    "annees",
    "experience",
    "experiences",
    "exp",
    "month",
    "months",
    "ans",
}

_CONTRACT_ALIASES: list[tuple[str, str]] = [
    ("cdi", "CDI"),
    ("cdd", "CDD"),
    ("freelance", "Freelance"),
    ("independant", "Freelance"),
    ("indépendant", "Freelance"),
    ("consultant", "Freelance"),
    ("stage", "Stage"),
    ("alternance", "Alternance"),
    ("temps plein", "Temps plein"),
    ("temps partiel", "Temps partiel"),
    ("full time", "Temps plein"),
    ("part time", "Temps partiel"),
    ("hybride", "Hybride"),
    ("teletravail", "Télétravail"),
    ("télétravail", "Télétravail"),
    ("remote", "Télétravail"),
    ("full remote", "Télétravail"),
]

_BUILTIN_SKILL_SYNONYMS: dict[str, str] = {
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "node js": "nodejs",
    "nodejs": "nodejs",
    "node": "nodejs",
    "node js express": "nodejs",
    "node js api": "nodejs",
    "node js backend": "nodejs",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "py": "python",
    "python": "python",
    "c#": "csharp",
    "c sharp": "csharp",
    "c++": "cplusplus",
    "c plus plus": "cplusplus",
    "react js": "react",
    "reactjs": "react",
    "react": "react",
    "vue js": "vue",
    "vuejs": "vue",
    "vue": "vue",
    "fast api": "fastapi",
    "fastapi": "fastapi",
    "docker": "docker",
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "aws": "aws",
    "azure": "azure",
}


@dataclass(slots=True)
class StructuredDocument:
    kind: str
    raw_text: str
    cleaned_text: str
    sections: dict[str, str] = field(default_factory=dict)
    summary_text: str = ""
    skills_text: str = ""
    experience_text: str = ""
    education_text: str = ""
    certifications_text: str = ""
    languages_text: str = ""
    job_required_text: str = ""
    job_nice_text: str = ""
    contract_text: str = ""
    location_text: str = ""
    other_text: str = ""
    skill_terms: list[str] = field(default_factory=list)
    required_skill_terms: list[str] = field(default_factory=list)
    nice_skill_terms: list[str] = field(default_factory=list)
    language_terms: list[str] = field(default_factory=list)
    contract_type: str | None = None
    experience_years: int = 0
    embedding_chunks: list[str] = field(default_factory=list)

    @property
    def canonical_text(self) -> str:
        parts = [
            self.summary_text,
            self.skills_text,
            self.job_required_text,
            self.job_nice_text,
            self.experience_text,
            self.education_text,
            self.certifications_text,
            self.languages_text,
            self.contract_text,
            self.location_text,
            self.other_text,
        ]
        return "\n".join(part for part in parts if part).strip()


def fold_text(value: str) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_value.lower()


def _normalize_line(value: str) -> str:
    line = value.replace("\u00ad", "")
    line = re.sub(r"\s+", " ", line.strip())
    line = re.sub(r"^[\-*•·•\u2022\u25e6]+\s*", "", line)
    return line.strip()


def clean_document_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    counts: Counter[str] = Counter()
    cleaned_lines: list[str] = []
    previous_folded = ""
    for raw_line in text.split("\n"):
        line = _normalize_line(raw_line)
        if not line:
            previous_folded = ""
            continue

        folded = fold_text(line)
        if len(folded) <= 1:
            continue
        if folded == previous_folded:
            continue
        counts[folded] += 1
        if counts[folded] > 2:
            continue

        cleaned_lines.append(line)
        previous_folded = folded

    return "\n".join(cleaned_lines).strip()


def _parse_synonyms(raw: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in (chunk.strip() for chunk in raw.split(",") if chunk.strip()):
        if "=" not in item:
            continue
        src, dest = item.split("=", 1)
        src_folded = fold_text(src).replace(".", " ")
        dest_folded = fold_text(dest).replace(".", " ")
        if src_folded and dest_folded:
            pairs[src_folded] = dest_folded
    return pairs


def _skill_synonyms() -> dict[str, str]:
    mapping = dict(_BUILTIN_SKILL_SYNONYMS)
    mapping.update(_parse_synonyms(settings.scoring_synonyms))
    return mapping


def _apply_synonyms(text: str) -> str:
    result = fold_text(text).replace(".", " ")
    for source, target in sorted(_skill_synonyms().items(), key=lambda item: len(item[0]), reverse=True):
        if not source or not target or source == target:
            continue
        result = re.sub(rf"\b{re.escape(source)}\b", target, result)
    return re.sub(r"\s+", " ", result).strip()


def canonical_tokens(text: str) -> list[str]:
    if not text:
        return []
    normalized = _apply_synonyms(text)
    return [token for token in re.findall(r"[a-z0-9]+", normalized) if len(token) >= 2]


def canonical_token_set(text: str) -> set[str]:
    return set(canonical_tokens(text))


def _extract_skill_terms(text: str) -> list[str]:
    if not text:
        return []

    chunks = re.split(r"[\n,;/|•]+|\band\b|\bet\b|\bou\b", text, flags=re.IGNORECASE)
    terms: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        normalized = _apply_synonyms(chunk)
        normalized = re.sub(r"[^a-z0-9+.# ]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized or len(normalized) < 2:
            continue
        token_set = set(re.findall(r"[a-z0-9]+", normalized))
        if token_set and token_set.issubset(_NOISE_TERMS):
            continue
        if any(token.isdigit() for token in token_set):
            continue
        if normalized not in seen:
            seen.add(normalized)
            terms.append(normalized)
    return terms


def _detect_contract_type(text: str) -> str | None:
    folded = fold_text(text)
    for needle, label in _CONTRACT_ALIASES:
        if re.search(rf"\b{re.escape(needle)}\b", folded):
            return label
    return None


def _detect_languages(text: str) -> list[str]:
    folded = fold_text(text)
    languages: list[str] = []
    seen: set[str] = set()
    for needle, label in _LANGUAGE_ALIASES.items():
        if re.search(rf"\b{re.escape(needle)}\b", folded) and label not in seen:
            seen.add(label)
            languages.append(label)
    return languages


def _extract_years(text: str) -> int:
    if not text:
        return 0
    folded = fold_text(text)
    matches = re.findall(r"(\d{1,2})\s*(?:\+|\-|plus)?\s*(?:years|year|ans|annees?|ann[eé]e?s?)", folded)
    values = [int(value) for value in matches if value.isdigit()]
    return max(values) if values else 0


def _split_heading_payload(line: str) -> tuple[str | None, str]:
    folded = fold_text(line)
    if ":" in line:
        head, tail = line.split(":", 1)
        head_folded = fold_text(head)
        heading = _match_heading(head_folded)
        if heading:
            return heading, tail.strip()
    heading = _match_heading(folded)
    if heading:
        return heading, ""
    return None, line


def _is_heading(line: str, next_line: str | None = None) -> bool:
    """Heuristique simple pour détecter si une ligne est un heading.

    Utilise longueur, ponctuation, ratio de majuscules, numérotation et
    observation de la ligne suivante (liste/bullet) pour décider.
    """
    if not line or not line.strip():
        return False

    folded = fold_text(line)

    # numbered headings (1. , I) ou "1)"
    if re.match(r"^\s*(?:\d+|[ivx]+)[\.)]\s+", line.lower()):
        return True

    # présence de ':' fortement indicative
    if ":" in line and len(line) < 200:
        return True

    words = folded.split()
    word_count = len(words)
    if word_count == 0:
        return False

    # trop long pour être un heading
    if len(folded) > 120 or word_count > 12:
        return False

    # ratio de majuscules (sur la ligne originale) — les headings sont souvent en MAJ
    letters = [c for c in line if c.isalpha()]
    if letters:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio > 0.5 and word_count <= 8:
            return True

    # si la ligne suivante ressemble à une liste, la ligne courante est probablement un heading
    if next_line:
        if re.match(r"^[\-\*\u2022\u25e6\d]\s+", next_line.strip()):
            return True
        if next_line.strip().startswith("-") or next_line.strip().startswith("•"):
            return True

    # si la ligne contient un alias de section connu -> heading
    for section, aliases in _SECTION_ALIASES:
        for alias in aliases:
            if fold_text(alias) in folded:
                return True

    # règle conservatrice finale: courte et peu de mots
    avg_len = sum(len(w) for w in words) / max(1, word_count)
    if word_count <= 6 and avg_len <= 14:
        return True

    return False


def _match_heading(folded_line: str) -> str | None:
    candidate = re.sub(r"\s+", " ", folded_line.strip())
    if not candidate or len(candidate.split()) > 8:
        return None
    for section, aliases in _SECTION_ALIASES:
        for alias in aliases:
            if fold_text(alias) in candidate:
                return section
    return None


def _line_chunks(text: str) -> list[str]:
    cleaned = clean_document_text(text)
    if not cleaned:
        return []
    return [line for line in cleaned.split("\n") if line.strip()]


def _first_lines(lines: list[str], limit: int = 3) -> str:
    return "\n".join(lines[:limit]).strip()


def build_document_profile(text: str, kind: str | None = None) -> StructuredDocument:
    cleaned_text = clean_document_text(text)
    lines = _line_chunks(cleaned_text)
    sections: dict[str, list[str]] = defaultdict(list)
    current_section = "other"

    for line in lines:
        heading, payload = _split_heading_payload(line)
        if heading:
            current_section = heading
            if payload:
                sections[current_section].append(payload)
            continue
        sections[current_section].append(line)

    section_texts = {name: "\n".join(values).strip() for name, values in sections.items() if values}

    summary_text = section_texts.get("summary", "")
    experience_text = section_texts.get("experience", "")
    education_text = section_texts.get("education", "")
    certifications_text = section_texts.get("certifications", "")
    languages_text = section_texts.get("languages", "")
    contract_text = section_texts.get("contract", "")
    location_text = section_texts.get("location", "")
    job_required_text = section_texts.get("job_required", "")
    job_nice_text = section_texts.get("job_nice", "")

    skills_text = section_texts.get("skills", "")
    other_text = section_texts.get("other", "")

    if not summary_text:
        summary_text = _first_lines(lines, 3)

    if not skills_text:
        skills_text = "\n".join(part for part in (job_required_text, job_nice_text) if part).strip()

    if kind == "job" and not job_required_text:
        job_required_text = skills_text
    if kind == "job" and not job_nice_text:
        job_nice_text = section_texts.get("strength", "")

    skill_terms = _extract_skill_terms("\n".join(part for part in (skills_text, job_required_text, job_nice_text) if part))
    required_skill_terms = _extract_skill_terms(job_required_text)
    nice_skill_terms = _extract_skill_terms(job_nice_text)
    language_terms = _detect_languages("\n".join(part for part in (languages_text, cleaned_text) if part))
    contract_type = _detect_contract_type("\n".join(part for part in (contract_text, cleaned_text) if part))
    experience_years = _extract_years("\n".join(part for part in (experience_text, cleaned_text) if part))

    if kind == "cv" and not skill_terms:
        skill_terms = _extract_skill_terms(cleaned_text)

    if kind == "job" and not required_skill_terms:
        required_skill_terms = skill_terms

    if kind == "job" and not language_terms:
        language_terms = _detect_languages(section_texts.get("job_required", "") + "\n" + cleaned_text)

    if kind == "job" and not contract_type:
        contract_type = _detect_contract_type(cleaned_text)

    embedding_chunks = [
        chunk
        for chunk in [
            summary_text,
            skills_text,
            job_required_text,
            job_nice_text,
            experience_text,
            education_text,
            certifications_text,
            languages_text,
            contract_text,
            location_text,
            other_text,
        ]
        if chunk
    ]
    if not embedding_chunks and cleaned_text:
        embedding_chunks = [cleaned_text]

    return StructuredDocument(
        kind=kind or "unknown",
        raw_text=text or "",
        cleaned_text=cleaned_text,
        sections=section_texts,
        summary_text=summary_text,
        skills_text=skills_text,
        experience_text=experience_text,
        education_text=education_text,
        certifications_text=certifications_text,
        languages_text=languages_text,
        job_required_text=job_required_text,
        job_nice_text=job_nice_text,
        contract_text=contract_text,
        location_text=location_text,
        other_text=other_text,
        skill_terms=skill_terms,
        required_skill_terms=required_skill_terms,
        nice_skill_terms=nice_skill_terms,
        language_terms=language_terms,
        contract_type=contract_type,
        experience_years=experience_years,
        embedding_chunks=embedding_chunks,
    )


def detect_document_kind(text: str) -> str | None:
    folded = fold_text(text)
    job_markers = (
        "offre structuree",
        "competences requises",
        "responsabilites",
        "taches",
        "qualifications",
        "profil recherche",
        "poste",
        "missions",
        "what you will do",
        "your mission",
    )
    cv_markers = (
        "curriculum vitae",
        "curriculum-vitae",
        "cv",
        "resume",
        "experience professionnelle",
        "formations",
        "formation",
        "competences",
        "skills",
    )
    if any(fold_text(marker) in folded for marker in job_markers):
        return "job"
    if any(fold_text(marker) in folded for marker in cv_markers):
        return "cv"
    return None


def canonical_document_text(text: str, kind: str | None = None) -> str:
    return build_document_profile(text, kind=kind).canonical_text


def is_noise_term(value: str) -> bool:
    folded = fold_text(value)
    return folded in _NOISE_TERMS
