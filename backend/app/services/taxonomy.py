"""
Universal skill taxonomy for CV/job matching.
Covers all professional domains (tech, commercial, finance, HR, marketing,
legal, logistics, health, construction, education, management).

Inspired by ESCO (https://esco.ec.europa.eu) but embedded as Python data
to avoid runtime downloads. Extend at startup with load_esco_csv().
"""
from __future__ import annotations

import csv
import difflib
import json
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from ..settings import get_settings
from .structured_constants import _BUILTIN_SKILL_SYNONYMS

settings = get_settings()
logger = logging.getLogger(__name__)

# canonical display name → list of matching aliases (lowercase, no accents)
_SKILLS: dict[str, list[str]] = {
    # ── INFORMATIQUE & TECH ────────────────────────────────────────────────
    "Python": ["python", "py"],
    "JavaScript": ["javascript", "js", "ecmascript", "es6", "es6+", "es2015", "vanilla js"],
    "TypeScript": ["typescript", "ts"],
    "PHP": ["php", "php 7", "php 8", "php7", "php8"],
    "Symfony": ["symfony", "symfony framework"],
    "Java": ["java"],
    "C#": ["c#", "csharp", "c sharp"],
    ".NET": [".net", "dotnet", "dot net", "asp.net", "asp net", ".net core"],
    "C++": ["c++", "cplusplus", "c plus plus"],
    "Ruby": ["ruby", "ruby on rails", "rails"],
    "Golang": ["golang", "go lang", "go programming"],
    "Rust": ["rust"],
    "Swift": ["swift"],
    "Kotlin": ["kotlin"],
    "Scala": ["scala"],
    "R": ["r stats", "langage r"],
    "SQL": ["sql", "structured query language"],
    "SQL Server": ["sql server", "ms sql server", "sqlserver", "mssql", "t-sql", "tsql"],
    "SSIS": ["ssis", "sql server integration services"],
    "SSAS": ["ssas", "sql server analysis services"],
    "SSRS": ["ssrs", "sql server reporting services"],
    "PostgreSQL": ["postgresql", "postgres", "psql"],
    "MySQL": ["mysql", "maria db", "mariadb"],
    "Oracle DB": ["oracle", "oracle database", "oracle db", "pl/sql"],
    "DB2": ["db2", "ibm db2"],
    "Snowflake": ["snowflake"],
    "QlikSense": ["qliksense", "qlik sense", "qlik"],
    "QlikView": ["qlikview", "qlik view"],
    "Talend": ["talend", "talend etl", "talend open studio"],
    "Informatica": ["informatica", "informatica powercenter", "powercenter", "iics", "informatica intelligent cloud services"],
    "Business Objects": ["business objects", "businessobjects", "sap bo", "sap businessobjects", "bo xir2", "bo xi", "xir2", "xi r2"],
    "WebIntelligence": ["webintelligence", "webi", "web intelligence"],
    # Bare "sas" excluded: an extremely common French legal-entity suffix
    # (Societe par Actions Simplifiee, e.g. "ACME SAS") -- same false-positive
    # risk that ruled out a bare "recette" alias. Only the qualified product
    # names below are unambiguous.
    "SAS (logiciel)": ["sas base", "sas enterprise guide", "sas grid"],
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
    "Vue.js": ["vue.js", "vuejs", "vue js", "vuex", "pinia", "vue 3", "vue 2"],
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
    "Git": ["git", "github", "gitlab", "bitbucket", "bitbuckets", "versioning", "version control"],
    "SVN": ["svn", "subversion", "apache subversion"],
    "Linux": ["linux", "ubuntu", "debian", "centos", "bash", "shell scripting", "unix"],
    "Machine Learning": ["machine learning", "ml", "apprentissage automatique", "apprentissage machine"],
    "Deep Learning": ["deep learning", "dl", "apprentissage profond", "reseau de neurones", "neural network"],
    "NLP": ["nlp", "natural language processing", "traitement du langage naturel", "traitement du langage"],
    "Data Science": ["data science", "datascience", "science des donnees"],
    "Data Engineering": ["data engineering", "ingenierie des donnees", "pipeline de donnees", "etl", "elt", "data management"],
    "Power BI": ["power bi", "powerbi"],
    "Tableau": ["tableau", "tableau software"],
    "SAP": ["sap", "sap erp", "sap hana", "sap r3", "sap r/3"],
    "Salesforce": ["salesforce", "sfdc", "crm salesforce"],
    "Cybersécurité": ["cybersecurite", "cybersecurity", "securite informatique", "pentest", "securite reseau", "soc", "siem", "owasp", "csrf", "xss", "vulnerabilites", "vulnerabilite"],
    "ISO 27001": ["iso 27001", "iso27001", "norme iso 27001"],
    "ISO 27005": ["iso 27005", "iso27005"],
    "ISO 42001": ["iso 42001", "iso42001"],
    "EBIOS": ["ebios", "ebios rm", "methode ebios"],
    # "dora" bare collides with the first name (find_skills folds case, so
    # "Dora" the person == "DORA" the regulation) -- same class of risk as
    # "c"/"son" fixed in the ROME import, but not excluded: unlike those two
    # near-ubiquitous French function words, a stray first-name mention is
    # rare in CV/job text, and the acronym is how real GRC/finance CVs list
    # it (bare, alongside NIS2/SOX/PCI-DSS with no surrounding context) --
    # dropping the bare alias would make it undetectable in exactly that
    # real case. Accepted trade-off, not an oversight.
    "DORA": ["dora", "digital operational resilience act"],
    "NIS2": ["nis2", "nis 2", "directive nis2"],
    "CISA": ["cisa", "certified information systems auditor"],
    "PCI-DSS": ["pci-dss", "pci dss", "pcidss"],
    "SMSI": ["smsi", "isms"],
    "IAM": ["iam", "identity and access management", "gestion des identites et des acces", "gestion des identites"],
    "PKI": ["pki", "infrastructure a cles publiques", "infrastructures a cles publiques"],
    "COBIT": ["cobit", "cobit 5", "cobit 5.0", "cobit 2019"],
    "ISAE 3402": ["isae 3402", "isae3402"],
    "SOX": ["sox", "sarbanes-oxley", "sarbanes oxley"],
    "Accessibilité web": ["accessibilite", "accessibility", "accessibilite web", "accessibilite numerique",
                          "wcag", "wcag 2", "wcag 2.0", "wcag 2.1", "wcag 2.2", "wcagrgaa",
                          "rgaa", "rgaa 4", "rgaa 4.1", "a11y", "wai-aria", "aria",
                          "opquast", "axe", "axe-core", "lighthouse a11y"],
    "Monitoring": ["monitoring", "observabilite", "observability", "supervision", "apm"],
    "Prometheus": ["prometheus"],
    "Grafana": ["grafana"],
    "Datadog": ["datadog"],
    "Sentry": ["sentry"],
    "SonarQube": ["sonarqube", "sonar", "sonarcloud", "code quality", "code coverage", "qualite du code"],
    "API REST": ["api", "rest", "restful", "api rest", "web services", "webservices", "json"],
    "SOAP/XML Web Services": ["soap", "wsdl"],
    "Microservices": ["microservices", "microservice", "architecture microservices"],
    "GraphQL": ["graphql", "apollo", "apollo server", "apollo client"],
    "WebSockets": ["websocket", "websockets", "socket.io", "socketio", "ws", "grpc", "grpc"],
    "Agile": ["agile", "methode agile", "agilite", "safe", "safe framework", "scaled agile", "scaled agile framework"],
    "Scrum": ["scrum", "scrum master", "kanban"],
    "Product Owner": ["po", "product owner"],
    "ITIL": ["itil", "itil v3", "itil v4", "service level management", "slm", "service level manager", "itsm", "service desk"],
    "ServiceNow": ["servicenow", "service now", "snow"],
    "Jira": ["jira", "atlassian"],
    "Confluence": ["confluence"],
    "Excel avancé": ["excel", "microsoft excel", "tableur", "macros excel", "google sheets"],
    "VBA": ["vba", "visual basic for applications", "visual basic"],
    "Tests automatisés": ["jest", "cypress", "playwright", "selenium", "phpunit", "junit", "mocha", "chai",
                          "supertest", "newman", "vitest", "pytest", "test unitaire", "tests unitaires",
                          "test integration", "tests integration", "tests e2e", "tdd", "bdd",
                          "qa", "istqb", "uat", "assurance qualite logicielle",
                          "tests de recette"],
    "Business Intelligence": ["bi", "business intelligence", "informatique decisionnelle"],
    "Data Analyst": ["data analyst", "analyste de donnees", "analyste donnees"],
    "ORM": ["orm", "object-relational mapping", "object relational mapping"],
    "Développeur Full Stack": ["full stack", "fullstack", "full-stack"],
    "Frontend": ["frontend", "front-end", "front end"],
    "Back-office": ["backoffice", "back-office", "back office"],
    "ERP": ["erp", "enterprise resource planning", "progiciel de gestion integre", "pgi"],
    "UML": ["uml", "unified modeling language"],
    "UX/UI Design": ["ux", "ui", "ux design", "ui design", "user experience", "user interface",
                      "ihm", "interface homme machine"],
    "TMA": ["tma", "tierce maintenance applicative"],
    "SGBD": ["sgbd", "systeme de gestion de base de donnees", "dbms", "base de donnees", "bases de donnees"],
    "J2EE": ["j2ee", "jee", "java ee", "java enterprise edition"],
    "JPA": ["jpa", "java persistence api"],
    "JSF": ["jsf", "java server faces"],
    "MVC": ["mvc", "model view controller"],
    "SSO": ["sso", "single sign on", "authentification unique"],
    "ALM": ["alm", "application lifecycle management", "hp alm"],
    "GLPI": ["glpi"],
    "SCCM": ["sccm", "system center configuration manager"],
    "TFS": ["tfs", "team foundation server"],
    "Cisco": ["cisco", "ccna", "certification ccna", "cisco systems"],
    "VMware": ["vmware", "vsphere", "esxi"],
    "MDM": ["mdm", "master data management", "mobile device management"],
    "RSSI": ["rssi", "responsable securite des systemes d information"],
    "SEPA": ["sepa", "virement sepa", "prelevement sepa"],
    "SOA": ["soa", "architecture orientee services"],
    "KYC": ["kyc", "know your customer"],
    "Continuité d'activité": ["pca", "pra", "plan de continuite d activite",
                               "plan de reprise d activite", "disaster recovery"],
    "Cloud Computing": ["cloud", "cloud computing", "informatique en nuage"],
    "DevOps": ["devops", "dev ops"],
    "RPA": ["rpa", "robotic process automation", "automatisation robotisee des processus"],
    "GPO": ["gpo", "group policy object", "strategie de groupe"],
    "BPM": ["bpm", "business process management", "gestion des processus metier"],
    "WAF": ["waf", "web application firewall"],
    "Réseaux informatiques": ["vpn", "dns", "dhcp", "lan", "wan", "mpls", "vlan", "ssh",
                               "ftp", "sftp", "ospf", "san", "ldap", "tcp ip"],

    # ── GESTION DE PROJET & MANAGEMENT ────────────────────────────────────
    "Gestion de projet": ["gestion de projet", "project management", "chef de projet", "pilotage de projet", "project manager"],
    "Leadership": ["leadership", "direction d equipe", "team leadership", "encadrement"],
    "Management d'équipe": ["management d equipe", "team management", "encadrement d equipe", "gestion d equipe", "people management"],
    "Conduite du changement": ["conduite du changement", "change management", "transformation organisationnelle"],
    "PMO": ["pmo", "project management office", "bureau de projet"],
    "Prince2": ["prince2", "prince 2"],
    "PMP": ["pmp", "project management professional"],
    "Budget": ["budget", "gestion budgetaire", "budget management", "controle budgetaire"],
    "Reporting": ["reporting", "tableau de bord", "tableaux de bord", "kpi", "indicateurs de performance", "dashboard"],
    "Planification": ["planification", "planning", "ordonnancement", "gantt", "planner"],
    "Coordination": ["coordination", "coordination d equipe", "coordination de projet"],
    "Communication": ["communication", "communication professionnelle", "communication orale", "communication ecrite"],
    "Négociation": ["negociation", "negotiation", "techniques de negociation"],
    "Présentation": ["presentation", "prise de parole", "powerpoint", "pitch"],
    "Résolution de problèmes": ["resolution de problemes", "problem solving", "analyse de problemes"],
    "Coaching": ["coaching", "mentoring", "mentorat", "accompagnement"],
    "Formation": ["developpement des competences", "animation de formation", "plan de formation professionnelle"],
    "Stratégie": ["strategic planning", "planification strategique", "vision strategique", "plan strategique"],
    "Gouvernance": ["gouvernance", "governance", "pilotage", "controle interne"],
    "Parties prenantes": ["parties prenantes", "stakeholders", "stakeholder management", "gestion des parties prenantes"],
    "Cycle en V": ["cycle en v", "v-model", "v model"],

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
    "Comptabilité analytique": ["comptabilite analytique", "comptabilite de gestion"],
    "Fiscalité": ["fiscalite", "tax", "droit fiscal", "tva", "impots", "declarations fiscales", "liasse fiscale"],
    "Consolidation": ["consolidation", "consolidation comptable", "etats financiers consolides", "consolidation des comptes"],
    "IFRS": ["ifrs", "normes ifrs", "normes internationales", "ias", "us gaap"],
    "Contrôle de gestion": ["controle de gestion", "controller", "controlling", "pilotage financier"],
    "Audit": ["audit", "commissariat aux comptes", "audit financier", "audit interne", "auditeur"],
    "Trésorerie": ["tresorerie", "cash management", "gestion de tresorerie", "cash flow", "plan de tresorerie"],
    "Paie": ["paie", "paye", "gestion de la paie", "bulletin de paie", "payroll", "gestionnaire de paie"],
    "Clôture comptable": ["cloture comptable", "cloture annuelle", "cloture mensuelle", "cloture des comptes"],
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
    "Compliance": ["compliance", "conformite", "conformite reglementaire", "projet reglementaire", "rgpd", "gdpr", "lcb ft"],
    "Contentieux": ["contentieux", "procedure judiciaire", "litige", "plaidoirie"],
    "Droit pénal": ["droit penal", "droit criminel", "procedure penale"],
    "Droit immobilier": ["droit immobilier", "droit de l urbanisme", "droit de la construction"],

    # ── ASSURANCE, RISQUE & CONFORMITÉ ──────────────────────────────────────
    # Found empirically: every real job offer sampled from production came
    # with a recruiter-curated "Mots Clés.docx" -- several of its terms had
    # zero taxonomy presence at all (this whole section), which meant a
    # candidate's real domain fit here (assurance/IARD/risque) never
    # entered the skill-coverage score no matter how relevant they were.
    "IARD": ["iard"],
    # Bare "assurance" excluded: also means "confidence" in everyday French
    # ("avoir de l assurance") and is already covered separately as
    # "assurance qualite logicielle" (software QA) -- same false-positive
    # class as bare "recette"/"sas" above. Only qualified, unambiguous
    # phrases are included; a bare "Assurance" mention is still usable via
    # a job's own priority-keywords (see matcher.py::_apply_priority_keywords).
    "Assurance": ["secteur de l assurance", "compagnie d assurance", "assureur",
                  "assurance dommages", "assurance vie", "assurance iard"],
    "Gestion des sinistres": ["gestion des sinistres", "gestion de sinistre", "sinistres",
                              "sinistralite", "cycle de vie d un sinistre"],
    "Gestion des risques": ["gestion des risques", "gestion du risque", "analyse des risques",
                            "cartographie des risques", "indicateurs de risques", "risk management",
                            "risques it", "gestion des risques it"],
    "GRC (gouvernance, risques, conformité)": ["grc", "governance risk compliance",
                                               "gouvernance risques conformite"],
    # LOD = "lines of defense", the 3-line banking/insurance risk-governance
    # model -- bare LOD1/LOD2/LOD3 are unambiguous acronyms in this context.
    "Lignes de défense (LOD)": ["lod1", "lod2", "lod3", "ligne de defense", "lignes de defense",
                                "line of defense", "1st line of defense", "2nd line of defense",
                                "3lod"],
    "NIST": ["nist", "nist framework", "nist csf"],
    # "Banque"/"Finance" deliberately NOT added as bare sector words: a
    # sector mentioned in a CV/job is not itself a skill (see
    # test_generic_sector_words_are_not_skills, a pre-existing invariant
    # from the ROME import bugfix -- "Finance"/"Informatique"/etc. must
    # never resolve as a competency). A recruiter who wants a job's sector
    # tracked as a requirement can still do so per-offer via
    # priority-keywords, which is exactly how the two real production jobs
    # that listed bare "Banque"/"Finance" as priorities handle it today.
    "Analyse des besoins": ["analyse des besoins", "besoins metiers", "recueil des besoins",
                            "expression de besoin", "expression des besoins"],
    "Outils bureautiques": ["outils bureautiques", "pack office", "suite office",
                            "microsoft office", "bureautique"],
    # Bare "RUN" (IT operations/production-support, vs. "BUILD" project
    # work) and "TRM" (ambiguous acronym -- third-party/technology risk
    # management, but also unrelated meanings elsewhere) excluded: too
    # generic/ambiguous for the global dictionary, same reasoning as
    # "recette" above. Usable per-offer via priority-keywords instead.

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
    "Conduite de travaux": ["conduite de travaux", "chef de chantier", "conducteur de travaux"],
    "Maîtrise d'ouvrage": ["maitrise d ouvrage", "moa", "maitre d ouvrage", "amoa"],
    "Maîtrise d'œuvre": ["maitrise d oeuvre", "moe", "maitre d oeuvre"],
    "Électricité bâtiment": ["electrotechnique", "courants forts", "courants faibles", "cfao", "electricite batiment"],
    "Plomberie CVC": ["plomberie", "sanitaire", "genie climatique", "cvc", "hvac"],
    "Métré": ["metre", "metreur", "estimatif", "quantitatif", "bordereau"],
    "QSE": ["qse", "hse", "qhse", "securite chantier", "prevention des risques", "document unique"],

    # ── ÉDUCATION & FORMATION ─────────────────────────────────────────────
    "Pédagogie": ["pedagogie", "pedagogy", "methodes pedagogiques", "ingenierie pedagogique"],
    "E-learning": ["e-learning", "formation en ligne", "enseignement a distance", "mooc", "lms"],
    "Conception pédagogique": ["conception pedagogique", "instructional design", "design pedagogique", "ingenierie de formation"],
    "Tutorat": ["tutorat", "tutoring", "soutien scolaire", "accompagnement scolaire", "tuteur"],
    "Mathématiques": ["mathematiques", "maths", "mathematics", "statistiques appliquees"],

    # ── COMPÉTENCES TRANSVERSALES ──────────────────────────────────────────
    "Travail en équipe": ["travail en equipe", "teamwork", "esprit d equipe", "collaboration", "team player"],
    "Autonomie": ["autonomie", "autonome", "self-management", "organisation personnelle", "independant"],
    "Rigueur": ["rigueur", "precision", "minutie", "attention aux details", "rigueur professionnelle"],
    "Adaptabilité": ["adaptabilite", "adaptable", "flexibilite", "polyvalence", "agilite d adaptation"],
    "Créativité": ["creativite", "creatif", "inventivite", "ideation"],
    "Organisation": ["organisation", "sens de l organisation", "organise", "structuration"],
    "Sens du service": ["sens du service", "orientation client", "service oriented"],
    "Esprit d'analyse": ["esprit d analyse", "analytical skills", "analyse", "sens analytique", "capacite d analyse"],
    "Force de proposition": ["force de proposition", "proactif", "proactivite", "initiative", "acteur du changement"],
    "Gestion du stress": ["gestion du stress", "resistance au stress", "sang-froid", "resilience"],
    "Permis B": ["permis b", "permis de conduire", "vehicule leger"],
}


def _fold(text: str) -> str:
    """Lowercase + strip accents for matching."""
    nfkd = unicodedata.normalize("NFKD", text)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower()


_ROME_SKILLS_PATH = Path(__file__).with_name("rome_skills_data.json")


@lru_cache(maxsize=1)
def _rome_skills() -> dict[str, list[str]]:
    """Bulk skill vocabulary from France Travail's ROME 4.0 'referentiel_savoir'
    open data export (Licence Ouverte / fr-lo), scoped to concrete
    professional-knowledge categories (software, tools, standards,
    regulations, techniques) and excluding diplomas/certifications and
    domains clearly unrelated to any professional CV (the ROME "savoir"
    referential — not "competence" — was picked specifically because its
    labels are short noun phrases like this taxonomy's, unlike ESCO/EMSI
    whose skill labels are full task sentences and don't lend themselves to
    exact-phrase matching at all).

    Kept as a bundled, generated JSON file (not hand-maintained) rather than
    inline in _SKILLS: ~8500 entries would make this module unreviewable,
    and _build_lookup() below treats it as a strictly lower-priority layer
    so a hand-curated _SKILLS alias always wins on conflict.
    """
    try:
        with _ROME_SKILLS_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("ROME skills data file not found: %s", _ROME_SKILLS_PATH)
        return {}


# Found empirically: the ROME bulk import (unlike the hand-curated _SKILLS
# above, which was reviewed alias-by-alias) contains a handful of bare
# 1-2 letter aliases that collide with ordinary French words once the
# tokenizer splits on punctuation. E.g. "c" -> canonical "C" (the language)
# matches every "c'est"/"c'était" ("c'" has no apostrophe in the token
# class, so it tokenizes as bare "c"), and "son" -> canonical "Son" matches
# the extremely common possessive "son/sa/ses". A single-character alias is
# excluded categorically (never specific enough to mean a real skill in
# flowing prose); "son" is excluded by name since it's the only length>=2
# case found so far. Extend this set if find_skills() regression tests
# surface more (see test_skill_detection_false_positives.py).
_ROME_ALIAS_STOPWORDS: frozenset[str] = frozenset({"son"})


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

    # Lower-priority layer: bulk ROME vocabulary fills gaps only — it can
    # never override a hand-curated _SKILLS alias set above.
    for canonical, aliases in _rome_skills().items():
        for alias in aliases:
            key = _fold(alias)
            if key and len(key) >= 2 and key not in _ROME_ALIAS_STOPWORDS and key not in lookup:
                lookup[key] = canonical

    return lookup


def normalize_skill(text: str) -> str | None:
    """Return canonical skill name if text matches any alias, else None."""
    return _build_lookup().get(_fold(text.strip()))


def _parse_synonyms(raw: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in (chunk.strip() for chunk in raw.split(",") if chunk.strip()):
        if "=" not in item:
            continue
        src, dest = item.split("=", 1)
        src_folded = _fold(src).replace(".", " ")
        dest_folded = _fold(dest).replace(".", " ")
        if src_folded and dest_folded:
            pairs[src_folded] = dest_folded
    return pairs


@lru_cache(maxsize=8)
def _skill_synonyms_for(raw_synonyms: str) -> dict[str, str]:
    mapping = dict(_BUILTIN_SKILL_SYNONYMS)
    mapping.update(_parse_synonyms(raw_synonyms))
    return mapping


def _skill_synonyms() -> dict[str, str]:
    # Cached by the *value* of settings.scoring_synonyms (not a bare
    # no-args cache) so a monkeypatch in tests still busts the cache
    # correctly, while production — where this string never changes at
    # runtime — gets a real cache hit instead of re-parsing it on every
    # find_skills() call. Measured ~7ms/call uncached vs sub-millisecond
    # cached; find_skills() runs 2-3x per document parsed.
    return _skill_synonyms_for(settings.scoring_synonyms)


def _apply_synonyms(text: str) -> str:
    result = _fold(text).replace(".", " ")
    for source, target in sorted(_skill_synonyms().items(), key=lambda item: len(item[0]), reverse=True):
        if not source or not target or source == target:
            continue
        result = re.sub(rf"\b{re.escape(source)}\b", target, result)
    return re.sub(r"\s+", " ", result).strip()


@lru_cache(maxsize=8)
def _skill_whitelist_for(raw_keywords: str) -> tuple[str, ...]:
    parts = [p.strip() for p in re.split(r"[,;]+", raw_keywords) if p.strip()]
    return tuple(_apply_synonyms(p) for p in parts)


def _skill_whitelist() -> list[str]:
    # See _skill_synonyms() above for why this is cached by value rather
    # than left uncached or given a bare no-args cache.
    return list(_skill_whitelist_for(settings.scoring_skill_keywords or ""))


def find_skills(text: str) -> list[str]:
    """
    Find all known skills mentioned in text.
    Returns canonical names, ordered by first occurrence, deduplicated.

    Three passes, in order:
    1. Taxonomy n-gram lookup (the bulk of detection — no false positives,
       only known canonical skills/aliases).
    2. AI_REALTIME_SCORING_SKILL_KEYWORDS whitelist, exact word-boundary
       match (on synonym-normalized text) — lets an admin extend detection
       without editing the taxonomy.
    3. Fuzzy match (typo-tolerant, e.g. "Pyhton" -> "python") for whitelist
       entries that didn't match exactly.
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

    found_lower = {k.lower() for k in found}
    next_position = len(words)
    synonymized = _apply_synonyms(text)

    for skill in _skill_whitelist():
        if not skill:
            continue
        canonical = normalize_skill(skill) or skill
        if canonical.lower() in found_lower:
            continue
        if re.search(rf"\b{re.escape(skill)}\b", synonymized):
            found[canonical] = next_position
            next_position += 1
            found_lower.add(canonical.lower())

    fuzzy_words = re.findall(r"[a-z0-9+.#]+", synonymized)
    for skill in _skill_whitelist():
        if not skill:
            continue
        canonical = normalize_skill(skill) or skill
        if canonical.lower() in found_lower:
            continue
        # difflib's ratio is unreliable below ~4 characters: "git" (3) vs
        # the business acronym "it" (2, as in "stratégie IT du groupe")
        # scores exactly the 0.8 cutoff, so any mention of "IT" flagged
        # Git as a required skill on a business/functional job with no
        # technical content at all. A skill this short either has an exact
        # alias in the main taxonomy already (see _SKILLS above) or isn't
        # specific enough for typo-tolerant matching to be safe -- same
        # rationale as _ROME_ALIAS_STOPWORDS above, applied to this pass.
        if len(skill) < 4:
            continue
        if difflib.get_close_matches(skill.lower(), fuzzy_words, n=1, cutoff=0.8):
            found[canonical] = next_position
            next_position += 1
            found_lower.add(canonical.lower())

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

# Distinct from SOFT_SKILL_CANONICALS (behavioural traits): these are real
# taxonomy canonicals -- three from the original SKILLS dict, "Contrôle
# qualité" pulled in by the ROME 4.0 vocabulary import (rome_skills_data.json,
# 8500+ entries covering every job family from textiles to mechanics) -- but
# worded so generically that they almost never appear as a literal, discrete
# line on a real CV the way "SQL" or "Python" would. Left in required_skill_
# terms, they silently lower the coverage denominator for every candidate
# on any job whose description happens to use ordinary phrases like "bonne
# communication" or "sens du service client" -- confirmed in production: a
# candidate with 6 of 7 real technical requirements covered was capped at
# 66% coverage (rather than the ~90%+ a recruiter would judge) purely
# because "Communication"/"Service client"/"Contrôle qualité"/"Mathématiques"
# were counted as missing hard skills alongside SAS/SQL/SGBD. This is
# necessarily a starting list, not an audit of the full ROME import --
# other entries in that vocabulary may be similarly over-broad and are not
# yet reviewed.
_GENERIC_SKILL_CANONICALS: frozenset[str] = frozenset({
    "Communication",
    "Service client",
    "Contrôle qualité",
    "Mathématiques",
})

_EXCLUDED_FROM_HARD_SKILLS = SOFT_SKILL_CANONICALS | _GENERIC_SKILL_CANONICALS


def is_soft_skill(canonical: str) -> bool:
    return canonical in SOFT_SKILL_CANONICALS


def partition_skills(skills: list[str]) -> tuple[list[str], list[str]]:
    """Split a list of canonical skills into (hard, soft), preserving order.
    "soft" here also absorbs _GENERIC_SKILL_CANONICALS (see comment above) --
    both are excluded from hard-skill coverage for the same reason, even
    though not all of them are behavioural traits."""
    hard = [s for s in skills if s not in _EXCLUDED_FROM_HARD_SKILLS]
    soft = [s for s in skills if s in _EXCLUDED_FROM_HARD_SKILLS]
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
