"""
Universal document parser for CV and job offers.

Handles ALL professional domains:
tech, commercial, finance, HR, marketing, legal, logistics,
health, construction, education, management.

Returns a ParsedDocument with structured fields used by matcher.py.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from .taxonomy import find_skills

# ── Utility ───────────────────────────────────────────────────────────────────


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower()


# ── Domain detection ──────────────────────────────────────────────────────────

_DOMAIN_SIGNALS: dict[str, list[str]] = {
    "tech": [
        "developpeur", "developer", "ingenieur logiciel", "software engineer",
        "backend", "frontend", "full stack", "fullstack", "data scientist", "devops",
        "python", "javascript", "kubernetes", "docker", "sql", "api rest",
        "programmation", "coding", "code", "informatique", "systemes",
    ],
    "commercial": [
        "commercial", "sales", "vente", "vendeur", "account manager",
        "developpement commercial", "business developer", "charge d affaires",
        "prospection", "crm", "portefeuille client", "chiffre d affaires",
    ],
    "finance": [
        "comptable", "comptabilite", "accounting", "auditeur", "controleur de gestion",
        "finance", "tresorier", "fiscalite", "bilan", "resultat", "ifrs",
        "sage", "cegid", "paie", "consolidation", "analyse financiere",
    ],
    "hr": [
        "ressources humaines", "rh", "recruteur", "recrutement", "charge rh",
        "talent", "sirh", "gpec", "droit du travail", "onboarding",
        "gestionnaire rh", "administration du personnel", "chargee rh",
    ],
    "marketing": [
        "marketing", "chef de produit", "product manager", "brand manager",
        "seo", "sea", "community manager", "marketing digital", "emailing",
        "communication", "chef de marque", "chargee de communication",
    ],
    "legal": [
        "juriste", "avocat", "droit", "compliance", "juridique",
        "contrat", "contentieux", "propriete intellectuelle", "reglementation",
        "notaire", "huissier", "conseil juridique",
    ],
    "logistics": [
        "logistique", "supply chain", "transport", "entrepot", "stock",
        "approvisionnement", "achats", "douane", "wms", "erp",
        "livraison", "distribution", "gestionnaire de stock",
    ],
    "health": [
        "infirmier", "medecin", "pharmacien", "aide soignant", "soins",
        "sante", "hopital", "clinique", "kinesitherapeute", "urgences",
        "bloc", "chirurgie", "patient", "nursing", "medical",
    ],
    "construction": [
        "btp", "chantier", "genie civil", "conducteur de travaux",
        "architecte", "bim", "autocad", "rehabilitation", "electricite",
        "plomberie", "maconnerie", "metreur", "maitre d oeuvre",
    ],
    "education": [
        "enseignant", "professeur", "formateur", "pedagogie", "education",
        "ecole", "lycee", "universite", "e-learning", "tutorat", "formation",
        "moniteur", "instructeur", "enseignante",
    ],
    "management": [
        "directeur", "responsable", "chef de service", "direction",
        "encadrement", "pilotage", "gouvernance", "strategie",
        "direction generale", "dg", "drh", "daf", "dsi",
    ],
}


def detect_domain(text: str) -> str:
    """
    Detect the primary professional domain of a document.
    Returns one of the domain keys in _DOMAIN_SIGNALS, or 'general'.
    Only examines the first 3000 chars to stay fast.
    """
    folded = _fold(text[:3000])
    scores: dict[str, int] = {}
    for domain, signals in _DOMAIN_SIGNALS.items():
        count = sum(1 for s in signals if _fold(s) in folded)
        if count > 0:
            scores[domain] = count
    if not scores:
        return "general"
    return max(scores, key=lambda d: scores[d])


# ── Section heading detection ─────────────────────────────────────────────────

_SECTION_DEFS: list[tuple[str, list[str]]] = [
    ("summary", [
        "profil", "profile", "about", "a propos", "a propos de moi",
        "bio", "biographie", "resume", "summary", "presentation",
        "profil professionnel", "objectif", "objectifs", "who am i",
        "profil du candidat",
    ]),
    ("skills", [
        "competences", "skills", "stack", "stack technique", "technologies",
        "outils", "outillage", "frameworks", "langages", "expertise",
        "hard skills", "soft skills", "aptitudes", "technical skills",
        "savoir faire", "savoir-faire", "connaissances", "maitrise",
    ]),
    ("experience", [
        "experience", "experiences", "work experience", "professional experience",
        "parcours", "missions", "mission", "emploi", "postes occupes",
        "employment history", "career", "parcours professionnel",
        "realisations", "achievements", "portfolio", "postes",
    ]),
    ("education", [
        "formation", "education", "etudes", "diplome", "diplomes",
        "diplomes obtenus", "academique", "scolarite", "universite",
        "ecole", "school", "cursus", "parcours academique", "enseignement",
    ]),
    ("certifications", [
        "certification", "certifications", "certificat", "certificats",
        "habilitations", "licences", "certifications professionnelles",
    ]),
    ("languages", [
        "langues", "languages", "language", "langues parlees",
        "language skills", "bilingue", "maitrise des langues",
    ]),
    ("job_required", [
        "competences requises", "exigences", "must have", "prerequis",
        "profil recherche", "profil attendu", "responsabilites",
        "missions principales", "taches", "role", "description du poste",
        "requirements", "qualifications", "ce que nous recherchons",
        "votre profil", "what we are looking for", "profil ideal",
    ]),
    ("job_nice", [
        "nice to have", "atouts", "bonus", "souhaite", "souhaitable",
        "apprecie", "sera apprecie", "un plus", "avantages",
        "ce serait un plus", "optionnel",
    ]),
    ("contract", [
        "contrat", "type de contrat", "statut", "disponibilite",
        "duree", "conditions", "contrat propose",
    ]),
    ("location", [
        "localisation", "location", "ville", "teletravail",
        "remote", "hybride", "mobilite", "lieu de travail",
    ]),
    ("contact", [
        "contact", "coordonnees", "email", "telephone", "adresse",
        "linkedin", "github", "portfolio", "me contacter",
    ]),
    ("hobbies", [
        "interets", "loisirs", "hobbies", "centres d interet",
        "passions", "activites extra",
    ]),
]


@lru_cache(maxsize=1)
def _section_lookup() -> dict[str, str]:
    """alias (folded) → section name."""
    lookup: dict[str, str] = {}
    for section, aliases in _SECTION_DEFS:
        for alias in aliases:
            lookup[_fold(alias)] = section
    return lookup


def _match_section(line: str) -> str | None:
    """Return section name if the line matches a known heading alias."""
    lookup = _section_lookup()
    folded = _fold(line.strip())
    if folded in lookup:
        return lookup[folded]
    # substring match (line contains the alias)
    for alias, section in lookup.items():
        if len(alias) >= 4 and alias in folded:
            return section
    return None


def _is_heading(line: str, next_line: str | None) -> bool:
    """Heuristic: does this line look like a section heading?"""
    s = line.strip()
    if not s:
        return False

    # Trailing colon = strong heading signal
    if s.endswith(":") and len(s) < 100:
        return True

    # Known section alias
    if _match_section(s):
        return True

    folded = _fold(s)
    words = folded.split()
    if not words:
        return False

    # ALL-CAPS short line
    letters = [c for c in s if c.isalpha()]
    if letters:
        upper = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper > 0.65 and 1 <= len(words) <= 6:
            return True

    # Short line followed by bullet list
    if next_line and re.match(r"^\s*[-•*\u2022\d]\s+", next_line):
        if 1 <= len(words) <= 6:
            return True

    return False


# ── Field extractors ──────────────────────────────────────────────────────────

_YEAR_CTX_RE = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:years?|ans?|ann[eé]e?s?)\s+d[e']\s*(?:exp[eé]rience|exp\b)"
    r"|(?:exp[eé]rience|exp)\s+(?:de\s+)?(\d{1,2})\s*\+?\s*(?:years?|ans?|ann[eé]e?s?)"
    r"|depuis\s+(\d{1,2})\s*\+?\s*(?:years?|ans?|ann[eé]e?s?)"
    r"|\+\s*(\d{1,2})\s*(?:years?|ans?|ann[eé]e?s?)",
    re.IGNORECASE,
)
_YEAR_PLAIN_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|ans?|ann[eé]e?s?)", re.IGNORECASE)
_AGE_CTX_RE = re.compile(r"\bne\b.{0,20}\d{4}|\bnaissance\b|\bage\s*[:\-]?\s*\d{1,2}\b", re.IGNORECASE)
_EXP_CTX_RE = re.compile(r"exp[eé]rience|exp\b|pratique", re.IGNORECASE)


def _extract_years(text: str) -> int:
    if not text:
        return 0
    folded = _fold(text)

    # Priority: explicit experience context patterns
    for m in _YEAR_CTX_RE.finditer(folded):
        groups = [g for g in m.groups() if g and g.isdigit()]
        if groups:
            v = int(groups[0])
            if 1 <= v <= 40:
                return v

    # Fallback: skip standalone age lines and age-context lines without experience
    safe_lines = []
    for line in folded.split("\n"):
        if re.fullmatch(r"\d{1,2}\s+ans?\.?", line.strip()):
            continue
        if _AGE_CTX_RE.search(line) and not _EXP_CTX_RE.search(line):
            continue
        safe_lines.append(line)
    values = [
        int(m) for m in _YEAR_PLAIN_RE.findall("\n".join(safe_lines))
        if m.isdigit() and 1 <= int(m) <= 40
    ]
    return max(values) if values else 0


_LANG_PATTERNS: list[tuple[str, str]] = [
    ("français", r"\bfran[cç]ais\b|\bfrench\b"),
    ("anglais", r"\banglais\b|\benglish\b|\bbilingue anglais\b"),
    ("espagnol", r"\bespagnol\b|\bspanish\b"),
    ("allemand", r"\ballemand\b|\bgerman\b|\bdeutsch\b"),
    ("arabe", r"\barabe\b|\barabic\b"),
    ("portugais", r"\bportugais\b|\bportuguese\b"),
    ("italien", r"\bitalien\b|\bitaliano\b|\bitalian\b"),
    ("mandarin", r"\bchinois\b|\bmandarin\b|\bchinese\b"),
]


def _detect_languages(text: str) -> list[str]:
    folded = _fold(text)
    found: list[str] = []
    seen: set[str] = set()
    for lang, pattern in _LANG_PATTERNS:
        if re.search(pattern, folded) and lang not in seen:
            seen.add(lang)
            found.append(lang)
    return found


_CONTRACT_PATTERNS: list[tuple[str, str]] = [
    ("CDI", r"\bcdi\b"),
    ("CDD", r"\bcdd\b"),
    ("Freelance", r"\bfreelance\b|\bindependant\b|\bconsultant independant\b"),
    ("Stage", r"\bstage\b|\binternship\b|\bstagiaire\b"),
    ("Alternance", r"\balternance\b|\bapprentissage\b|\bcontrat d apprentissage\b"),
    ("Temps plein", r"\btemps plein\b|\bfull.?time\b"),
    ("Temps partiel", r"\btemps partiel\b|\bpart.?time\b"),
    ("Télétravail", r"\bteletravail\b|\bremote\b|\bfull remote\b"),
]


def _detect_contract(text: str) -> str | None:
    folded = _fold(text)
    for label, pattern in _CONTRACT_PATTERNS:
        if re.search(pattern, folded):
            return label
    return None


# ── Text cleaning ─────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Normalize raw extracted text (no import from extraction.py to avoid cycles)."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    lines: list[str] = []
    seen: dict[str, int] = {}
    prev = ""
    for raw in text.split("\n"):
        line = re.sub(r"\u00ad", "", raw)
        line = re.sub(r"\s+", " ", line.strip())
        line = re.sub(r"^[\-*•·\u2022\u25e6]+\s*", "", line).strip()
        if not line or len(line) < 2:
            prev = ""
            continue
        key = _fold(line)
        if key == prev:
            continue
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 2:
            continue
        lines.append(line)
        prev = key
    return "\n".join(lines).strip()


# ── ParsedDocument dataclass ──────────────────────────────────────────────────

@dataclass
class ParsedDocument:
    kind: str                           # 'cv' or 'job'
    domain: str                         # 'tech', 'commercial', 'finance', etc.
    raw_text: str
    cleaned_text: str

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

    # NER (filled externally if enabled)
    person_name: str | None = None
    organization_terms: list[str] = field(default_factory=list)
    location_terms: list[str] = field(default_factory=list)

    @property
    def canonical_text(self) -> str:
        parts = [
            self.summary_text, self.skills_text, self.job_required_text,
            self.job_nice_text, self.experience_text, self.education_text,
            self.certifications_text, self.languages_text, self.other_text,
        ]
        return "\n".join(p for p in parts if p).strip()


# ── Main parse function ───────────────────────────────────────────────────────

def parse_document(text: str, kind: str = "cv") -> ParsedDocument:
    """
    Parse a CV or job offer into a structured ParsedDocument.

    Args:
        text: Raw extracted text
        kind: 'cv' or 'job'

    Returns:
        ParsedDocument with all extracted fields populated
    """
    cleaned = _clean_text(text)
    lines = [ln for ln in cleaned.split("\n") if ln.strip()]
    domain = detect_domain(cleaned)

    # Section assignment
    sections: dict[str, list[str]] = {}
    current = "other"

    for idx, line in enumerate(lines):
        next_line = lines[idx + 1] if idx + 1 < len(lines) else None

        # Inline heading: "Section: content"
        if ":" in line and len(line) < 100:
            head, _, payload = line.partition(":")
            section = _match_section(head.strip())
            if section:
                current = section
                if payload.strip():
                    sections.setdefault(current, []).append(payload.strip())
                continue

        # Full-line heading
        section = _match_section(line)
        if section and _is_heading(line, next_line):
            current = section
            continue

        # Unrecognized heading — don't assign content, just skip
        if _is_heading(line, next_line) and not _match_section(line):
            continue

        sections.setdefault(current, []).append(line)

    def sec(name: str) -> str:
        return "\n".join(sections.get(name, [])).strip()

    summary_text = sec("summary")
    skills_text = sec("skills")
    experience_text = sec("experience")
    education_text = sec("education")
    certifications_text = sec("certifications")
    languages_text = sec("languages")
    job_required_text = sec("job_required")
    job_nice_text = sec("job_nice")
    contract_text = sec("contract")
    location_text = sec("location")
    other_text = sec("other")

    # Fallback: no summary → use first 3 content lines
    if not summary_text and lines:
        summary_text = "\n".join(lines[:3])

    # Skill extraction via taxonomy
    if kind == "job":
        skill_src = "\n".join(p for p in [job_required_text, job_nice_text, skills_text] if p)
    else:
        skill_src = "\n".join(p for p in [skills_text, experience_text, other_text] if p)

    skill_terms = find_skills(skill_src or cleaned)
    required_skill_terms = find_skills(job_required_text) if job_required_text else list(skill_terms)
    nice_skill_terms = find_skills(job_nice_text) if job_nice_text else []

    # Language, contract, experience year extraction
    lang_src = "\n".join(p for p in [languages_text, cleaned[:2000]] if p)
    language_terms = _detect_languages(lang_src)

    contract_src = "\n".join(p for p in [contract_text, cleaned[:2000]] if p)
    contract_type = _detect_contract(contract_src)

    exp_src = "\n".join(p for p in [experience_text, cleaned] if p)
    experience_years = _extract_years(exp_src)

    return ParsedDocument(
        kind=kind,
        domain=domain,
        raw_text=text or "",
        cleaned_text=cleaned,
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
    )
