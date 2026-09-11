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
from datetime import datetime
from functools import lru_cache

from .taxonomy import find_skills, partition_skills

# ── Utility ───────────────────────────────────────────────────────────────────


def _fold(text: str) -> str:
    # Typographic apostrophes (curly quote U+2019, acute accent U+00B4 used as
    # a lazy apostrophe by some fonts/PDF exports) are common in real
    # Word/Docs-authored CVs ("d'expérience", "aujourd'hui"). Left alone, the
    # ascii-ignore step below silently DELETES U+2019 (no ascii mapping) and
    # turns standalone U+00B4 into a bare space (its NFKD compat decomposition
    # is space + combining accent, and the combining mark then gets dropped)
    # -- either way destroying the apostrophe that many regexes downstream
    # rely on to find a word boundary, and merging or splitting words in a way
    # that breaks matching. Normalizing them to a plain "'" first keeps that
    # boundary intact for every caller of _fold, not just apostrophe-aware ones.
    text = text.replace("’", "'").replace("´", "'").replace("`", "'")
    nfkd = unicodedata.normalize("NFKD", text)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower()


# ── Domain detection ──────────────────────────────────────────────────────────

_DOMAIN_SIGNALS: dict[str, list[str]] = {
    "tech": [
        "developpeur", "developer", "ingenieur logiciel", "software engineer",
        "backend", "frontend", "full stack", "fullstack", "data scientist", "devops",
        "python", "javascript", "kubernetes", "docker", "sql", "api rest",
        "programmation", "coding", "code", "informatique", "systemes",
        "data engineer", "ingenieur bi", "business intelligence", "etl",
        "administrateur systeme", "architecte logiciel", "architecte technique",
    ],
    "commercial": [
        "commercial", "sales", "vente", "vendeur", "account manager",
        "developpement commercial", "business developer", "charge d affaires",
        "prospection", "crm", "portefeuille client", "chiffre d affaires",
        "attache commercial", "ingenieur commercial",
    ],
    "finance": [
        "comptable", "comptabilite", "accounting", "auditeur", "controleur de gestion",
        "tresorier", "fiscalite", "bilan comptable", "ifrs",
        "sage", "cegid", "paie", "consolidation", "analyse financiere",
        "expert comptable", "controle de gestion", "daf",
    ],
    "hr": [
        "ressources humaines", "recruteur", "recrutement", "charge rh",
        "talent acquisition", "sirh", "gpec", "droit du travail", "onboarding",
        "gestionnaire rh", "administration du personnel", "chargee rh",
        "responsable rh", "drh", "gestionnaire de paie",
    ],
    "marketing": [
        "marketing", "chef de produit", "product manager", "brand manager",
        "seo", "sea", "community manager", "marketing digital", "emailing",
        "chef de marque", "chargee de communication", "charge de communication",
        "content manager", "traffic manager", "growth",
    ],
    "legal": [
        "juriste", "avocat", "droit", "compliance", "juridique",
        "contentieux", "propriete intellectuelle", "reglementation",
        "notaire", "huissier", "conseil juridique", "droit des affaires",
        "droit social", "droit des contrats",
    ],
    "logistics": [
        "logistique", "supply chain", "entrepot",
        "approvisionnement", "douane", "wms",
        "livraison", "gestionnaire de stock", "responsable logistique",
        "affretement", "cariste", "magasinier", "planification logistique",
    ],
    "health": [
        "infirmier", "medecin", "pharmacien", "aide soignant", "soins",
        "hopital", "clinique", "kinesitherapeute", "urgences",
        "bloc operatoire", "chirurgie", "patient", "nursing", "medical",
        "sage femme", "radiologue", "ide",
    ],
    "construction": [
        "btp", "chantier", "genie civil", "conducteur de travaux",
        "architecte", "bim", "autocad", "rehabilitation",
        "plomberie", "maconnerie", "metreur", "maitre d oeuvre",
        "gros oeuvre", "second oeuvre", "economiste de la construction",
    ],
    "education": [
        "enseignant", "professeur", "formateur", "pedagogie",
        "ecole", "lycee", "universite", "e-learning", "tutorat",
        "moniteur", "instructeur", "enseignante", "ingenierie pedagogique",
    ],
    "management": [
        "directeur", "responsable", "chef de service", "direction",
        "encadrement", "pilotage", "gouvernance", "strategie",
        "direction generale", "dg", "dsi",
        # Gestion de projet = coeur du management de projet, souvent le vrai
        # metier de profils transverses (chef de projet IT en banque, etc.)
        "chef de projet", "cheffe de projet", "chef de projets", "gestion de projet",
        "project manager", "pilotage de projet", "pmo", "moa", "moe", "amoa", "amoe",
        "maitrise d ouvrage", "maitrise d oeuvre", "conduite du changement",
        "cadrage", "comitologie", "chef de programme",
    ],
}

# Signaux "forts" : titres de poste / metiers sans ambiguite. Comptent
# double dans le depart de domaine, car un titre de poste est bien plus
# discriminant qu'un simple outil ou mot-cle isole (ex: "sql" apparait dans
# des CV de tous domaines, "chef de projet" designe un metier precis).
_STRONG_SIGNALS: dict[str, set[str]] = {
    "tech": {"developpeur", "developer", "ingenieur logiciel", "software engineer",
             "data scientist", "devops", "data engineer", "ingenieur bi",
             "administrateur systeme", "architecte logiciel", "architecte technique"},
    "commercial": {"commercial", "account manager", "business developer",
                   "charge d affaires", "attache commercial", "ingenieur commercial"},
    "finance": {"comptable", "auditeur", "controleur de gestion", "tresorier",
                "expert comptable", "daf"},
    "hr": {"recruteur", "charge rh", "gestionnaire rh", "chargee rh",
           "responsable rh", "drh", "gestionnaire de paie"},
    "marketing": {"chef de produit", "product manager", "brand manager",
                  "community manager", "chef de marque", "content manager",
                  "traffic manager"},
    "legal": {"juriste", "avocat", "notaire", "huissier"},
    "logistics": {"responsable logistique", "gestionnaire de stock", "cariste",
                  "magasinier"},
    "health": {"infirmier", "medecin", "pharmacien", "aide soignant",
               "kinesitherapeute", "sage femme", "radiologue", "ide"},
    "construction": {"conducteur de travaux", "metreur", "maitre d oeuvre",
                     "economiste de la construction"},
    "education": {"enseignant", "professeur", "formateur", "moniteur",
                  "instructeur", "enseignante"},
    "management": {"directeur", "chef de service", "direction generale", "dg",
                   "dsi", "chef de projet", "cheffe de projet", "chef de projets",
                   "project manager", "pmo", "chef de programme"},
}


def detect_domain(text: str) -> str:
    """
    Detect the primary professional domain of a document.
    Returns one of the domain keys in _DOMAIN_SIGNALS, or 'general'.

    Weighting: a "strong" signal (a job title / occupation) counts double,
    since it is far more discriminating than a lone tool or keyword ("sql"
    appears in CVs of every domain; "chef de projet" names a specific job).
    Only the first 3000 chars are examined for speed.

    Ties are broken deterministically by _TIE_PRIORITY (occupation-defining
    domains first) rather than by dict insertion order, so a transverse
    profile (e.g. an IT project manager working in banking) doesn't fall
    into an arbitrary domain on a 1-1 keyword tie.
    """
    folded = _fold(text[:3000])
    scores: dict[str, int] = {}
    for domain, signals in _DOMAIN_SIGNALS.items():
        strong = _STRONG_SIGNALS.get(domain, set())
        score = 0
        for s in signals:
            if _fold(s) in folded:
                score += 2 if s in strong else 1
        if score > 0:
            scores[domain] = score
    if not scores:
        return "general"
    best = max(scores.values())
    top = [d for d, v in scores.items() if v == best]
    if len(top) == 1:
        return top[0]
    # Tie: prefer the domain whose *role* is most specific.
    return min(top, key=lambda d: _TIE_PRIORITY.get(d, 99))


# Lower = wins ties. Occupation-defining, less ambiguous domains rank first;
# "management" outranks "tech" so a project-manager profile that also mentions
# a couple of tools lands in management rather than tech on a tie.
_TIE_PRIORITY: dict[str, int] = {
    "health": 0,
    "legal": 1,
    "finance": 2,
    "construction": 3,
    "hr": 4,
    "education": 5,
    "logistics": 6,
    "management": 7,
    "marketing": 8,
    "commercial": 9,
    "tech": 10,
}


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
        # Job-offer phrasing for the required-experience line ("Experience
        # requise : Minimum 8 ans..."). Exact aliases, not left to the
        # generic word-boundary search, since "requise"/"demandee" aren't
        # themselves registered anywhere -- the stricter _match_section
        # (see _SECTION_STOPWORDS) would otherwise reject the whole heading
        # as an alias word buried in unrelated content, same as it now
        # correctly rejects "Technologies et outils utilises".
        "experience requise", "experience demandee", "experience souhaitee",
        "experience minimum",
    ]),
    ("education", [
        "formation", "formations", "education", "etudes", "diplome", "diplomes",
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


@lru_cache(maxsize=512)
def _alias_pattern(alias: str) -> re.Pattern:
    return re.compile(r"\b" + re.escape(alias) + r"\b")


_SECTION_STOPWORDS = {
    "et", "de", "des", "du", "la", "le", "les", "d", "l", "a", "à",
    "en", "pour", "sur", "avec", "au", "aux", "&",
    # Generic qualifiers that commonly extend a heading without changing its
    # meaning ("Expériences professionnelles", "Compétences principales") —
    # unlike a list-intro verb ("... utilisés :"), these carry no content of
    # their own, so treating them as filler doesn't risk absorbing a
    # per-bullet label like "Technologies utilisées" as a section switch.
    "professionnel", "professionnelle", "professionnels", "professionnelles",
    "personnel", "personnelle", "personnels", "personnelles",
    "principal", "principale", "principaux", "principales",
    "general", "generale", "generaux", "generales",
    "specifique", "specifiques", "cle", "cles",
}


def _match_section(line: str) -> str | None:
    """Return section name if the line matches a known heading alias.

    Only heading-shaped lines (a handful of words, like the ALL-CAPS and
    bullet-follow heuristics below) are considered. Without that guard, an
    alias word occurring naturally inside a normal sentence — or even glued
    inside an unrelated word, e.g. "role" inside "controle" without a word
    boundary — would misclassify that sentence as a section break and
    silently drop its own content from every section.

    Beyond the length guard, every word in the line besides the matched
    alias itself must be a stopword or another alias OF THE SAME SECTION.
    Real headings are made of nothing else ("Compétences et connaissances").
    Per-role bullet labels that happen to contain an alias word are not:
    "Technologies et outils utilisés : ..." matches "technologies", but
    "utilises" is neither a stopword nor a recognized alias, so it is
    correctly rejected instead of being read as a switch to the Skills
    section — which used to truncate every job entry listed after the
    first one's "Technologies utilisées" bullet out of the Experience
    section entirely (they'd be silently reassigned to Skills instead).
    """
    folded = _fold(line.strip())
    words = folded.split()
    if not words or len(words) > 6:
        return None

    lookup = _section_lookup()
    if folded in lookup:
        return lookup[folded]
    for alias, section in lookup.items():
        if len(alias) < 4 or not _alias_pattern(alias).search(folded):
            continue
        alias_words = set(alias.split())
        extra = [w for w in words if w not in alias_words and w not in _SECTION_STOPWORDS]
        if all(lookup.get(w) == section for w in extra):
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

# This runs on _fold()ed text, which now normalizes curly-quote/acute-accent
# apostrophe variants to a plain "'" before this regex ever sees them (see
# _fold), so a bare ASCII "'" here is enough to match "d'expérience" however
# it was originally typed.
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

# Date-range patterns, e.g. "2018 - 2023", "2020 – à ce jour", "depuis 2018",
# "janvier 2019 - décembre 2023", "01/2019 - 12/2023".
# NOTE: this runs on the ORIGINAL text, not the _fold()ed one, because _fold
# strips en-dash/em-dash (and accents), which would destroy the range
# separator. We therefore accept accented "ongoing" tokens here, and make the
# dash separator tolerant (hyphen/en-dash/em-dash, or just whitespace).
_DASH = r"[-–—]"
# "Aujourd'hui" almost never keeps a plain ASCII apostrophe in a real,
# Word/Docs-authored CV: word processors auto-correct it to a typographic
# quote (’, U+2019), and PDF font substitution sometimes turns it into an
# acute accent (´, U+00B4) instead. A bare `'?` only matched the ASCII form
# -- every other variant made the whole date range invisible to
# _years_from_date_ranges, silently dropping that job (often the most
# recent, ongoing one) from the total. Real case: a candidate with 5 years
# of BI experience (stated explicitly as "5 ans d'expériences" and
# corroborated by 5 job entries) came out at 0 because both of his ongoing
# roles used "Aujourd’hui"/"Aujourd´hui".
_APOS = r"['’´`]?"
_ONGOING = rf"(?:à ce jour|a ce jour|aujourd{_APOS}hui|pr[ée]sent|actuel(?:le)?|en cours|now)"
_MONTH_NAME = (
    r"(?:jan(?:vier)?|f[ée]v(?:rier)?|mars|avr(?:il)?|mai|juin|juil(?:let)?|"
    r"ao[uû]t|sept?(?:embre)?|oct(?:obre)?|nov(?:embre)?|d[ée]c(?:embre)?|"
    r"january|february|march|april|may|june|july|august|september|october|november|december)"
)
# A year is very often preceded by a month name ("janvier 2019") or a
# numeric month ("01/2019") — optional so a bare year still matches. The
# space after the month name is itself optional: PDF text extraction
# routinely glues the month straight onto the year with no space at all
# ("Décembre2022 – Mai 2023"), same class of artifact as "Technologieset"
# elsewhere in this file — a required \s+ silently dropped that whole job
# entry (and its years) out of the date-range total.
_MONTH_PREFIX = rf"(?:{_MONTH_NAME}\.?\s*|\d{{1,2}}\s*/\s*)?"
_YEAR_RANGE_RE = re.compile(
    rf"\b{_MONTH_PREFIX}(19[7-9]\d|20\d\d)\s*(?:{_DASH}|au|to|\bà\b)\s*"
    rf"{_MONTH_PREFIX}(19[7-9]\d|20\d\d|{_ONGOING})",
    re.IGNORECASE,
)
_SINCE_RE = re.compile(rf"\bdepuis\s+{_MONTH_PREFIX}(19[7-9]\d|20\d\d)\b", re.IGNORECASE)
_ONGOING_RE = re.compile(_ONGOING, re.IGNORECASE)

# Some CV templates lay job dates out in a side column, rendered by PDF
# extraction as their own short lines interleaved with the main column's
# content -- e.g. "De mai 2024 à" / "UTI GROUP Dijon, France" / "déc. 2025"
# instead of one contiguous "mai 2024 - déc. 2025". _YEAR_RANGE_RE can't see
# this as a range at all: the company/location line sitting between the
# start and end tokens isn't whitespace, so nothing bridges them. Detected
# separately by pairing a "De/Du/Depuis/D' <month> <year> à/au" line-ending
# with the next bare "<month> <year>" (or ongoing-token) line within a
# small window.
_SPLIT_RANGE_START_RE = re.compile(
    rf"\b(?:de|du|depuis|d['’´`])\s*{_MONTH_NAME}\.?\s*(19[7-9]\d|20\d\d)\s*(?:à|au)\s*$",
    re.IGNORECASE,
)
_SPLIT_RANGE_END_RE = re.compile(
    rf"^\s*{_MONTH_NAME}\.?\s*(19[7-9]\d|20\d\d)\s*$", re.IGNORECASE
)


def _merge_intervals(intervals: list[tuple[int, int]]) -> int:
    """Total number of years covered by a set of [start, end] year intervals,
    merging overlaps so parallel jobs are not double-counted.

    The regex feeding this only captures calendar years, not months, so a
    mission entirely within one year (e.g. "01/2018 - 07/2018") becomes the
    zero-length interval (2018, 2018). A consulting CV built from many such
    short back-to-back missions -- common in French IT/finance CVs -- used
    to compute a total near 0 or 1 year on a ~20-year career: consecutive
    single-year missions like (2017,2017) and (2018,2018) don't overlap and
    aren't "contiguous" by a strict start <= previous_end check (2018 >
    2017), so each contributed 0 to the sum instead of merging into a
    running total. Treating a 1-year gap as still-contiguous fixes this: it
    slightly over-merges genuine one-year employment gaps, but that's a far
    smaller error than collapsing a decade of continuous short missions
    to ~0.
    """
    if not intervals:
        return 0
    ordered = sorted(intervals)
    merged: list[list[int]] = [list(ordered[0])]
    for start, end in ordered[1:]:
        last = merged[-1]
        if start <= last[1] + 1:      # overlap, contiguous, or a 1-year gap
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged)


def _years_from_date_ranges(text: str) -> int:
    """Estimate total experience from dated job periods.

    Handles "2018 - 2023", "2020 – à ce jour", "depuis 2018". Overlapping
    periods are merged (parallel jobs don't inflate the total). Runs on the
    original (non-folded) text so typographic dashes survive. Returns 0 when
    no date range is found.
    """
    current_year = datetime.now().year
    intervals: list[tuple[int, int]] = []

    for m in _YEAR_RANGE_RE.finditer(text):
        start = int(m.group(1))
        end_raw = m.group(2).strip()
        if _ONGOING_RE.fullmatch(end_raw):
            end = current_year
        else:
            end = int(end_raw)
        if end < start or start > current_year or end > current_year:
            continue
        intervals.append((start, end))

    for m in _SINCE_RE.finditer(text):
        start = int(m.group(1))
        if start <= current_year:
            intervals.append((start, current_year))

    lines = text.split("\n")
    for i, line in enumerate(lines):
        m_start = _SPLIT_RANGE_START_RE.search(line.strip())
        if not m_start:
            continue
        start = int(m_start.group(1))
        for candidate in lines[i + 1 : i + 4]:
            candidate = candidate.strip()
            m_end = _SPLIT_RANGE_END_RE.match(candidate)
            if m_end:
                end = int(m_end.group(1))
                if start <= end <= current_year:
                    intervals.append((start, end))
                break
            if _ONGOING_RE.fullmatch(candidate):
                intervals.append((start, current_year))
                break

    total = _merge_intervals(intervals)
    return total if 1 <= total <= 40 else 0


def _explicit_years_statement(text: str) -> int:
    """Priority 1: explicit "N ans d'expérience" phrasing (most reliable).
    Returns 0 when no such statement is found."""
    if not text:
        return 0
    folded = _fold(text)
    for m in _YEAR_CTX_RE.finditer(folded):
        groups = [g for g in m.groups() if g and g.isdigit()]
        if groups:
            v = int(groups[0])
            if 1 <= v <= 40:
                return v
    return 0


def _extract_years(text: str) -> int:
    if not text:
        return 0
    folded = _fold(text)

    explicit = _explicit_years_statement(text)
    if explicit:
        return explicit

    # Priority 2: dated job periods (many CVs never write "N ans" and instead
    # list positions with date ranges — those previously returned 0). Runs on
    # the ORIGINAL text so typographic dashes/accents survive.
    from_dates = _years_from_date_ranges(text)
    if from_dates:
        return from_dates

    # Priority 3 (fallback): a bare "N ans" somewhere, skipping age lines.
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

# A recurring page header/footer ("Curriculum Vitae - Jean Dupont", "Document
# confidentiel") is almost always a full phrase, while a short recurring
# bullet ("Python", "SQL", "Rigueur") is exactly the kind of content that
# gets legitimately repeated across several job entries in a CV and must not
# be capped the same way. Mirrors extraction.py::_BOILERPLATE_MIN_LENGTH.
_BOILERPLATE_MIN_LENGTH = 20


def _clean_text(text: str) -> str:
    """Normalize raw extracted text (no import from extraction.py to avoid cycles)."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = text.replace("\u25a0", "fi")
    text = re.sub(r"(?<=[a-zA-Z\u00c0-\u024f])\?(?=[a-zA-Z\u00c0-\u024f])", "ti", text)
    lines: list[str] = []
    seen: dict[str, int] = {}
    prev = ""
    for raw in text.split("\n"):
        line = re.sub(r"\u00ad", "", raw)
        line = re.sub(r"\s+", " ", line.strip())
        line = re.sub(r"^[\-*•·\u2022\u25e6\u00fc\u00b0\u00f0►▪▫●○]+\s*", "", line).strip()
        if not line or len(line) < 2:
            prev = ""
            continue
        key = _fold(line)
        if key == prev:
            continue
        if len(line) > _BOILERPLATE_MIN_LENGTH:
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
    # Recruiter-curated priority keywords (job side only -- see
    # JobDocument.priority_keywords). Not populated by parse_document();
    # set by the caller before scoring, and folded into required_skill_terms
    # by matcher.py::match_parsed_documents() -- see that function for why
    # this can't just be find_skills()'d like everything else (some of
    # these terms, e.g. "LOD2"/"DORA", aren't in the skill taxonomy at all).
    priority_keyword_terms: list[str] = field(default_factory=list)
    soft_skill_terms: list[str] = field(default_factory=list)
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

_OVERRIDE_KNOWN_SECTIONS = {
    "summary", "skills", "experience", "education", "certifications",
    "languages", "contract", "location", "job_required", "job_nice",
}


def parse_document(
    text: str,
    kind: str = "cv",
    override_sections: dict[str, str] | None = None,
) -> ParsedDocument:
    """
    Parse a CV or job offer into a structured ParsedDocument.

    Args:
        text: Raw extracted text
        kind: 'cv' or 'job'
        override_sections: pre-split sections from an upstream structured
            conversion (Docling). When given, heuristic heading detection is
            skipped entirely and these boundaries are trusted as-is — this
            is the single section-assignment path shared with
            structured.build_document_profile, which used to reimplement
            this independently and could drift out of sync with it.

    Returns:
        ParsedDocument with all extracted fields populated
    """
    cleaned = _clean_text(text)
    lines = [ln for ln in cleaned.split("\n") if ln.strip()]
    domain = detect_domain(cleaned)

    # Section assignment
    sections: dict[str, list[str]] = {}

    if override_sections:
        for name, content in override_sections.items():
            if name == "_doc_title" or not content or not content.strip():
                continue
            # Docling labels a "Strengths"-style block "strength"; it maps
            # naturally onto job_nice (nice-to-have) rather than a section
            # of its own.
            key = "job_nice" if name == "strength" else name
            if key not in _OVERRIDE_KNOWN_SECTIONS:
                key = "other"
            sections.setdefault(key, []).append(content.strip())
    else:
        current = "other"
        for idx, line in enumerate(lines):
            next_line = lines[idx + 1] if idx + 1 < len(lines) else None

            # Inline heading: "Section: content"
            if ":" in line and len(line) < 100:
                head, _, payload = line.partition(":")
                section = _match_section(head.strip())
                if section:
                    # "Outils & technologies : Semarchy; Vertica; ..." /
                    # "Technologies utilisees : SSIS; SSAS; ..." are per-role
                    # tool call-outs that recur once per job entry inside
                    # Experience -- not a real, lasting switch to Skills.
                    # Persisting `current` here dropped every following job
                    # entry's own title/date-range line (misclassified as
                    # Skills content) until the next "Realisations :" bullet
                    # happened to reset it back. A real Skills SECTION only
                    # shows up here once; keep the payload but don't move
                    # `current` off Experience for whatever comes after it.
                    if section == "skills" and current == "experience" and payload.strip():
                        sections.setdefault(section, []).append(payload.strip())
                    else:
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

    # Skill extraction via taxonomy.
    # Section classification (_match_section) is driven by heading keywords
    # found in the text, not by `kind` — a CV can legitimately have content
    # classified as 'job_required' (e.g. a "Missions" or "Responsabilites"
    # subsection describing a past role), and a job offer can have content
    # classified as 'skills' or 'experience'. Restricting cv-mode to a
    # narrower set of sections than job-mode meant identical text could
    # yield completely different skill_terms depending on which folder it
    # was dropped in — including a self-match (same document as both CV and
    # job) collapsing to ~0% skill coverage. Aggregate the same full set of
    # sections regardless of kind so extraction only depends on content.
    skill_src = "\n".join(
        p for p in [
            job_required_text, job_nice_text, skills_text,
            summary_text, other_text, experience_text, certifications_text,
        ] if p
    )

    # Soft skills ("Rigueur", "Autonomie"...) are partitioned out of the hard
    # skill lists: matcher.py's _skill_score treats required_skill_terms as
    # the technical coverage denominator, and a soft trait counting the same
    # as a real hard skill both waters down genuine gaps and lets an
    # unrelated candidate "match" on a shared soft-skill word alone.
    all_skill_terms, soft_skill_terms = partition_skills(find_skills(skill_src or cleaned))
    skill_terms = all_skill_terms
    required_skill_terms, _ = (
        partition_skills(find_skills(job_required_text)) if job_required_text else (list(skill_terms), [])
    )
    nice_skill_terms, _ = partition_skills(find_skills(job_nice_text)) if job_nice_text else ([], [])

    # Language, contract, experience year extraction
    lang_src = "\n".join(p for p in [languages_text, cleaned[:2000]] if p)
    language_terms = _detect_languages(lang_src)

    contract_src = "\n".join(p for p in [contract_text, cleaned[:2000]] if p)
    contract_type = _detect_contract(contract_src)

    # An explicit "N ans d'experience" statement is checked against the
    # WHOLE document first: it's almost always written in the summary/
    # profile section, above wherever the CV's own "Experience" heading
    # starts (or with no such heading at all, e.g. a mission-based
    # consultant CV listing dateless "PROJET 1 / PROJET 2 / ..." entries) --
    # so restricting it to exp_src below would silently throw it away on
    # exactly the CVs most likely to state it plainly instead of listing
    # calendar dates.
    #
    # Failing that, prefer the actual experience section for date-RANGE
    # scanning: scanning the whole document as well used to let date ranges
    # from Education (e.g. "Master 2015-2017") merge into the total,
    # inflating experience_years with years spent in school. Only fall back
    # to the whole document for that scan when no experience section was
    # identified at all (some CVs never label one explicitly).
    explicit_years = _explicit_years_statement(cleaned)
    if explicit_years:
        experience_years = explicit_years
    else:
        exp_src = experience_text or cleaned
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
        soft_skill_terms=soft_skill_terms,
        language_terms=language_terms,
        contract_type=contract_type,
        experience_years=experience_years,
    )
