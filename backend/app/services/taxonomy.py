"""
Universal skill taxonomy for CV/job matching.
Covers all professional domains (tech, commercial, finance, HR, marketing,
legal, logistics, health, construction, education, management).

Inspired by ESCO (https://esco.ec.europa.eu) but embedded as Python data
to avoid runtime downloads. Extend at startup with load_esco_csv().
"""
from __future__ import annotations

import csv
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# canonical display name → list of matching aliases (lowercase, no accents)
_SKILLS: dict[str, list[str]] = {
    # ── INFORMATIQUE & TECH ────────────────────────────────────────────────
    "Python": ["python", "py"],
    "JavaScript": ["javascript", "js", "ecmascript", "es6", "es6+", "es2015", "vanilla js"],
    "TypeScript": ["typescript", "ts"],
    "PHP": ["php", "php 7", "php 8", "php7", "php8", "composer", "symfony"],
    "Java": ["java"],
    "C#": ["c#", "csharp", "c sharp", ".net", "dotnet"],
    "C++": ["c++", "cplusplus", "c plus plus"],
    "Ruby": ["ruby", "ruby on rails", "rails"],
    "Golang": ["golang", "go lang", "go programming"],
    "Rust": ["rust"],
    "Swift": ["swift"],
    "Kotlin": ["kotlin"],
    "Scala": ["scala"],
    "R": ["r stats", "langage r"],
    "SQL": ["sql", "structured query language"],
    "SQL Server": ["sql server", "ms sql server", "sqlserver", "mssql", "t-sql", "tsql",
                   "ssis", "ssas", "ssrs",
                   "sql server integration services", "sql server analysis services",
                   "sql server reporting services"],
    "PostgreSQL": ["postgresql", "postgres", "psql"],
    "MySQL": ["mysql", "maria db", "mariadb"],
    "Oracle DB": ["oracle", "oracle database", "oracle db", "pl/sql"],
    "Snowflake": ["snowflake"],
    "QlikSense": ["qliksense", "qlik sense", "qlikview", "qlik view", "qlik"],
    "Talend": ["talend", "talend etl", "talend open studio"],
    "Power Query": ["power query", "powerquery", "power query m", "scripts m"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "Elasticsearch": ["elasticsearch", "opensearch", "elastic"],
    "Kafka": ["kafka", "apache kafka", "kafka streams", "kafka connect"],
    "RabbitMQ": ["rabbitmq", "rabbit mq", "amqp"],
    "Blockchain": ["solidity", "web3", "web3.js", "web3js", "dapp", "dapps", "smart contract", "smart contracts", "ethereum", "blockchain"],
    "HTML/CSS": ["html", "html5", "css", "css3", "sass", "scss", "tailwind", "tailwindcss", "bootstrap", "styled components"],
    "React": ["react", "react.js", "reactjs", "react js", "redux", "react redux", "react hooks", "jsx", "react native"],
    "Angular": ["angular", "angularjs", "ngrx", "rxjs", "angular js"],
    "Vue.js": ["vue", "vue.js", "vuejs", "vue js", "vuex", "pinia", "vue 3", "vue 2"],
    "Node.js": ["node", "nodejs", "node.js", "node js"],
    "Next.js": ["next.js", "nextjs", "next js"],
    "Express.js": ["express.js", "expressjs", "express js", "express"],
    "NestJS": ["nestjs", "nest.js", "nest js"],
    "FastAPI": ["fastapi", "fast api"],
    "Django": ["django"],
    "Flask": ["flask"],
    "Spring Boot": ["spring", "spring boot", "springframework"],
    "Laravel": ["laravel"],
    "Docker": ["docker", "containerisation", "containerization"],
    "Kubernetes": ["kubernetes", "k8s", "kubectl"],
    "AWS": ["aws", "amazon web services", "amazon cloud"],
    "Azure": ["azure", "microsoft azure"],
    "GCP": ["gcp", "google cloud", "google cloud platform"],
    "Terraform": ["terraform", "iac", "infrastructure as code"],
    "Ansible": ["ansible"],
    "CI/CD": ["cicd", "ci/cd", "github actions", "gitlab ci", "jenkins", "devops pipeline", "circleci", "circle ci", "travis ci", "travis"],
    "Git": ["git", "github", "gitlab", "bitbucket", "bitbuckets", "versioning", "svn"],
    "Linux": ["linux", "ubuntu", "debian", "centos", "bash", "shell scripting", "unix"],
    "Machine Learning": ["machine learning", "ml", "apprentissage automatique", "apprentissage machine"],
    "Deep Learning": ["deep learning", "dl", "apprentissage profond", "reseau de neurones", "neural network"],
    "NLP": ["nlp", "natural language processing", "traitement du langage naturel", "traitement du langage"],
    "Data Science": ["data science", "datascience", "science des donnees"],
    "Data Engineering": ["data engineering", "ingenierie des donnees", "pipeline de donnees", "etl", "elt"],
    "Power BI": ["power bi", "powerbi"],
    "Tableau": ["tableau", "tableau software"],
    "SAP": ["sap", "sap erp", "sap hana", "sap r3", "sap r/3"],
    "Salesforce": ["salesforce", "sfdc", "crm salesforce"],
    "Cybersécurité": ["cybersecurite", "cybersecurity", "securite informatique", "pentest", "securite reseau", "soc", "siem", "owasp", "csrf", "xss"],
    "Accessibilité web": ["accessibilite", "accessibility", "accessibilite web", "accessibilite numerique",
                          "wcag", "wcag 2", "wcag 2.0", "wcag 2.1", "wcag 2.2", "wcagrgaa",
                          "rgaa", "rgaa 4", "rgaa 4.1", "a11y", "wai-aria", "aria",
                          "opquast", "axe", "axe-core", "lighthouse a11y"],
    "Monitoring": ["monitoring", "observabilite", "observability", "datadog", "sentry", "prometheus", "grafana", "newrelic", "dynatrace"],
    "SonarQube": ["sonarqube", "sonar", "sonarcloud", "code quality", "code coverage", "qualite du code"],
    "API REST": ["api", "rest", "restful", "api rest", "web services", "microservices"],
    "GraphQL": ["graphql", "apollo", "apollo server", "apollo client"],
    "WebSockets": ["websocket", "websockets", "socket.io", "socketio", "ws", "grpc", "grpc"],
    "Agile": ["agile", "methode agile", "agilite", "safe", "safe framework", "scaled agile", "scaled agile framework"],
    "Scrum": ["scrum", "scrum master", "kanban"],
    "ITIL": ["itil", "itil v3", "itil v4", "service level management", "slm", "service level manager", "itsm", "service desk"],
    "ServiceNow": ["servicenow", "service now", "snow"],
    "Jira": ["jira", "confluence", "atlassian"],
    "Excel avancé": ["excel", "microsoft excel", "tableur", "vba", "macros excel", "google sheets"],
    "Tests automatisés": ["jest", "cypress", "playwright", "selenium", "phpunit", "junit", "mocha", "chai",
                          "supertest", "newman", "vitest", "pytest", "test unitaire", "tests unitaires",
                          "test integration", "tests integration", "tests e2e", "tdd", "bdd"],

    # ── GESTION DE PROJET & MANAGEMENT ────────────────────────────────────
    "Gestion de projet": ["gestion de projet", "project management", "chef de projet", "pilotage de projet", "project manager"],
    "Leadership": ["leadership", "direction d equipe", "team leadership", "encadrement"],
    "Management d'équipe": ["management d equipe", "team management", "encadrement d equipe", "gestion d equipe", "people management"],
    "Conduite du changement": ["conduite du changement", "change management", "transformation organisationnelle"],
    "PMO": ["pmo", "project management office", "bureau de projet"],
    "Prince2": ["prince2", "prince 2"],
    "PMP": ["pmp", "project management professional"],
    "Budget": ["budget", "gestion budgetaire", "budget management", "controle budgetaire"],
    "Reporting": ["reporting", "tableau de bord", "kpi", "indicateurs de performance", "dashboard"],
    "Planification": ["planification", "planning", "ordonnancement", "gantt", "planner"],
    "Coordination": ["coordination", "coordination d equipe", "coordination de projet"],
    "Communication": ["communication", "communication professionnelle", "communication orale", "communication ecrite"],
    "Négociation": ["negociation", "negotiation", "techniques de negociation"],
    "Présentation": ["presentation", "prise de parole", "powerpoint", "pitch"],
    "Résolution de problèmes": ["resolution de problemes", "problem solving", "analyse de problemes"],
    "Coaching": ["coaching", "mentoring", "mentorat", "accompagnement"],
    "Formation": ["developpement des competences", "animation de formation", "plan de formation professionnelle", "ingenierie pedagogique"],
    "Stratégie": ["strategic planning", "planification strategique", "vision strategique", "plan strategique"],
    "Gouvernance": ["gouvernance", "governance", "pilotage", "controle interne"],

    # ── COMMERCIAL & VENTE ────────────────────────────────────────────────
    "Développement commercial": ["developpement commercial", "business development", "bizdev", "developpement des affaires", "business developer"],
    "Vente": ["vente", "sales", "commercialisation", "acte de vente", "vendeur", "commercial"],
    "Prospection": ["prospection", "prospection commerciale", "cold calling", "demarchage", "teleprospection"],
    "CRM": ["crm", "gestion de la relation client", "customer relationship management", "hubspot", "pipedrive", "zoho"],
    "Account Management": ["account management", "gestion de compte", "key account", "grands comptes", "account manager", "kam"],
    "Service client": ["service client", "customer service", "relation client", "satisfaction client", "customer success", "customer care"],
    "Fidélisation": ["fidelisation", "retention", "retention client", "programme fidelite"],
    "Appel d'offres": ["appel d offres", "reponse a appel d offres", "ao", "rfp", "appel d offre"],
    "Vente B2B": ["vente b2b", "b2b", "business to business", "vente entreprise"],
    "Vente B2C": ["vente b2c", "b2c", "business to consumer", "vente au detail", "vente en magasin"],
    "Trade marketing": ["trade marketing", "animation reseau", "sell-out", "merchandising"],
    "Force de vente": ["force de vente", "animation equipe commerciale", "coaching commercial"],

    # ── MARKETING & COMMUNICATION ──────────────────────────────────────────
    "Marketing digital": ["marketing digital", "digital marketing", "marketing en ligne", "web marketing"],
    "SEO": ["seo", "referencement naturel", "search engine optimization", "referencement"],
    "SEA": ["sea", "google ads", "adwords", "publicite payante", "sem", "bing ads"],
    "Réseaux sociaux": ["reseaux sociaux", "social media", "community management", "community manager"],
    "Content Marketing": ["content marketing", "marketing de contenu", "creation de contenu", "inbound marketing"],
    "Emailing": ["emailing", "email marketing", "newsletters", "mailchimp", "sendinblue", "klaviyo"],
    "Google Analytics": ["google analytics", "analytics", "analyse d audience", "web analytics", "ga4"],
    "Branding": ["branding", "image de marque", "identite de marque", "brand management"],
    "Relations presse": ["relations presse", "rp", "pr", "relations publiques", "presse"],
    "Événementiel": ["evenementiel", "organisation d evenements", "event management", "event planner"],
    "Copywriting": ["copywriting", "redaction publicitaire", "redaction web", "content writing"],
    "Design graphique": ["photoshop", "adobe photoshop", "indesign", "adobe indesign", "illustrator", "canva", "figma", "design graphique", "pao"],
    "WordPress": ["wordpress", "cms", "woocommerce", "prestashop", "shopify"],

    # ── COMPTABILITÉ & FINANCE ─────────────────────────────────────────────
    "Comptabilité générale": ["comptabilite generale", "comptabilite", "accounting", "tenue de comptabilite", "comptable"],
    "Comptabilité analytique": ["comptabilite analytique", "controle de gestion", "comptabilite de gestion", "controlling"],
    "Fiscalité": ["fiscalite", "tax", "droit fiscal", "tva", "impots", "declarations fiscales", "liasse fiscale"],
    "Consolidation": ["consolidation", "consolidation comptable", "etats financiers consolides", "consolidation des comptes"],
    "IFRS": ["ifrs", "normes ifrs", "normes internationales", "ias", "us gaap"],
    "Contrôle de gestion": ["controle de gestion", "controller", "controlling", "analyse financiere", "pilotage financier"],
    "Audit": ["audit", "commissariat aux comptes", "audit financier", "audit interne", "auditeur"],
    "Trésorerie": ["tresorerie", "cash management", "gestion de tresorerie", "cash flow", "plan de tresorerie"],
    "Paie": ["paie", "paye", "gestion de la paie", "bulletin de paie", "payroll", "gestionnaire de paie"],
    "Clôture comptable": ["cloture", "cloture comptable", "cloture annuelle", "cloture mensuelle"],
    "Sage": ["sage", "sage 100", "sage x3", "sage compta"],
    "Cegid": ["cegid", "cegid business", "cegid expert"],
    "SAP FI": ["sap fi", "sap fico", "sap finance", "finance erp"],
    "Analyse financière": ["analyse financiere", "financial analysis", "analyse de bilan", "analyse des ratios", "modeles financiers"],

    # ── RESSOURCES HUMAINES ────────────────────────────────────────────────
    "Recrutement": ["recrutement", "recruitment", "sourcing", "talent acquisition", "chasse de tetes", "recruteur"],
    "GPEC": ["gpec", "gepp", "gestion des emplois et competences", "gestion previsionnelle des emplois"],
    "SIRH": ["sirh", "hris", "workday", "oracle hrm", "sap hr", "systeme rh", "success factors"],
    "Droit du travail": ["droit du travail", "droit social", "droit du travail et de l emploi", "code du travail"],
    "Gestion des talents": ["gestion des talents", "talent management", "developpement des talents", "peoples review"],
    "Administration du personnel": ["administration du personnel", "administration rh", "gestion administrative rh"],
    "Relations sociales": ["relations sociales", "negociation syndicale", "dialogue social", "cse", "irp"],
    "Formation professionnelle": ["formation professionnelle", "plan de formation", "cpf", "plan de developpement des competences"],
    "Onboarding": ["onboarding", "accueil des nouveaux collaborateurs"],
    "Qualité de vie au travail": ["qvt", "bien etre au travail", "qualite de vie au travail", "rse", "qualite de vie"],
    "Gestion des conflits": ["gestion des conflits", "mediation", "resolution de conflits"],

    # ── DROIT & JURIDIQUE ─────────────────────────────────────────────────
    "Droit des contrats": ["droit des contrats", "contract law", "redaction de contrats", "droit contractuel"],
    "Droit des affaires": ["droit des affaires", "business law", "droit commercial", "droit des societes"],
    "Propriété intellectuelle": ["propriete intellectuelle", "pi", "brevets", "marques", "droits d auteur", "pi"],
    "Droit public": ["droit public", "droit administratif", "droit constitutionnel", "droit de la commande publique"],
    "Compliance": ["compliance", "conformite", "conformite reglementaire", "rgpd", "gdpr", "lcb ft"],
    "Contentieux": ["contentieux", "procedure judiciaire", "litige", "plaidoirie"],
    "Droit pénal": ["droit penal", "droit criminel", "procedure penale"],
    "Droit immobilier": ["droit immobilier", "droit de l urbanisme", "droit de la construction"],

    # ── LOGISTIQUE & SUPPLY CHAIN ──────────────────────────────────────────
    "Supply Chain": ["supply chain", "chaine d approvisionnement", "chaine logistique", "supply chain management"],
    "Gestion des stocks": ["gestion des stocks", "stock management", "inventaire", "gestion d entrepot", "gestion de stocks"],
    "Transport": ["logistique transport", "gestion du transport", "affretement", "expedition", "gestion des transports"],
    "Douane": ["douane", "transit douanier", "dedouanement", "incoterms", "transit"],
    "WMS": ["wms", "warehouse management system", "gestion entrepot", "manhattan", "reflex"],
    "ERP Logistique": ["sap mm", "sap sd", "oracle scm", "erp logistique", "sap wm"],
    "Approvisionnement": ["approvisionnement", "achats", "procurement", "purchasing", "acheteur"],
    "Planification logistique": ["planification logistique", "s&op", "sales and operations planning", "mrp"],
    "Distribution": ["reseau de distribution", "logistique du dernier km", "livraison last mile"],
    "Lean": ["lean", "lean management", "lean manufacturing", "kaizen"],
    "Six Sigma": ["six sigma", "6 sigma", "6sigma", "black belt", "green belt", "dmaic"],
    "Qualité": ["management de la qualite", "iso 9001", "certification qualite", "demarche qualite", "smed"],

    # ── SANTÉ & MÉDICAL ───────────────────────────────────────────────────
    "Soins infirmiers": ["soins infirmiers", "infirmier", "nursing", "soins aux patients", "ide"],
    "Pharmacologie": ["pharmacologie", "pharmacie", "medicaments", "dispensation", "pharmacien"],
    "Soins d'urgence": ["urgences", "soins d urgence", "smur", "reanimation", "samu"],
    "Bloc opératoire": ["bloc operatoire", "chirurgie", "instrumentiste", "aide soignant", "ibode"],
    "Médecine générale": ["medecine generale", "omnipraticien", "consultation medicale", "medecin"],
    "Radiologie": ["radiologie", "imagerie medicale", "echographie", "scanner", "irm", "manipulateur"],
    "Kinésithérapie": ["kinesitherapie", "kinesitherapeute", "reeducation", "physiotherapie", "mkde"],
    "Psychologie": ["psychologie", "psychologue", "psychotherapie", "counseling", "therapie"],
    "Nutrition": ["nutrition", "dietetique", "dieteticien", "dietetiste"],
    "Hygiène hospitalière": ["hygiene hospitaliere", "bio-nettoyage", "asepsie", "sterilisation"],

    # ── BTP & CONSTRUCTION ────────────────────────────────────────────────
    "AutoCAD": ["autocad", "cao", "dessin assiste par ordinateur", "dessin technique", "catia", "solidworks"],
    "BIM": ["bim", "building information modeling", "revit", "archicad", "bim manager"],
    "Génie civil": ["genie civil", "civil engineering", "beton arme", "gros oeuvre"],
    "Conduite de travaux": ["conduite de travaux", "chef de chantier", "maitrise d oeuvre", "moe", "conducteur de travaux"],
    "Maîtrise d'ouvrage": ["maitrise d ouvrage", "moa", "maitre d ouvrage", "amoa"],
    "Électricité bâtiment": ["electrotechnique", "courants forts", "courants faibles", "cfao", "electricite batiment"],
    "Plomberie CVC": ["plomberie", "sanitaire", "genie climatique", "cvc", "hvac"],
    "Métré": ["metre", "metreur", "estimatif", "quantitatif", "bordereau"],
    "QSE": ["qse", "hse", "qhse", "securite chantier", "prevention des risques", "document unique"],

    # ── ÉDUCATION & FORMATION ─────────────────────────────────────────────
    "Pédagogie": ["pedagogie", "pedagogy", "methodes pedagogiques", "ingenierie pedagogique"],
    "E-learning": ["e-learning", "formation en ligne", "enseignement a distance", "mooc", "lms"],
    "Conception pédagogique": ["conception pedagogique", "instructional design", "design pedagogique", "ingenierie de formation"],
    "Tutorat": ["tutorat", "tutoring", "soutien scolaire", "accompagnement scolaire", "tuteur"],
    "Mathématiques": ["mathematiques", "maths", "mathematics", "algebre", "analyse"],

    # ── COMPÉTENCES TRANSVERSALES ──────────────────────────────────────────
    "Travail en équipe": ["travail en equipe", "teamwork", "esprit d equipe", "collaboration", "team player"],
    "Autonomie": ["autonomie", "autonome", "self-management", "organisation personnelle", "independant"],
    "Rigueur": ["rigueur", "precision", "minutie", "attention aux details", "rigueur professionnelle"],
    "Adaptabilité": ["adaptabilite", "adaptable", "flexibilite", "polyvalence", "agilite d adaptation"],
    "Créativité": ["creativite", "creatif", "inventivite", "ideation"],
    "Organisation": ["organisation", "sens de l organisation", "organise", "structuration"],
    "Sens du service": ["sens du service", "orientation client", "service oriented", "service client"],
    "Esprit d'analyse": ["esprit d analyse", "analytical skills", "analyse", "sens analytique", "capacite d analyse"],
    "Force de proposition": ["force de proposition", "proactif", "proactivite", "initiative", "acteur du changement"],
    "Gestion du stress": ["gestion du stress", "resistance au stress", "sang-froid", "resilience"],
    "Permis B": ["permis b", "permis de conduire", "vehicule leger"],
}


def _fold(text: str) -> str:
    """Lowercase + strip accents for matching."""
    nfkd = unicodedata.normalize("NFKD", text)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower()


@lru_cache(maxsize=1)
def _build_lookup() -> dict[str, str]:
    """Return alias → canonical_name mapping (cached).

    Only aliases are indexed — canonical names are NOT auto-indexed.
    This prevents single common words (e.g. "distribution", "qualite")
    from generating false positives when they happen to match a canonical name.
    Each skill that should match its own canonical word must include it as an alias.
    """
    lookup: dict[str, str] = {}
    for canonical, aliases in _SKILLS.items():
        for alias in aliases:
            key = _fold(alias)
            if key:
                lookup[key] = canonical
                # index space-for-slash form so "ci cd" matches "CI/CD" after slash normalisation
                if "/" in key:
                    space_key = key.replace("/", " ")
                    if space_key and space_key not in lookup:
                        lookup[space_key] = canonical
    return lookup


def normalize_skill(text: str) -> str | None:
    """Return canonical skill name if text matches any alias, else None."""
    return _build_lookup().get(_fold(text.strip()))


def find_skills(text: str) -> list[str]:
    """
    Find all known skills mentioned in text.
    Returns canonical names, ordered by first occurrence, deduplicated.
    """
    if not text:
        return []
    lookup = _build_lookup()
    # Replace slashes with spaces so "php/laravel" → ["php","laravel"] and "ci/cd" → 2-gram "ci cd"
    folded = _fold(text).replace("/", " ")
    # Tokens keep internal '.', '#', '+' (needed for "node.js", "c#", "c++"),
    # but leading/trailing punctuation is stripped so a sentence-final period
    # doesn't fuse into the token ("qliksense." → "qliksense", "python." →
    # "python"). Without this, any skill ending a sentence or list item was
    # silently missed. A bare "." (e.g. from "5.") collapses to an empty
    # token and is dropped.
    raw_words = re.findall(r"[a-z0-9#+.]+", folded)
    words = [w.strip(".") for w in raw_words]
    words = [w for w in words if w]

    found: dict[str, int] = {}  # canonical → first word-position
    # Longest match first (up to 5-gram)
    for n in range(min(5, len(words)), 0, -1):
        for i in range(len(words) - n + 1):
            gram = " ".join(words[i: i + n])
            if gram in lookup:
                canonical = lookup[gram]
                if canonical not in found:
                    found[canonical] = i

    return [k for k, _ in sorted(found.items(), key=lambda x: x[1])]


# Canonicals from the "COMPÉTENCES TRANSVERSALES" block above. Listed in a
# frozenset to partition technical skills from behavioural ones — soft skills
# pollute the technical match signal when mixed into skill_terms.
SOFT_SKILL_CANONICALS: frozenset[str] = frozenset({
    "Travail en équipe",
    "Autonomie",
    "Rigueur",
    "Adaptabilité",
    "Créativité",
    "Organisation",
    "Sens du service",
    "Esprit d'analyse",
    "Force de proposition",
    "Gestion du stress",
    "Permis B",
})


def is_soft_skill(canonical: str) -> bool:
    return canonical in SOFT_SKILL_CANONICALS


def partition_skills(skills: list[str]) -> tuple[list[str], list[str]]:
    """Split a list of canonical skills into (hard, soft), preserving order."""
    hard = [s for s in skills if s not in SOFT_SKILL_CANONICALS]
    soft = [s for s in skills if s in SOFT_SKILL_CANONICALS]
    return hard, soft


def load_esco_csv(csv_path: str | Path) -> int:
    """
    Extend the taxonomy from an ESCO skills CSV export.
    Returns the number of new canonical skills added.

    Download at: https://esco.ec.europa.eu/en/use-esco/download
    Expected columns: preferredLabel, altLabels
    """
    path = Path(csv_path)
    if not path.exists():
        logger.warning("ESCO CSV not found: %s", path)
        return 0

    added = 0
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                label = (row.get("preferredLabel") or "").strip()
                if not label:
                    continue
                alt_raw = row.get("altLabels") or ""
                aliases = [a.strip() for a in re.split(r"[\n|]+", alt_raw) if a.strip()]
                if label not in _SKILLS:
                    _SKILLS[label] = [label.lower()] + [a.lower() for a in aliases]
                    added += 1
                else:
                    existing = set(_SKILLS[label])
                    _SKILLS[label].extend(a.lower() for a in aliases if a.lower() not in existing)

        _build_lookup.cache_clear()
        logger.info("Loaded %d new skills from ESCO CSV: %s", added, path)
    except Exception as exc:
        logger.exception("Failed to load ESCO CSV %s: %s", path, exc)

    return added
