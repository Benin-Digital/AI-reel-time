from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
import unicodedata
from ..settings import get_settings
from .structured_constants import (
    _BUILTIN_SKILL_SYNONYMS,
    _NOISE_TERMS,
)
from .structured_ner import (
    _SPACY_AVAILABLE,
    _extract_ner_entities,
    _is_valid_ner_entity,
    _load_ner_model,
    _load_ner_model_for,
    _unique_preserve_order,
    spacy,
)

settings = get_settings()
logger = logging.getLogger(__name__)


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
    soft_skill_terms: list[str] = field(default_factory=list)
    job_title: str | None = None
    # POC v2: ESCO-normalized skill identifiers (stable across CV phrasings).
    # Populated only when AI_REALTIME_ESCO_ENRICH_SKILLS=true.
    esco_skill_uris: list[str] = field(default_factory=list)
    language_terms: list[str] = field(default_factory=list)
    contract_type: str | None = None
    experience_years: int = 0
    person_name: str | None = None
    organization_terms: list[str] = field(default_factory=list)
    location_terms: list[str] = field(default_factory=list)
    date_terms: list[str] = field(default_factory=list)
    embedding_chunks: list[str] = field(default_factory=list)
    debug_info: dict = field(default_factory=dict)

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
    """Thin wrapper kept for backward compatibility: the taxonomy/whitelist/
    fuzzy-match logic that used to live only here now lives in
    taxonomy.find_skills, so the real scoring path (parser.py) benefits from
    it too instead of being weaker at skill detection than this display path."""
    if not text:
        return []
    from .taxonomy import find_skills as _taxonomy_find

    return _taxonomy_find(text)


_NAME_CONTACT_RE = re.compile(
    r"@|https?://|www\.|linkedin|github|\+?\d[\d\s.\-()]{7,}",
    re.IGNORECASE,
)
_NAME_SECTION_RE = re.compile(
    r"compétence|competence|expérience|experience|formation|education|"
    r"skills|profil|summary|contact|certif|langue|language|loisir|hobby|"
    r"réf|ref\b|version\b|doc-|"
    r"mission|connaissance|technique|réalisation|realisation|"
    r"parcours|diplôme|diplome|savoir|responsabilit|"
    r"objectif|domaine|présentation|presentation|à propos|a propos|"
    r"intérêt|interet|atout|qualité|qualite|soft skill|point fort",
    re.IGNORECASE,
)
_NAME_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# Words that start with uppercase but are NOT part of a person name
_NAME_STOP_WORDS = frozenset([
    # Job titles
    "developpeur", "developer", "manager", "directeur", "directrice", "chef",
    "consultant", "consultante", "expert", "experte", "ingenieur", "ingenieure",
    "technicien", "technicienne", "responsable", "analyste", "architecte",
    "assistant", "assistante", "coordinateur", "coordinatrice", "gestionnaire",
    "senior", "junior", "lead", "stagiaire", "superviseur", "superviseure",
    "charge", "chargee", "president", "vice",
    # Work context
    "direction", "transition", "gouvernance", "pilotage", "gestion", "management",
    "programme", "projet", "projets", "service", "services", "objectif",
    "activite", "activites", "operations", "organisation",
    # Language levels
    "natif", "native", "courant", "bilingue", "intermediaire", "avance",
    "avancee", "elementaire", "notions", "professionnel", "professionnelle",
    # English technical/domain words — appear capitalised in CVs but never in names
    "data", "business", "intelligence", "cloud", "computing", "analytics",
    "warehousing", "warehouse", "reporting", "solutions", "systems",
    "architecture", "infrastructure", "development", "integration", "implementation",
    "deployment", "information", "enterprise", "global", "group", "international",
    "technical", "digital", "technology", "technologies", "platform", "network",
    "security", "software", "hardware", "application", "applications",
    "conception", "modelisation", "certifie", "certified",
    # Action / section words that can lead a mis-ordered multi-column extract
    "developpement", "deploiement", "analyse", "gestion", "maintenance",
    "realisation", "realisations", "mission", "missions", "connaissances",
    "competences", "objectifs", "responsabilites", "administration",
    "coordination", "planification", "amelioration", "optimisation",
    # Education institution words: same letter-spaced-header failure mode as
    # the French connectors below, but for the "Formation"/"Éducation"
    # section -- a school name line ("LYCÉE LOUIS ARMAND") can otherwise read
    # as a plausible 2-3 word capitalised name once its own section header
    # is letter-spaced and no longer matches _NAME_SECTION_RE.
    "lycee", "universite", "ecole", "institut", "faculte", "college",
    "campus", "academie", "baccalaureat",
    # Common product / company names that appear capitalised
    "microsoft", "oracle", "azure", "google", "amazon", "office", "power",
    "sharepoint", "teams", "excel", "windows", "linux", "gitlab", "github",
    # Collaboration / DevOps tools often read before the name in multi-column CVs
    "jira", "confluence", "bitbucket", "bitbuckets", "trello", "notion",
    "snowflake", "tableau", "qlik", "qliksense", "qlikview",
    "servicenow", "sonarqube", "datadog", "sentry", "grafana", "prometheus",
    "docker", "kubernetes", "terraform", "ansible", "jenkins",
    "mongodb", "redis", "kafka", "rabbitmq", "elasticsearch",
    # French connectors/articles: never part of a real name, but a bare
    # short word like "ET" or "DE" satisfies _is_name_word's all-caps/
    # capitalised-word check just like a real name token would. Without this,
    # a section title split across capitalised words (e.g. a diploma line
    # "COMMERCE ET SERVICE") can be mistaken for a two-word name once its
    # actual header ("É D U C A T I O N") is letter-spaced and no longer
    # matches _NAME_SECTION_RE as a section marker (see
    # test_letter_spaced_header_is_not_a_name).
    "et", "de", "du", "des", "la", "le", "les", "un", "une",
    "en", "au", "aux", "pour", "avec", "sans", "sur", "dans", "par", "ou",
])


def _extract_name_rule_based(lines: list[str]) -> str | None:
    """Extract person name from first lines of a CV using heuristics only.

    Handles: typographic apostrophes, all-caps names, multi-column PDF merges.
    """
    # Lazy import: any word that resolves to a known skill is not part of a person name.
    # normalize_skill uses an lru_cache so repeated calls are just a dict lookup.
    try:
        from .taxonomy import normalize_skill as _is_known_skill
    except Exception:
        _is_known_skill = None

    def _fold_ascii(w: str) -> str:
        return unicodedata.normalize("NFKD", w.lower()).encode("ascii", "ignore").decode("ascii")

    def _is_name_word(w: str) -> bool:
        """True if w looks like a proper name word, not a mixed-case abbreviation."""
        if not w or not w[0].isupper():
            return False
        # All uppercase (CHILAVERT, N'DAH): valid name words
        if all(c.isupper() or not c.isalpha() for c in w):
            return True
        # Initial uppercase + rest all lowercase (Thierry, Reynès, N'dah)
        rest = w[1:].replace("'", "").replace("-", "")
        return bool(rest) and rest == rest.lower()

    def _collect_name_words(text: str) -> list[str]:
        """Collect leading proper-name words (max 4), excluding stop words and abbreviations."""
        collected: list[str] = []
        for token in text.split():
            clean = re.sub(r"[^A-Za-zÀ-ÿ'\-]", "", token)
            if not clean or len(clean) < 2:
                if collected:
                    break
                continue
            if not _is_name_word(clean):
                if collected:
                    break
                continue
            if _fold_ascii(clean) in _NAME_STOP_WORDS:
                break
            if _is_known_skill and _is_known_skill(clean):
                break
            collected.append(clean)
            if len(collected) == 4:
                break
        return collected

    def _is_letter_spaced(line: str) -> bool:
        """True for a decoratively kerned header like "P E L A G I E N J I K I"
        (a real name/title, one letter per token) -- common CV template style
        for the name banner. The individual letters can't be reassembled into
        words from plain extracted text alone (inter-letter and inter-word
        gaps both collapse to one space), and the same letter-spacing defeats
        _NAME_SECTION_RE on the section header that would otherwise mark the
        education/experience content coming after it as off-limits. Once such
        a line is seen, further scanning reliably picks up an unrelated
        capitalised phrase instead (a diploma, a school name, a bullet point)
        rather than the real name -- so treat it as a signal to stop, not a
        line to skip past."""
        tokens = line.split()
        if len(tokens) < 4:
            return False
        single_char = sum(1 for t in tokens if len(t) == 1)
        return single_char / len(tokens) >= 0.6

    def _try_segment(segment: str) -> str | None:
        segment = segment.replace('\u2019', "'").replace('\u2018', "'").strip()
        if not segment or len(segment) < 3:
            return None
        if _NAME_SECTION_RE.search(segment) or _NAME_YEAR_RE.search(segment):
            return None
        words = _collect_name_words(segment)
        if len(words) >= 2:
            return " ".join(words)
        return None

    # Pass 1: short clean lines (most CVs)
    for line in lines[:40]:
        line = line.replace('\u2019', "'").replace('\u2018', "'").strip()
        if not line or len(line) < 3 or len(line) > 60:
            continue
        if _is_letter_spaced(line):
            # Distinct from the "nothing found" `None` below: this is
            # positive evidence the real name sits right here but can't be
            # reassembled from flattened text -- NOT "no name-like line
            # anywhere, defer to NER". The caller must clear whatever NER
            # guessed instead of leaving it standing, since NER reads the
            # exact same garbled letter-spaced text and is just as likely to
            # misfire on it (a real production case: it picked up a
            # candidate's high school name, "Lyc\u00e9e Louis Armand", as her
            # name instead).
            return ""
        if _NAME_CONTACT_RE.search(line) or _NAME_SECTION_RE.search(line) or _NAME_YEAR_RE.search(line):
            continue
        if re.search(r"\d{3,}", line):
            continue
        words = _collect_name_words(line)
        if len(words) >= 2:
            return " ".join(words)

    # Pass 2: multi-column PDFs where header is one long merged line —
    # strip contact tokens then scan each |-separated segment
    for line in lines[:40]:
        line = line.replace('\u2019', "'").replace('\u2018', "'").strip()
        if not line or len(line) <= 60:
            continue
        stripped = re.sub(r'\S+@\S+', '', line)
        stripped = re.sub(r'\+?\d[\d\s.\-()]{7,}', '', stripped)
        stripped = re.sub(r'https?://\S+|www\.\S+', '', stripped)
        stripped = re.sub(r'\s+', ' ', stripped).strip()
        if not stripped:
            continue
        for seg in re.split(r'\|+', stripped):
            result = _try_segment(seg.strip())
            if result:
                return result
        result = _try_segment(stripped)
        if result:
            return result

    return None


def _esco_enrich(skill_terms: list[str]) -> list[str]:
    """Map skill terms to ESCO concept URIs (top-1 per term). Safe no-op if ESCO is offline.

    Records ESCO_ENRICH_TERMS_TOTAL{outcome=mapped|unmapped|error} per term so
    a drift in mapping quality (e.g. after a taxonomy import that introduces
    labels the embedding model maps poorly) shows up as a metric instead of
    silently vanishing into an empty result — see test_esco_mapping.py.
    """
    if not skill_terms:
        return []
    try:
        from .esco_taxonomy import find_skills_esco
    except Exception:
        return []
    from ..observability import ESCO_ENRICH_TERMS_TOTAL

    max_uris = int(getattr(settings, "esco_enrich_max_uris", 30) or 30)
    seen: set[str] = set()
    uris: list[str] = []
    for term in skill_terms:
        try:
            hits = find_skills_esco(term, top_k=1)
        except Exception:
            ESCO_ENRICH_TERMS_TOTAL.labels(outcome="error").inc()
            continue
        if not hits or not any(skill.uri for skill, _score in hits):
            ESCO_ENRICH_TERMS_TOTAL.labels(outcome="unmapped").inc()
            continue
        ESCO_ENRICH_TERMS_TOTAL.labels(outcome="mapped").inc()
        for skill, _score in hits:
            if skill.uri and skill.uri not in seen:
                seen.add(skill.uri)
                uris.append(skill.uri)
                if len(uris) >= max_uris:
                    return uris
    return uris


# Job-title heuristic constants. Action verbs appearing at the start of a line
# in a job offer almost always introduce a requirement bullet ("Respecter WCAG/RGAA"),
# never a job title. Title keywords mark a line as likely-title.
_JOB_CONSTRAINT_VERBS = frozenset({
    "respecter", "maitriser", "comprendre", "garantir", "assurer", "effectuer",
    "participer", "realiser", "concevoir", "creer", "mettre", "gerer", "suivre",
    "coordonner", "piloter", "animer", "definir", "optimiser", "evoluer",
    "implementer", "deployer", "developper", "ecrire", "rediger", "tester",
    "valider", "documenter", "former", "accompagner", "contribuer", "collaborer",
    "savoir", "etre",
})
_JOB_TITLE_KEYWORDS = frozenset({
    "developpeur", "developpeuse", "developer", "ingenieur", "ingenieure",
    "engineer", "architecte", "architect", "manager", "lead", "consultant",
    "consultante", "analyste", "analyst", "designer", "chef", "directeur",
    "directrice", "responsable", "expert", "experte", "technicien",
    "technicienne", "administrateur", "administratrice", "scrum", "product",
    "owner", "devops", "sre", "fullstack", "frontend", "backend", "data",
    "qa", "tester", "stagiaire", "alternant", "alternante", "apprenti",
    "apprentie", "ux", "ui",
})


def _extract_job_title(text: str, lines: list[str]) -> str | None:
    """Heuristic job-title extraction from the head of a job offer.

    Scans the first ~25 non-empty lines, rejects requirement-style lines
    (start with a constraint verb) and returns the first short line that
    contains a known job-title keyword.
    """
    candidates = [ln.strip() for ln in lines[:25] if ln and ln.strip()]
    for raw in candidates:
        line = raw.strip(" .,:;-•·\u2022\u25e6")
        if not line:
            continue
        words = line.split()
        if not (2 <= len(words) <= 10):
            continue
        if _NAME_CONTACT_RE.search(line):
            continue
        if _NAME_YEAR_RE.search(line):
            continue
        first_word = fold_text(words[0])
        if first_word in _JOB_CONSTRAINT_VERBS:
            continue
        folded_line = fold_text(line)
        tokens = set(re.findall(r"[a-z]+", folded_line))
        if tokens & _JOB_TITLE_KEYWORDS:
            return line
    return None


def build_document_profile(
    text: str,
    kind: str | None = None,
    enable_ner: bool | None = None,
    override_sections: dict[str, str] | None = None,
) -> StructuredDocument:
    """Build a StructuredDocument for display/embeddings/ESCO.

    Section/skill/experience/language/contract detection is fully delegated
    to parser.py::parse_document — the same pipeline matcher.py scores
    against. This used to be reimplemented independently here (different
    heading heuristics, no whitelist/fuzzy skill matching, a separately
    buggy text-cleaning pass) and the two could silently drift apart. Only
    what's genuinely specific to this display path stays here: NER, rule-
    based CV name extraction, job-title heuristics, ESCO enrichment, the
    `sections` dict and `embedding_chunks` used by the embeddings pipeline,
    and debug_info.
    """
    from .parser import parse_document

    resolved_kind = kind or "cv"

    doc_title_override: str | None = None
    if override_sections:
        raw_title = override_sections.get("_doc_title")
        if raw_title and raw_title.strip():
            doc_title_override = raw_title.strip()

    parsed = parse_document(text, kind=resolved_kind, override_sections=override_sections)

    cleaned_text = parsed.cleaned_text
    lines = [ln for ln in cleaned_text.split("\n") if ln.strip()]

    section_texts = {
        name: value
        for name, value in (
            ("summary", parsed.summary_text),
            ("skills", parsed.skills_text),
            ("experience", parsed.experience_text),
            ("education", parsed.education_text),
            ("certifications", parsed.certifications_text),
            ("languages", parsed.languages_text),
            ("job_required", parsed.job_required_text),
            ("job_nice", parsed.job_nice_text),
            ("contract", parsed.contract_text),
            ("location", parsed.location_text),
            ("other", parsed.other_text),
        )
        if value
    }

    esco_skill_uris: list[str] = (
        _esco_enrich(parsed.skill_terms) if getattr(settings, "esco_enrich_skills", False) else []
    )

    # decide whether to run NER: default to settings.ner_enabled when enable_ner is None
    do_ner = bool(settings.ner_enabled) if enable_ner is None else bool(enable_ner)
    if do_ner:
        ner_payload = _extract_ner_entities(cleaned_text)
        person_name = ner_payload["person_name"]
        organization_terms = list(ner_payload["organization_terms"])
        location_terms = list(ner_payload["location_terms"])
        date_terms = list(ner_payload["date_terms"])
    else:
        person_name = None
        organization_terms = []
        location_terms = []
        date_terms = []

    # For CVs: rule-based name extraction overrides NER (spaCy confuses orgs/titles with persons)
    if resolved_kind == "cv":
        rule_name = _extract_name_rule_based(lines)
        if rule_name:
            person_name = rule_name
        elif rule_name == "":
            # "" (not None) means the rule-based scan found positive
            # evidence of an unparseable letter-spaced name header -- see
            # its docstring. NER ran on the same garbled text, so its guess
            # is equally untrustworthy here; clear it instead of leaving
            # whatever it picked up standing unquestioned.
            person_name = None

    # Job offers never have a person_name (NER picks up "Fiche" from "Fiche de poste", etc.)
    if resolved_kind == "job":
        person_name = None

    # Job title: prefer Docling's first heading; fall back to heuristic line scan.
    job_title: str | None = None
    if resolved_kind == "job":
        if doc_title_override:
            job_title = doc_title_override
        else:
            job_title = _extract_job_title(cleaned_text, lines)

    embedding_chunks = [
        chunk
        for chunk in [
            parsed.summary_text,
            parsed.skills_text,
            parsed.job_required_text,
            parsed.job_nice_text,
            parsed.experience_text,
            parsed.education_text,
            parsed.certifications_text,
            parsed.languages_text,
            parsed.contract_text,
            parsed.location_text,
            parsed.other_text,
        ]
        if chunk
    ]
    if not embedding_chunks and cleaned_text:
        embedding_chunks = [cleaned_text]

    debug: dict = {}
    if person_name or organization_terms or location_terms or date_terms:
        debug["ner"] = {
            "person_name": person_name,
            "organizations": organization_terms,
            "locations": location_terms,
            "dates": date_terms,
        }

    return StructuredDocument(
        kind=kind or "unknown",
        raw_text=text or "",
        cleaned_text=cleaned_text,
        sections=section_texts,
        summary_text=parsed.summary_text,
        skills_text=parsed.skills_text,
        experience_text=parsed.experience_text,
        education_text=parsed.education_text,
        certifications_text=parsed.certifications_text,
        languages_text=parsed.languages_text,
        job_required_text=parsed.job_required_text,
        job_nice_text=parsed.job_nice_text,
        contract_text=parsed.contract_text,
        location_text=parsed.location_text,
        other_text=parsed.other_text,
        skill_terms=parsed.skill_terms,
        required_skill_terms=parsed.required_skill_terms,
        nice_skill_terms=parsed.nice_skill_terms,
        soft_skill_terms=parsed.soft_skill_terms,
        job_title=job_title,
        esco_skill_uris=esco_skill_uris,
        language_terms=parsed.language_terms,
        contract_type=parsed.contract_type,
        experience_years=parsed.experience_years,
        person_name=person_name,
        organization_terms=organization_terms,
        location_terms=location_terms,
        date_terms=date_terms,
        embedding_chunks=embedding_chunks,
        debug_info=debug,
    )


def canonical_document_text(text: str, kind: str | None = None) -> str:
    return build_document_profile(text, kind=kind).canonical_text


def is_noise_term(value: str) -> bool:
    folded = fold_text(value)
    return folded in _NOISE_TERMS


def normalize_job_offer_from_parsed(doc: StructuredDocument, source_path: str | None = None) -> dict:
    """Map a StructuredDocument (kind='job') to a dict compatible with JobOfferCreate.

    This is a heuristic mapping: picks sensible defaults and normalizes lists.
    """
    from pathlib import Path

    title = doc.job_title or (
        doc.summary_text.splitlines()[0].strip() if doc.summary_text else (Path(source_path).stem if source_path else "Offre")
    )
    # category: try to extract from first line of summary or fallback
    category = "Non renseigné"
    if doc.sections.get("summary"):
        first = doc.sections["summary"].splitlines()[0]
        if len(first.split()) <= 6:
            category = first.strip()

    contract_type = doc.contract_type or "Non renseigné"
    languages = doc.language_terms or ["Français"]

    # skills: required + nice
    skills = list(dict.fromkeys([s for s in (doc.required_skill_terms or []) + (doc.nice_skill_terms or [])]))

    # strong constraints: take top lines from job_required_text
    strong_constraints = [line.strip() for line in (doc.job_required_text or "").splitlines() if line.strip()][:6]

    description = "\n".join(
        part for part in (doc.job_required_text, doc.job_nice_text, doc.summary_text) if part
    )

    meta_keywords = list(dict.fromkeys(canonical_tokens(" ".join(skills))))[:10]

    return {
        "title": title or "Offre",
        "meta_keywords": meta_keywords,
        "contract_type": contract_type,
        "company": "Non renseigné",
        "category": category or "Non renseigné",
        "job_type": None,
        "salary_max": None,
        "languages": languages,
        "description": description or (doc.cleaned_text[:1000] if doc.cleaned_text else ""),
        "visual_code": None,
        "paragraph": None,
        "skills": skills,
        "strong_constraints": strong_constraints,
        "status": "draft",
    }
