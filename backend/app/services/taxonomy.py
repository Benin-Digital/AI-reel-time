"""
Universal skill taxonomy for CV/job matching.
Covers all professional domains (tech, commercial, finance, HR, marketing,
legal, logistics, health, construction, education, management).

Inspired by ESCO (https://esco.ec.europa.eu) and France Travail's ROME 4.0,
both embedded as generated Python data (see _rome_skills()/_esco_skills())
to avoid runtime downloads or CSV parsing on every request.
"""
from __future__ import annotations

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
    "Back-office": [
        "backoffice", "back-office", "back office",
        # Plural form, unreachable without stemming (find_skills does exact
        # n-gram lookup, see the "sinistre(s)" precedent above): a real CV
        # wrote "des outils metiers et des back-offices" and it stayed
        # invisible to the taxonomy despite the singular alias existing.
        # "back offices" (space) is the form find_skills() actually builds
        # its n-grams against -- its tokenizer (`[a-z0-9#+.]+`) treats the
        # hyphen as a plain word separator, so "back-offices" the raw
        # string never reaches the lookup as a single hyphenated token.
        "backoffices", "back-offices", "back offices",
    ],
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

    # ── TECH (COMPLÉMENT 2026-09-17) : data/IA, cloud, DevOps, mobile, ────
    # tests, cybersécurité, réseaux, design, IoT, jeu vidéo, architecture,
    # low-code, marketing tech. Demande explicite de couverture exhaustive
    # du domaine tech ; chaque alias verifie contre le dictionnaire existant
    # (pas de doublon) et contre le risque de collision avec un mot
    # francais/anglais ordinaire (meme discipline que "Chef"/"SAS"/
    # "Eclipse" trouves plus tot le meme jour) -- ex: "solid"/"pandas"/
    # "sketch" gardes uniquement sous leur forme qualifiee, "Consul" sans
    # alias nu (collision avec le mot francais "consul").
    "Scikit-learn": ["scikit learn", "scikit-learn", "sklearn"],
    "Pandas": ["pandas dataframe", "pandas python"],
    "NumPy": ["numpy"],
    "Jupyter": ["jupyter", "jupyter notebook", "jupyterlab"],
    "Hugging Face": ["hugging face", "huggingface", "transformers library"],
    "LangChain": ["langchain"],
    "LLM": ["grands modeles de langage", "large language model", "large language models", "llm"],
    "IA Générative": ["genai", "generative ai", "ia generative"],
    "Prompt Engineering": ["conception de prompts", "ingenierie de prompt", "prompt engineering"],
    "RAG": ["rag", "rag llm", "retrieval augmented generation"],
    "Base de données vectorielle": ["base de donnees vectorielle", "chromadb", "faiss", "milvus", "pinecone", "vector database", "weaviate"],
    "OpenAI API": ["chatgpt api", "gpt-4", "gpt4", "openai api"],
    "Computer Vision": ["computer vision", "opencv"],
    "MLOps": ["mlflow", "mlops"],
    "XGBoost": ["xgboost"],
    "LightGBM": ["lightgbm"],
    "Reinforcement Learning": ["apprentissage par renforcement", "reinforcement learning"],
    "Feature Engineering": ["feature engineering", "ingenierie des caracteristiques"],
    "Databricks": ["databricks"],
    "PySpark": ["py spark", "pyspark"],
    "dbt": ["data build tool", "dbt"],
    "Apache Flink": ["apache flink", "flink"],
    "Presto/Trino": ["presto db", "presto/trino", "trino sql"],
    "ClickHouse": ["clickhouse"],
    "AWS Lambda": ["amazon lambda", "aws lambda"],
    "Amazon S3": ["amazon s3", "aws s3"],
    "Amazon RDS": ["amazon rds", "aws rds"],
    "Amazon EKS": ["amazon eks", "aws eks", "elastic kubernetes service"],
    "Amazon ECS": ["amazon ecs", "aws ecs", "elastic container service"],
    "Amazon SQS": ["amazon sqs", "aws sqs"],
    "Amazon SNS": ["amazon sns", "aws sns"],
    "Amazon CloudFront": ["amazon cloudfront", "aws cloudfront"],
    "Amazon VPC": ["amazon vpc", "aws vpc"],
    "Amazon Route 53": ["amazon route 53", "aws route53", "route 53"],
    "Azure Functions": ["azure functions"],
    "Azure DevOps": ["azure devops"],
    "AKS": ["aks", "aks cluster", "azure kubernetes service"],
    "Azure Cosmos DB": ["azure cosmos db", "cosmosdb"],
    "Azure Blob Storage": ["azure blob storage", "blob storage"],
    "Google BigQuery": ["bigquery", "google bigquery"],
    "Google Cloud Functions": ["cloud functions gcp", "google cloud functions"],
    "GKE": ["gke", "gke cluster", "google kubernetes engine"],
    "Google Pub/Sub": ["google pub sub", "google pub/sub", "pub/sub gcp"],
    "Multi-cloud": ["cloud hybride", "hybrid cloud", "multi-cloud", "multicloud"],
    "Helm": ["helm", "helm charts", "helm kubernetes"],
    "ELK Stack": ["elk stack", "kibana", "logstash"],
    "HashiCorp Vault": ["hashicorp vault", "vault secrets"],
    # "Consul" (HashiCorp) sans alias nu : collision avec le mot francais
    # "consul" (representant diplomatique) -- meme risque que "chef"/"sas".
    "Consul": ["hashicorp consul"],
    "ArgoCD": ["argo cd", "argocd"],
    "GitOps": ["gitops"],
    "Istio": ["istio", "istio service mesh"],
    "Service Mesh": ["maillage de services", "service mesh"],
    "Nginx": ["nginx"],
    "Apache HTTP Server": ["apache http server", "apache2", "httpd"],
    "HAProxy": ["haproxy"],
    "Load Balancing": ["equilibrage de charge", "load balancing", "repartition de charge"],
    "Packer": ["hashicorp packer", "packer"],
    "Site Reliability Engineering": ["site reliability engineering", "sre"],
    "SwiftUI": ["swiftui"],
    "Jetpack Compose": ["jetpack compose"],
    "Flutter": ["dart", "flutter"],
    "Xamarin": ["xamarin"],
    "Ionic": ["ionic", "ionic framework"],
    "Neo4j": ["base de donnees graphe", "graph database", "neo4j"],
    "InfluxDB": ["base de donnees temporelle", "influxdb", "time series database"],
    "CouchDB": ["apache couchdb", "couchdb"],
    "JMeter": ["apache jmeter", "jmeter"],
    "Gatling": ["gatling", "gatling load testing"],
    "k6": ["grafana k6", "k6", "k6 load testing"],
    "Appium": ["appium", "appium mobile testing"],
    "Robot Framework": ["robot framework"],
    "Burp Suite": ["burp suite", "burpsuite"],
    "Nmap": ["nmap"],
    "SOAR": ["security orchestration", "soar", "soar security"],
    "EDR": ["edr", "edr endpoint", "endpoint detection and response"],
    "XDR": ["extended detection and response", "xdr", "xdr security"],
    "Zero Trust": ["architecture zero trust", "zero trust"],
    "MFA": ["2fa", "authentification a deux facteurs", "authentification multifacteur", "mfa"],
    "OAuth": ["oauth", "oauth 2.0", "oauth2"],
    "OpenID Connect": ["oidc", "openid connect"],
    "JWT": ["json web token", "jwt"],
    "TLS/SSL": ["certificat ssl", "certificat tls", "ssl", "tls", "tls/ssl"],
    "IDS/IPS": ["ids ips", "ids/ips", "intrusion detection system", "intrusion prevention system"],
    "Threat Intelligence": ["renseignement sur la menace", "threat intelligence"],
    "Red Team / Blue Team": ["blue team", "purple team", "red team", "red team / blue team"],
    "CTF": ["capture the flag", "ctf", "ctf hacking"],
    "CVE": ["common vulnerabilities and exposures", "cve"],
    "Bug Bounty": ["bug bounty"],
    "Firewall Palo Alto": ["firewall palo alto", "palo alto firewall", "palo alto networks"],
    "Fortinet": ["fortigate", "fortinet"],
    "Check Point": ["check point", "check point firewall", "checkpoint firewall"],
    "SD-WAN": ["sd-wan", "sdwan"],
    "CDN": ["cdn", "content delivery network", "reseau de diffusion de contenu"],
    "IPv6": ["ipv6"],
    # "Sketch" sans alias nu : "sketch" est aussi un mot francais courant
    # (sketch comique).
    "Sketch": ["sketch app design"],
    "Adobe XD": ["adobe xd"],
    "InVision": ["invision", "invision app"],
    "Arduino": ["arduino"],
    "Raspberry Pi": ["raspberry pi"],
    "RTOS": ["real time operating system", "rtos", "systeme d exploitation temps reel"],
    "MQTT": ["mqtt"],
    "IoT": ["internet of things", "iot", "objets connectes"],
    "Unity": ["unity", "unity 3d", "unity engine"],
    "Godot": ["godot", "godot engine"],
    "Design Patterns": ["design patterns", "patrons de conception"],
    # "SOLID" sans alias nu : "solid" est un mot anglais tres courant dans
    # les phrases de CV ("solid experience", "solid understanding of...").
    "SOLID": ["principes solid", "solid principles"],
    "Domain-Driven Design": ["ddd", "domain driven design", "domain-driven design"],
    "Event-Driven Architecture": ["architecture evenementielle", "event-driven architecture"],
    "Architecture Hexagonale": ["architecture hexagonale", "hexagonal architecture", "ports and adapters"],
    "CQRS": ["command query responsibility segregation", "cqrs"],
    "Clean Code": ["clean code", "code propre"],
    "Power Apps": ["microsoft power apps", "power apps"],
    "Bubble.io": ["bubble no-code", "bubble.io"],
    "Airtable": ["airtable"],
    "Zapier": ["zapier"],
    "Make (Integromat)": ["integromat", "make (integromat)", "make automation"],
    "Google Tag Manager": ["google tag manager", "gtm"],
    "SEO/SEA": ["ahrefs", "referencement payant", "semrush", "seo/sea"],
    "FFmpeg": ["ffmpeg"],
    "WebRTC": ["webrtc"],

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

    # ── MANAGEMENT (COMPLÉMENT 2026-09-17) : outils, méthodologies, ──────
    # gouvernance, certifications, leadership, entrepreneuriat. Même
    # discipline que le lot tech : pas d'alias nu risquant de collisionner
    # avec un mot francais/anglais ordinaire ou un prenom courant (ex:
    # "notion"/"miro"/"delegation" gardes uniquement sous forme qualifiee).
    "Trello": ["trello"],
    "Asana": ["asana"],
    "Monday.com": ["monday.com", "monday com"],
    "Microsoft Project": ["microsoft project", "ms project", "msproject"],
    "Smartsheet": ["smartsheet"],
    "Notion": ["notion app", "outil notion"],
    "ClickUp": ["clickup", "click up"],
    "Wrike": ["wrike"],
    "Basecamp": ["basecamp"],
    "OpenProject": ["openproject"],
    "Miro": ["miro board", "tableau miro"],
    "OKR": ["okr", "objectifs et resultats cles", "objectives and key results"],
    "Balanced Scorecard": ["balanced scorecard", "tableau de bord prospectif"],
    "Analyse SWOT": ["swot", "analyse swot", "forces faiblesses opportunites menaces"],
    "PESTEL": ["pestel", "analyse pestel"],
    "Business Model Canvas": ["business model canvas", "bmc"],
    "Value Proposition Canvas": ["value proposition canvas"],
    "Benchmarking": ["benchmarking", "benchmark concurrentiel"],
    "TQM": ["tqm", "total quality management", "management total de la qualite"],
    "5S": ["methode 5s", "5s lean"],
    "PDCA": ["pdca", "roue de deming", "plan do check act"],
    "TPM (maintenance)": ["total productive maintenance", "maintenance productive totale"],
    "Value Stream Mapping": ["value stream mapping", "cartographie des flux de valeur"],
    "Hoshin Kanri": ["hoshin kanri"],
    "Diagramme d'Ishikawa": ["ishikawa", "diagramme d ishikawa", "diagramme causes effets", "arete de poisson"],
    "COSO": ["coso", "cadre coso", "coso framework"],
    "ISO 31000": ["iso 31000"],
    "Due diligence": ["due diligence", "audit d acquisition"],
    "MBA": ["mba", "master of business administration"],
    "Executive MBA": ["executive mba", "emba"],
    "MSP (Managing Successful Programmes)": ["managing successful programmes"],
    "P3O": ["p3o"],
    "Gestion de programme": ["gestion de programme", "program management", "programme management"],
    "Gestion de portefeuille de projets": ["gestion de portefeuille de projets", "portfolio management"],
    "Comité de direction": ["comite de direction", "codir", "comex", "comite executif"],
    "Business Unit Management": ["business unit management", "gestion de business unit", "direction de business unit"],
    "Pilotage d'activité": ["pilotage d activite", "pilotage operationnel"],
    # "Fusions et acquisitions" existe deja (ROME) sous ce nom exact ; on
    # ajoute seulement les alias manquants sans creer de canonical rival.
    "Fusions et acquisitions": ["m&a", "mergers and acquisitions"],
    "Leadership transformationnel": ["leadership transformationnel", "transformational leadership"],
    "Leadership situationnel": ["leadership situationnel", "situational leadership"],
    "Servant Leadership": ["servant leadership", "leadership serviteur"],
    "Management bienveillant": ["management bienveillant", "management participatif"],
    "Gestion des fournisseurs": ["gestion des fournisseurs", "vendor management", "supplier management"],
    "Gestion des sous-traitants": ["gestion des sous-traitants", "management de sous-traitance"],
    "Gestion de contrats": ["gestion de contrats", "contract management", "suivi contractuel"],
    "Gestion du temps": ["gestion du temps", "time management"],
    "Priorisation": ["priorisation", "prioritization", "matrice d eisenhower"],
    "Prise de décision": ["prise de decision", "decision making", "aide a la decision"],
    "Délégation": ["delegation de taches", "delegation d equipe"],
    "Entrepreneuriat": ["entrepreneuriat", "creation d entreprise", "esprit entrepreneurial"],
    "Intrapreneuriat": ["intrapreneuriat", "intrapreneur"],
    "Business Plan": ["business plan", "plan d affaires"],
    "Levée de fonds": ["levee de fonds", "fundraising", "capital-risque", "venture capital"],

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

    # ── COMMERCIAL (COMPLÉMENT 2026-09-17) ───────────────────────────────
    "SPIN Selling": ["spin selling", "methode spin"],
    "Challenger Sale": ["challenger sale", "vente challenger"],
    "Solution Selling": ["solution selling", "vente de solutions"],
    "Social Selling": ["social selling", "vente sociale"],
    "Vente à distance": ["vente a distance", "televente"],
    "Techniques de closing": ["closing commercial", "techniques de closing"],
    "Vente export": ["vente export", "export sales", "developpement export"],
    "Sales Navigator": ["sales navigator", "linkedin sales navigator"],
    "Gestion de rayon": ["gestion de rayon", "chef de rayon"],

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

    # ── MARKETING (COMPLÉMENT 2026-09-17) ────────────────────────────────
    # "Marketo" existe deja (ONET) ; on n'y touche pas.
    "Growth Marketing": ["growth marketing", "growth hacking"],
    "Marketing Automation": ["marketing automation", "pardot", "activecampaign"],
    "Études de marché": ["etudes de marche", "market research", "etude marketing"],
    "Marketing produit": ["marketing produit", "product marketing"],
    "Influence Marketing": ["influence marketing", "marketing d influence", "influenceurs"],
    "Publicité": ["publicite", "advertising", "creation publicitaire", "campagne publicitaire"],
    "Marketing mix": ["marketing mix", "4p marketing"],
    "Persona marketing": ["persona marketing", "buyer persona"],
    "A/B Testing": ["a/b testing", "ab testing", "tests ab"],
    "Marketing international": ["marketing international"],
    "Storytelling": ["storytelling", "narration de marque", "brand storytelling"],
    "UGC (contenu généré par les utilisateurs)": ["ugc", "contenu genere par les utilisateurs", "user generated content"],

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

    # ── FINANCE (COMPLÉMENT 2026-09-17) ──────────────────────────────────
    "Finance de marché": ["finance de marche", "capital markets", "salle des marches"],
    "Trading algorithmique": ["trading algorithmique", "algo trading", "high frequency trading"],
    "Gestion de patrimoine": ["gestion de patrimoine", "wealth management", "conseiller en gestion de patrimoine", "cgp"],
    # "Gestion d’actifs" (apostrophe typographique) existe deja via ROME ;
    # on rejoint EXACTEMENT ce canonical (meme chaine) pour ajouter le seul
    # alias manquant, plutot que de creer un canonical rival avec une
    # apostrophe droite.
    "Gestion d’actifs": ["gestionnaire de portefeuille"],
    # Idem pour "Finance d'entreprise" (apostrophe droite, deja via ROME).
    "Finance d'entreprise": ["corporate finance"],
    "Capital investissement": ["capital investissement", "private equity", "capital developpement"],
    "Bâle III": ["bale 3", "bale iii", "basel iii"],
    "Solvabilité II": ["solvabilite 2", "solvabilite ii", "solvency ii"],
    # "KYC" existe deja (ROME) ; on n'y touche pas et on cree seulement le
    # volet AML, non couvert.
    "Lutte anti-blanchiment (AML)": ["aml", "anti money laundering", "lutte anti-blanchiment"],
    "Crédit bancaire": ["credit bancaire", "analyse credit", "risque de credit", "octroi de credit"],
    "Middle Office": ["middle office"],
    "Back Office bancaire": ["back office bancaire", "back office titres"],
    "Front Office": ["front office"],
    "Valorisation d'entreprise": ["valorisation d entreprise", "evaluation d entreprise", "dcf valorisation"],
    "Modélisation financière": ["modelisation financiere", "financial modeling", "excel financier"],
    "Bloomberg Terminal": ["bloomberg terminal"],
    "Reuters Eikon": ["reuters eikon", "refinitiv eikon"],
    "Microfinance": ["microfinance", "institution de microfinance"],
    "Financement de projet": ["financement de projet", "project finance"],
    "Titrisation": ["titrisation", "securitization"],
    "Marchés obligataires": ["marches obligataires", "marche obligataire", "bond market"],
    "Produits dérivés": ["produits derives", "options et futures"],
    "Change (Forex)": ["forex", "marche des changes", "trading de devises"],
    "SWIFT (messagerie bancaire)": ["message swift", "systeme swift", "swift banking"],

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

    # ── RH (COMPLÉMENT 2026-09-17) ───────────────────────────────────────
    "Marque employeur": ["marque employeur", "employer branding"],
    "HRBP (HR Business Partner)": ["hrbp", "hr business partner", "rh de proximite"],
    "Mobilité interne": ["mobilite interne", "gestion de carriere"],
    "Entretien annuel": ["entretien annuel", "entretien d evaluation", "entretien professionnel"],
    "Diversité et inclusion": ["diversite et inclusion", "politique handicap en entreprise"],
    "Rémunération et avantages sociaux": ["remuneration et avantages sociaux", "compensation and benefits"],
    "Digitalisation RH": ["digitalisation rh", "digital hr"],
    "Entretien de recrutement": ["entretien de recrutement", "entretien d embauche"],
    "LinkedIn Recruiter": ["linkedin recruiter"],
    "ATS (Applicant Tracking System)": ["ats recrutement", "applicant tracking system", "logiciel de recrutement"],
    "Bilan de compétences": ["bilan de competences", "bilan professionnel"],

    # ── DROIT & JURIDIQUE ─────────────────────────────────────────────────
    "Droit des contrats": ["droit des contrats", "contract law", "redaction de contrats", "droit contractuel"],
    "Droit des affaires": ["droit des affaires", "business law", "droit commercial", "droit des societes"],
    "Propriété intellectuelle": ["propriete intellectuelle", "pi", "brevets", "marques", "droits d auteur", "pi"],
    "Droit public": ["droit public", "droit administratif", "droit constitutionnel", "droit de la commande publique"],
    "Compliance": ["compliance", "conformite", "conformite reglementaire", "projet reglementaire", "rgpd", "gdpr", "lcb ft"],
    "Contentieux": ["contentieux", "procedure judiciaire", "litige", "plaidoirie"],
    "Droit pénal": ["droit penal", "droit criminel", "procedure penale"],
    "Droit immobilier": ["droit immobilier", "droit de l urbanisme", "droit de la construction"],

    # ── LÉGAL (COMPLÉMENT 2026-09-17) ────────────────────────────────────
    "Droit international": ["droit international", "droit international prive", "droit international public"],
    # Bare "arbitrage" exclu : mot francais courant signifiant aussi
    # "compromis/choix" hors contexte juridique (ex: "faire un arbitrage
    # entre deux options").
    "Arbitrage juridique": ["arbitrage juridique", "arbitrage commercial", "procedure d arbitrage"],
    "Notariat": ["notariat", "notaire", "acte notarie"],
    "Rédaction juridique": ["redaction juridique", "legal drafting", "redaction d actes"],
    "Veille juridique": ["veille juridique", "legal watch"],
    "Droit de la concurrence": ["droit de la concurrence", "droit antitrust"],
    "Droit bancaire et financier": ["droit bancaire", "droit financier"],
    "Legal Tech": ["legal tech", "legaltech"],
    "Juriste d'entreprise": ["juriste d entreprise", "in-house counsel", "corporate counsel"],

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
    # "declaration de sinistre" added: a real production CV read exactly
    # this (singular, verb "declarer" not "gerer") and matched nothing at
    # all despite being squarely claims-handling experience -- find_skills()
    # does exact n-gram lookup with no stemming, so plural-only coverage
    # ("sinistres") silently missed this common singular phrasing. The bare
    # singular word "sinistre" alone is deliberately NOT added here (see
    # test_deliberately_excluded_terms_stay_unresolved) -- unlike the
    # 3-word phrase, it collides with the far more common everyday French
    # adjective meaning "sinister/grim", which this exact multi-word
    # context doesn't share. "indemnisation" is added too: the
    # insurance-industry term for claims compensation/payout, and in a
    # real "Chef de Projet MOA - Indemnisation IARD" job posting, literally
    # the job's own domain name -- yet had no taxonomy entry of any kind
    # before this, so it never counted as a real, demonstrated skill for a
    # candidate whose CV used the same industry-standard word.
    "Gestion des sinistres": ["gestion des sinistres", "gestion de sinistre", "sinistres",
                              "declaration de sinistre", "indemnisation",
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

    # ── LOGISTIQUE (COMPLÉMENT 2026-09-17) ───────────────────────────────
    "Gestion de flotte": ["gestion de flotte", "fleet management", "gestionnaire de flotte"],
    "Transport routier": ["transport routier", "affretement routier"],
    "Transport maritime": ["transport maritime", "fret maritime", "shipping maritime"],
    "Transport aérien": ["transport aerien", "fret aerien", "air freight"],
    "Logistique internationale": ["logistique internationale", "chaine logistique internationale"],
    "Cross-docking": ["cross-docking", "cross docking"],
    "Gestion des flux": ["gestion des flux", "flux tendus", "juste a temps", "just in time"],
    "Préparation de commandes": ["preparation de commandes", "picking entrepot", "order picking"],
    "Traçabilité logistique": ["tracabilite logistique", "suivi de tracabilite"],
    "Logistique inverse": ["reverse logistics", "logistique inverse", "gestion des retours"],
    "CACES (chariot élévateur)": ["caces", "chariot elevateur", "conduite de chariot"],
    "Transitaire": ["transitaire", "commissionnaire de transport"],

    # ── SANTÉ & MÉDICAL ───────────────────────────────────────────────────
    # "ide" (Infirmier Diplome d'Etat) deliberately NOT included as a bare
    # alias: real bug found via testing (2026-09-17) while validating the
    # O*NET import -- "ide" collides with the extremely common tech
    # abbreviation IDE (Integrated Development Environment, "Eclipse IDE",
    # "un bon IDE"...), which this dictionary now covers extensively. A
    # real nurse's CV says "infirmier"/"soins infirmiers" or spells out
    # "IDE" with surrounding context far more often than the bare
    # 3-letter form alone.
    "Soins infirmiers": ["soins infirmiers", "infirmier", "nursing", "soins aux patients"],
    "Pharmacologie": ["pharmacologie", "pharmacie", "medicaments", "dispensation", "pharmacien"],
    "Soins d'urgence": ["urgences", "soins d urgence", "smur", "reanimation", "samu"],
    "Bloc opératoire": ["bloc operatoire", "chirurgie", "instrumentiste", "aide soignant", "ibode"],
    "Médecine générale": ["medecine generale", "omnipraticien", "consultation medicale", "medecin"],
    "Radiologie": ["radiologie", "imagerie medicale", "echographie", "scanner", "irm", "manipulateur"],
    "Kinésithérapie": ["kinesitherapie", "kinesitherapeute", "reeducation", "physiotherapie", "mkde"],
    "Psychologie": ["psychologie", "psychologue", "psychotherapie", "counseling", "therapie"],
    "Nutrition": ["nutrition", "dietetique", "dieteticien", "dietetiste"],
    "Hygiène hospitalière": ["hygiene hospitaliere", "bio-nettoyage", "asepsie", "sterilisation"],

    # ── SANTÉ (COMPLÉMENT 2026-09-17) ────────────────────────────────────
    # "Odontologie"/"Orthodontie" existent deja (ROME/ESCO) ; on y ajoute
    # seulement les alias manquants plutot que de creer un "Dentisterie"
    # rival.
    "Odontologie": ["chirurgien-dentiste", "soins dentaires"],
    "Médecine vétérinaire": ["medecine veterinaire", "veterinaire", "soins animaliers"],
    "Analyses de laboratoire": ["analyses de laboratoire", "laboratoire d analyses medicales"],
    # "Santé publique"/"Gériatrie" ci-dessous rejoignent des canonicals ROME
    # deja identiques (meme chaine) ; "epidemiologie"/"gerontologie" deja
    # couverts separement donc omis ici.
    "Santé publique": ["promotion de la sante"],
    "Gestion hospitalière": ["gestion hospitaliere", "administration hospitaliere"],
    "Aide à domicile": ["aide a domicile", "auxiliaire de vie", "aide medico-psychologique"],
    "Dispositifs médicaux": ["dispositifs medicaux", "materiel medical"],
    "Télémédecine": ["telemedecine", "telesante", "teleconsultation"],
    "Gériatrie": ["soins aux personnes agees", "ehpad"],
    "Pédiatrie": ["pediatrie", "soins pediatriques"],
    "Sécurité sociale": ["securite sociale", "assurance maladie", "cpam", "protection sociale"],
    "Orthophonie": ["orthophonie", "orthophoniste", "reeducation du langage"],
    "Ergothérapie": ["ergotherapie", "ergotherapeute"],
    "Sage-femme": ["sage-femme", "maieutique", "obstetrique"],

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

    # ── CONSTRUCTION (COMPLÉMENT 2026-09-17) ─────────────────────────────
    # "Second oeuvre" et "Economie de la construction" existent deja
    # (ROME) sous une orthographe legerement differente (oe vs œ, sans
    # accent vs avec) mais un fold identique ; pas de nouvel alias a
    # ajouter, donc pas d'entree ici pour eviter un canonical rival.
    "VRD (Voirie et Réseaux Divers)": ["vrd", "voirie et reseaux divers"],
    "Permis de construire": ["permis de construire", "dossier de permis", "autorisation d urbanisme"],
    "RE2020 / Réglementation thermique": ["re2020", "rt2012", "reglementation thermique batiment"],
    "Matériaux de construction": ["materiaux de construction", "materiaux batiment"],
    "Engins de chantier": ["engins de chantier", "conduite d engins", "pelleteuse"],
    "Diagnostic immobilier": ["diagnostic immobilier", "dpe immobilier"],
    "Economiste de la construction": ["economiste de la construction"],
    "Coordination SPS": ["coordination sps", "coordinateur sps"],
    "Topographie": ["topographie", "geometre", "leve topographique"],
    "Urbanisme": ["urbanisme", "amenagement du territoire", "plan local d urbanisme"],

    # ── ÉDUCATION & FORMATION ─────────────────────────────────────────────
    "Pédagogie": ["pedagogie", "pedagogy", "methodes pedagogiques", "ingenierie pedagogique"],
    "E-learning": ["e-learning", "formation en ligne", "enseignement a distance", "mooc", "lms"],
    "Conception pédagogique": ["conception pedagogique", "instructional design", "design pedagogique", "ingenierie de formation"],
    "Tutorat": ["tutorat", "tutoring", "soutien scolaire", "accompagnement scolaire", "tuteur"],
    "Mathématiques": ["mathematiques", "maths", "mathematics", "statistiques appliquees"],

    # ── ÉDUCATION (COMPLÉMENT 2026-09-17) ────────────────────────────────
    "Andragogie": ["andragogie", "adult learning"],
    "Différenciation pédagogique": ["differenciation pedagogique", "pedagogie differenciee"],
    "Classe inversée": ["classe inversee", "flipped classroom"],
    "Évaluation des apprentissages": ["evaluation des apprentissages", "evaluation formative", "evaluation sommative"],
    "Moodle": ["moodle"],
    "Google Classroom": ["google classroom"],
    "Canvas LMS": ["canvas lms"],
    "Blackboard": ["blackboard lms"],
    "Formateur d'adultes": ["formateur d adultes", "formateur professionnel"],
    "Orientation scolaire et professionnelle": ["orientation scolaire", "orientation professionnelle", "conseiller d orientation"],
    "Direction d'établissement scolaire": ["direction d etablissement", "chef d etablissement", "proviseur", "principal de college"],
    "Vie scolaire": ["vie scolaire", "conseiller principal d education", "cpe"],
    "FLE (Français Langue Étrangère)": ["fle", "francais langue etrangere"],
    "Didactique": ["didactique", "didactique des disciplines"],
    "Recherche académique": ["recherche academique", "publication scientifique", "travaux de recherche", "these de doctorat"],
    "Rédaction de mémoire": ["redaction de memoire", "memoire de recherche"],
    "Bibliothéconomie": ["bibliotheconomie", "documentaliste", "sciences de l information"],
    "Petite enfance": ["petite enfance", "eveil de l enfant", "auxiliaire de puericulture"],
    "Apprentissage par projet": ["apprentissage par projet", "project-based learning", "pedagogie de projet"],
    "Gamification pédagogique": ["gamification pedagogique", "ludopedagogie", "serious game"],

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

    # ── GÉNÉRAL / TRANSVERSAL (COMPLÉMENT 2026-09-17) ────────────────────
    "Multilinguisme": ["multilinguisme", "bilingue", "trilingue", "multilingual"],
    # Bare "responsabilite" exclu : trop generique, collisionne avec les
    # en-tetes de section de CV ("Responsabilites : ...") sans indiquer une
    # competence demontree.
    "Sens des responsabilités": ["sens des responsabilites", "sens du devoir"],
    "Curiosité intellectuelle": ["curiosite intellectuelle", "curiosite professionnelle"],
    "Esprit critique": ["esprit critique", "pensee critique", "critical thinking"],
    "Capacité d'apprentissage": ["capacite d apprentissage", "apprentissage continu", "learning agility"],
    "Orientation résultats": ["orientation resultats", "orientation performance"],
    "Discrétion professionnelle": ["discretion professionnelle", "devoir de reserve"],
    "Empathie": ["empathie", "ecoute empathique"],
    # "Ethique professionnelle" (sans accent) existe deja (ROME) sous ce
    # nom exact ; on y ajoute seulement les alias manquants.
    "Ethique professionnelle": ["deontologie professionnelle", "integrite professionnelle"],

    # ── COMPLÉMENT ISSU DE 67 OFFRES D'EMPLOI RÉELLES (2026-09-17) ──────
    # Extrait de mod326_js_job_jobs.json (export production, offres ESN
    # tech/finance/telecom réelles). Deux volets : des competences totalement
    # absentes de la taxonomie (nouveaux outils/reglementations), et des
    # competences deja reconnues via ROME/ESCO/O*NET/e-CF mais promues ici
    # dans le dictionnaire de confiance manuel.
    "FinOps": ["finops", "gouvernance financiere cloud"],
    "SEFAS HCS": ["sefas hcs", "suite sefas", "sefas v6"],
    "ATEM MDM": ["atem mdm", "outil atem"],
    "Nutanix": ["nutanix", "nutanix ahv", "cluster nutanix"],
    "Quarkus": ["quarkus"],
    "MicroStrategy": ["microstrategy", "micro strategy"],
    "XL Release / XL Deploy": ["xl release", "xl deploy", "xldeploy", "xlr", "xld"],
    "Xray (gestion de tests Jira)": ["jira xray", "xray test management"],
    "LPM (Loi de Programmation Militaire)": ["lpm"],
    "DSP2 (PSD2)": ["dsp2", "psd2", "payment services directive"],
    "Planon": ["planon", "planon software"],
    "Dynatrace": ["dynatrace"],
    # Note : "MCO" est aussi l'acronyme hospitalier "Medecine-Chirurgie-
    # Obstetrique" (service/pole MCO) -- collision mineure acceptee (le
    # domaine sante ne represente que 0.5% du corpus de validation).
    "MCO (Maintien en Condition Opérationnelle)": ["mco", "maintien en condition operationnelle"],
    "IMS DL/1": ["dl1", "ims dl/1", "ims db"],

    # Promotions depuis ROME/ESCO/O*NET/e-CF (memes noms canoniques exacts) :
    "Amazon EC2": ["amazon ec2"],
    "Amélioration des processus": ["amelioration des processus"],
    "Analysis Services": ["analysis services"],
    "Anglais professionnel": ["anglais professionnel"],
    "Apache": ["apache"],
    "Apache Cassandra": ["apache cassandra"],
    "Apache Hadoop": ["apache hadoop"],
    "Apache Hive": ["apache hive"],
    "Apache Spark": ["apache spark"],
    "Big Data": ["big data"],
    "Conception des applications": ["conception des applications"],
    "Concepts des télécommunications": ["concepts des telecommunications"],
    "Documentation technique": ["documentation technique"],
    "Données non structurées": ["donnees non structurees"],
    "Gestion de bases de données": ["gestion de bases de donnees"],
    "Gestion de projets": ["gestion de projets"],
    "Gestion des actifs": ["gestion des actifs"],
    "Gestion des coûts": ["gestion des couts"],
    "Gestion des incidents": ["gestion des incidents"],
    "Gestion des problèmes": ["gestion des problemes"],
    "Gestion des ressources": ["gestion des ressources"],
    "Gestion du changement": ["gestion du changement"],
    "Gestion financière": ["gestion financiere"],
    "Google Android": ["google android"],
    "Groovy": ["groovy"],
    "Hadoop": ["hadoop"],
    "Hibernate ORM": ["hibernate orm"],
    "IOS": ["ios"],
    "Intégration de systèmes": ["integration de systemes"],
    "MDX": ["mdx"],
    "Marketing numérique": ["marketing numerique"],
    "Micro-informatique": ["micro-informatique"],
    "Modèles de données": ["modeles de donnees"],
    "Modélisation orientée services": ["modelisation orientee services"],
    "Métrologie": ["metrologie"],
    "NoSQL": ["nosql"],
    "Normes de sécurité": ["normes de securite"],
    "OpenShift": ["openshift"],
    "Perl": ["perl"],
    "Portugais": ["portugais"],
    "Postman": ["postman"],
    "PowerShell": ["powershell"],
    "Procédures de sauvegarde des données": ["procedures de sauvegarde des donnees"],
    "Protection des données": ["protection des donnees"],
    "Routage": ["routage"],
    "Règles de sécurité": ["regles de securite"],
    "SharePoint": ["sharepoint"],
    "Spring Framework": ["spring framework"],
    "Stockage de données": ["stockage de donnees"],
    "Suivi de projet": ["suivi de projet"],
    "Sybase": ["sybase"],
    "Systèmes d'information": ["systemes d'information"],
    "Systèmes d’exploitation": ["systemes dexploitation"],
    "Sécurité des systèmes d'information": ["securite des systemes d'information"],
    "Techniques comptables": ["techniques comptables"],
    "Technologies de dématérialisation": ["technologies de dematerialisation"],
    "UNIX Shell": ["unix shell"],
    "Veille technologique": ["veille technologique"],
    "Windows Server": ["windows server"],
    "XML": ["xml"],
    "WildFly": ["jboss"],
    "Transact-SQL": ["transact sql"],
    "Base de données": ["entrepot de donnees"],

    # ── COMPLÉMENT ISSU DE 33 574 PROFILS CANDIDATS RÉELS (2026-09-17) ──
    # Extrait des champs "keywords"/"skills" de mod326_js_job_resume.json
    # (export production, mots-cles auto-declares par les candidats).
    # Promotions depuis ROME/ESCO/O*NET/e-CF vers le dictionnaire de confiance
    # manuel (memes noms canoniques exacts, pas de canonical rival cree).
    # Mots generiques a risque (Architecture/Cycle/marketing/Logistique/
    # Statistiques/Francais/Technologie/Ecosystemes/Prevention) deliberement
    # laisses hors de ce niveau, meme piege que Chef/SAS trouve plus tot.
    # "Projet social" trouve et exclu au niveau ROME (voir
    # _ROME_ALIAS_STOPWORDS) : collision avec "Chef de projet social media".
    "Alteryx": ["alteryx"],
    "Amazon DynamoDB": ["amazon dynamodb"],
    "Amazon Redshift": ["amazon redshift"],
    "Apache Airflow": ["apache airflow"],
    "Apache Tomcat": ["apache tomcat"],
    "Apple macOS": ["apple macos"],
    "Application web": ["application web"],
    "ArcGIS": ["arcgis"],
    "Asset management": ["asset management"],
    "Automatisme": ["automatisme"],
    "BGP": ["bgp"],
    "Cisco Webex": ["cisco webex"],
    "Cobol": ["cobol"],
    "Cognos": ["cognos"],
    "Cryptomonnaie": ["cryptomonnaie"],
    "Drupal": ["drupal"],
    "Développement de logiciels": ["developpement de logiciels"],
    "E-commerce": ["e-commerce"],
    "Electromagnétisme": ["electromagnetisme"],
    "Electronique": ["electronique"],
    "Fortran": ["fortran"],
    "GRH": ["grh"],
    "Gestion de crise": ["gestion de crise"],
    "Gestion des services informatiques": ["gestion des services informatiques"],
    "Graphiques animés": ["graphiques animes"],
    "Génie logiciel": ["genie logiciel"],
    "Infographie": ["infographie"],
    "Informatique industrielle": ["informatique industrielle"],
    "Intelligence artificielle": ["intelligence artificielle"],
    "JQuery": ["jquery"],
    "Knowledge Management": ["knowledge management"],
    "MATLAB": ["matlab"],
    "Maintenance prédictive": ["maintenance predictive"],
    "Maltego": ["maltego"],
    "Marketing relationnel": ["marketing relationnel"],
    "Maîtrise de la langue française": ["maitrise de la langue francaise"],
    "Microprogramme": ["microprogramme"],
    "Microsoft Active Directory": ["microsoft active directory"],
    "Microsoft Outlook": ["microsoft outlook"],
    "Microsoft Teams": ["microsoft teams"],
    "Modélisation orientée objet": ["modelisation orientee objet"],
    "Monétique": ["monetique"],
    "Nessus": ["nessus"],
    "Oracle Cloud": ["oracle cloud"],
    "Power Platform": ["power platform"],
    "Puppet": ["puppet"],
    "RACI": ["raci"],
    "Red Hat Enterprise Linux": ["red hat enterprise linux"],
    "Responsive design": ["responsive design"],
    "Risques technologiques": ["risques technologiques"],
    "Rédaction de cahier des charges": ["redaction de cahier des charges"],
    "Rétro-ingénierie": ["retro-ingenierie"],
    "SAP Concur": ["sap concur"],
    "Script Shell": ["script shell"],
    "Service clients": ["service clients"],
    "Slack": ["slack"],
    "SoapUI": ["soapui"],
    "Splunk": ["splunk"],
    "Systèmes embarqués": ["systemes embarques"],
    "Sécurité des applications": ["securite des applications"],
    "Sécurité des réseaux": ["securite des reseaux"],
    "TensorFlow": ["tensorflow"],
    "Tests fonctionnels": ["tests fonctionnels"],
    "Tests utilisateurs": ["tests utilisateurs"],
    "Traitement du signal": ["traitement du signal"],
    "Wireshark": ["wireshark"],

    # ── COMPLÉMENT ISSU DU CORPUS COMPLET DE 13 618 CV RÉELS (2026-09-18) ──
    # Scan find_skills() sur le texte brut extrait des 13 715 CV de production
    # (pas un echantillon) : 1438 competences deja reconnues via ROME/ESCO/
    # O*NET/e-CF mais absentes du dictionnaire manuel. 1278 promues ici avec
    # leur nom canonique exact (verifie contre _build_lookup() pour eviter tout
    # canonical rival) ; 147 mots generiques/ambigus exclus (meme discipline
    # que Chef/SAS/Architecture/Cycle plus tot dans la session -- sports/loisirs,
    # noms de secteur/produit, mots polysemiques) et 13 abandonnes car leur
    # propre nom resolvait deja vers un autre canonical existant (Jenkins->
    # CI/CD, PowerPoint->Presentation, etc.). Revue complete dans
    # full_corpus_gap_fill_summary.txt (scratchpad de session, non commite).
    ".NET Framework": [".net framework"],
    "3DS MAX": ["3ds max"],
    "ABAP": ["abap"],
    "ADSL": ["adsl"],
    "AJAX": ["ajax"],
    "APL": ["apl"],
    "AWS CloudFormation": ["aws cloudformation"],
    "Accidentologie": ["accidentologie"],
    "Accouchement": ["accouchement"],
    "Accueil des patients": ["accueil des patients"],
    "Accueil et conseil des clients": ["accueil et conseil des clients"],
    "Accueil physique et téléphonique": ["accueil physique et telephonique"],
    "Achat médias": ["achat medias"],
    "Acoustique": ["acoustique"],
    "Actifs financiers": ["actifs financiers"],
    "Activités bancaires": ["activites bancaires"],
    "Activités de vente": ["activites de vente"],
    "Adaptation aux nouvelles technologies": ["adaptation aux nouvelles technologies"],
    "Adaptation aux évolutions technologiques": ["adaptation aux evolutions technologiques"],
    "Administration centrale": ["administration centrale"],
    "Administration de bases de données": ["administration de bases de donnees"],
    "Administration de pare-feu": ["administration de pare-feu"],
    "Administration de réseaux": ["administration de reseaux"],
    "Administration de serveurs web": ["administration de serveurs web"],
    "Administration publique": ["administration publique"],
    "Adobe Acrobat": ["adobe acrobat"],
    "Adobe After Effects": ["adobe after effects"],
    "Adobe Illustrator": ["adobe illustrator"],
    "Adobe Photoshop Lightroom": ["adobe photoshop lightroom"],
    "Adobe Première Pro": ["adobe premiere pro"],
    "Adobe creative suite": ["adobe creative suite"],
    "Affaires étrangères": ["affaires etrangeres"],
    "Affirmation de soi": ["affirmation de soi"],
    "After Effects": ["after effects"],
    "Agriculture biologique": ["agriculture biologique"],
    "Agriculture numérique": ["agriculture numerique"],
    "Agroforesterie": ["agroforesterie"],
    "Agronomie": ["agronomie"],
    "Aide humanitaire": ["aide humanitaire"],
    "Aides auditives": ["aides auditives"],
    "Ajax Framework": ["ajax framework"],
    "Albanais": ["albanais"],
    "Algorithmique": ["algorithmique"],
    "Algèbre": ["algebre"],
    "Algèbre linéaire": ["algebre lineaire"],
    "Alkylation": ["alkylation"],
    "Allemand": ["allemand"],
    "Amortissement": ["amortissement"],
    "Aménagement d'espaces intérieurs": ["amenagement d'espaces interieurs"],
    "Aménagement urbain": ["amenagement urbain"],
    "Analyse commerciale": ["analyse commerciale"],
    "Analyse de données": ["analyse de donnees"],
    "Analyse de marché": ["analyse de marche"],
    "Analyse des entreprises": ["analyse des entreprises"],
    "Analyse fondamentale": ["analyse fondamentale"],
    "Analyse marketing": ["analyse marketing"],
    "Analyse quantitative": ["analyse quantitative"],
    "Anesthésie-réanimation": ["anesthesie-reanimation"],
    "Anglais des affaires": ["anglais des affaires"],
    "Anglais niveau avancé B2": ["anglais niveau avance b2"],
    "Anglais technique": ["anglais technique"],
    "Anglais universitaire": ["anglais universitaire"],
    "Animation de sessions de formation": ["animation de sessions de formation"],
    "Animation vectorielle": ["animation vectorielle"],
    "Anthropologie": ["anthropologie"],
    "Apache Maven": ["apache maven"],
    "Apple Safari": ["apple safari"],
    "Aptitude à travailler sous pression": ["aptitude a travailler sous pression"],
    "Arabe": ["arabe"],
    "Architecture d'intérieur": ["architecture d'interieur"],
    "Architecture de l’information": ["architecture de linformation"],
    "Architecture des systèmes d'information": ["architecture des systemes d'information"],
    "Architecture réseau": ["architecture reseau"],
    "Architecture web": ["architecture web"],
    "Architectures matérielles": ["architectures materielles"],
    "Archivage électronique des documents": ["archivage electronique des documents"],
    "Archéologie": ["archeologie"],
    "Archéologie préventive": ["archeologie preventive"],
    "Argumentaire de vente": ["argumentaire de vente"],
    "Argumentation commerciale": ["argumentation commerciale"],
    "Arménien": ["armenien"],
    "Aromathérapie": ["aromatherapie"],
    "Arts appliqués": ["arts appliques"],
    "Arts numériques": ["arts numeriques"],
    "Assembleur": ["assembleur"],
    "Assistance commerciale": ["assistance commerciale"],
    "Astrologie": ["astrologie"],
    "Astronomie": ["astronomie"],
    "Audiologie": ["audiologie"],
    "AutoCAD Civil 3D": ["autocad civil 3d"],
    "Autodesk Revit": ["autodesk revit"],
    "Automate programmable": ["automate programmable"],
    "Autopartage": ["autopartage"],
    "Azéri": ["azeri"],
    "Aéraulique": ["aeraulique"],
    "Aérodynamique": ["aerodynamique"],
    "Bactériologie": ["bacteriologie"],
    "Banque d’investissement": ["banque dinvestissement"],
    "Basque": ["basque"],
    "Beaux-arts": ["beaux-arts"],
    "Bengali": ["bengali"],
    "Bentley MicroStation": ["bentley microstation"],
    "Berbère": ["berbere"],
    "Bien-être animal": ["bien-etre animal"],
    "Biochimie": ["biochimie"],
    "Biodiesel": ["biodiesel"],
    "Biologie": ["biologie"],
    "Biologie cellulaire": ["biologie cellulaire"],
    "Biologie de la peau": ["biologie de la peau"],
    "Biologie des organismes": ["biologie des organismes"],
    "Biologie moléculaire": ["biologie moleculaire"],
    "Biologie médicale": ["biologie medicale"],
    "Biomarqueurs": ["biomarqueurs"],
    "Biomécanique": ["biomecanique"],
    "Biomédecine": ["biomedecine"],
    "Biométrie": ["biometrie"],
    "Biophysique": ["biophysique"],
    "Biostatistique": ["biostatistique"],
    "Biosécurité": ["biosecurite"],
    "Biotechnologie": ["biotechnologie"],
    "Biotechnologies": ["biotechnologies"],
    "Bioéconomie": ["bioeconomie"],
    "Biélorusse": ["bielorusse"],
    "BlackBerry": ["blackberry"],
    "Blender": ["blender"],
    "Bosnien": ["bosnien"],
    "Botanique": ["botanique"],
    "Braille": ["braille"],
    "Bulgare": ["bulgare"],
    "Business Objects Designer": ["business objects designer"],
    "Cadencier": ["cadencier"],
    "Calcul différentiel": ["calcul differentiel"],
    "Calcul distribué": ["calcul distribue"],
    "Calcul intégral": ["calcul integral"],
    "Calculs financiers": ["calculs financiers"],
    "Cancérologie": ["cancerologie"],
    "Capacité financière": ["capacite financiere"],
    "Capacité à travailler sous pression": ["capacite a travailler sous pression"],
    "Capteurs": ["capteurs"],
    "Capture One": ["capture one"],
    "Capture de mouvement": ["capture de mouvement"],
    "Caractéristiques des produits": ["caracteristiques des produits"],
    "Cardiologie": ["cardiologie"],
    "Cartographie numérique": ["cartographie numerique"],
    "Cash Pooling": ["cash pooling"],
    "Catalan": ["catalan"],
    "Cellules souches": ["cellules souches"],
    "Chaîne du froid": ["chaine du froid"],
    "Chaîne graphique": ["chaine graphique"],
    "Chiffrage projet": ["chiffrage projet"],
    "Chimie": ["chimie"],
    "Chimie analytique": ["chimie analytique"],
    "Chimie computationnelle": ["chimie computationnelle"],
    "Chimie des matériaux": ["chimie des materiaux"],
    "Chimie des polymères": ["chimie des polymeres"],
    "Chimie inorganique": ["chimie inorganique"],
    "Chimie moléculaire": ["chimie moleculaire"],
    "Chimie organique": ["chimie organique"],
    "Chimie verte": ["chimie verte"],
    "Chinois": ["chinois"],
    "Chorus": ["chorus"],
    "Cinéma 4D": ["cinema 4d"],
    "Cinématique": ["cinematique"],
    "Cinématographie": ["cinematographie"],
    "Cinétique": ["cinetique"],
    "Circuit du médicament": ["circuit du medicament"],
    "Circuits hydrauliques": ["circuits hydrauliques"],
    "Circuits imprimés": ["circuits imprimes"],
    "Circuits intégrés": ["circuits integres"],
    "Circuits électriques": ["circuits electriques"],
    "Circuits électroniques": ["circuits electroniques"],
    "Climatologie": ["climatologie"],
    "Clonezilla": ["clonezilla"],
    "Code de la route": ["code de la route"],
    "Code des marchés publics": ["code des marches publics"],
    "CoffeeScript": ["coffeescript"],
    "Cogénération": ["cogeneration"],
    "Coiffure": ["coiffure"],
    "Collecte de fonds": ["collecte de fonds"],
    "Coloration capillaire": ["coloration capillaire"],
    "Colorimétrie": ["colorimetrie"],
    "Commerce international": ["commerce international"],
    "Communication des entreprises": ["communication des entreprises"],
    "Communication électronique": ["communication electronique"],
    "Composants d’éclairage LED": ["composants declairage led"],
    "Composants matériels": ["composants materiels"],
    "Composants électroniques": ["composants electroniques"],
    "Compréhension des besoins clients": ["comprehension des besoins clients"],
    "Compétences interculturelles": ["competences interculturelles"],
    "Conception architecturale": ["conception architecturale"],
    "Conception créative": ["conception creative"],
    "Conception d'architectures logicielles": ["conception d'architectures logicielles"],
    "Conception de bases de données": ["conception de bases de donnees"],
    "Conception de batteries": ["conception de batteries"],
    "Conception de cahiers des charges": ["conception de cahiers des charges"],
    "Conception de l'architecture": ["conception de l'architecture"],
    "Conception de programmes de formation": ["conception de programmes de formation"],
    "Conception de sites web": ["conception de sites web"],
    "Conception de systèmes informatiques": ["conception de systemes informatiques"],
    "Conception de systèmes intégrés": ["conception de systemes integres"],
    "Conception des systèmes": ["conception des systemes"],
    "Conception et développement d'applications": ["conception et developpement d'applications"],
    "Conception graphique": ["conception graphique"],
    "Conception intégrée": ["conception integree"],
    "Confidentialité de l’information": ["confidentialite de linformation"],
    "Connaissance du client": ["connaissance du client"],
    "Connectique": ["connectique"],
    "Conseil en gestion": ["conseil en gestion"],
    "Conseil financier": ["conseil financier"],
    "Consolidation d'équipe": ["consolidation d'equipe"],
    "Consommation de gaz": ["consommation de gaz"],
    "Consommation d’eau": ["consommation deau"],
    "Consommation d’électricité": ["consommation delectricite"],
    "Construction automobile": ["construction automobile"],
    "Construction métallique": ["construction metallique"],
    "Contextes multiculturels": ["contextes multiculturels"],
    "Contrat intelligent": ["contrat intelligent"],
    "Contrats commerciaux": ["contrats commerciaux"],
    "Contrats de travail": ["contrats de travail"],
    "Contrôle des équipements de sécurité": ["controle des equipements de securite"],
    "Contrôle qualité": ["controle qualite"],
    "Contrôle qualité des livrables": ["controle qualite des livrables"],
    "Contrôle qualité des produits": ["controle qualite des produits"],
    "Contrôle qualité statistique": ["controle qualite statistique"],
    "Contrôle technique": ["controle technique"],
    "Convivialité de l’application": ["convivialite de lapplication"],
    "Copropriété": ["copropriete"],
    "Corel Draw": ["corel draw"],
    "Coréen": ["coreen"],
    "Courant électrique": ["courant electrique"],
    "Couture": ["couture"],
    "Criminalistique": ["criminalistique"],
    "Criminologie": ["criminologie"],
    "Croate": ["croate"],
    "Cryptographie": ["cryptographie"],
    "Cryptographie appliquée": ["cryptographie appliquee"],
    "Cryptologie": ["cryptologie"],
    "Cubase": ["cubase"],
    "Culture cellulaire": ["culture cellulaire"],
    "Cybernétique": ["cybernetique"],
    "Cynégétique": ["cynegetique"],
    "Câblage filaire": ["cablage filaire"],
    "Danois": ["danois"],
    "Data ingineering": ["data ingineering"],
    "Delphi": ["delphi"],
    "Design d'expérience utilisateur": ["design d'experience utilisateur"],
    "Dessin industriel": ["dessin industriel"],
    "Diagnostic de pannes": ["diagnostic de pannes"],
    "Diagnostic de performance": ["diagnostic de performance"],
    "Diagnostic social": ["diagnostic social"],
    "Distribution de carburant": ["distribution de carburant"],
    "Documentation technique d'installation": ["documentation technique d'installation"],
    "Domotique": ["domotique"],
    "Données de contrôle": ["donnees de controle"],
    "Données de maintenance": ["donnees de maintenance"],
    "Dosimétrie": ["dosimetrie"],
    "Dreamweaver": ["dreamweaver"],
    "Droit civil": ["droit civil"],
    "Droit de l'environnement": ["droit de l'environnement"],
    "Droit de l'internet": ["droit de l'internet"],
    "Droit de la consommation": ["droit de la consommation"],
    "Droit de la famille": ["droit de la famille"],
    "Droit des associations": ["droit des associations"],
    "Droit des assurances": ["droit des assurances"],
    "Droit des libertés publiques": ["droit des libertes publiques"],
    "Droit des marchés": ["droit des marches"],
    "Droit des marchés financiers": ["droit des marches financiers"],
    "Droit des médias": ["droit des medias"],
    "Droit des obligations": ["droit des obligations"],
    "Droit des successions": ["droit des successions"],
    "Droit des transports": ["droit des transports"],
    "Droit du commerce": ["droit du commerce"],
    "Droit du commerce international": ["droit du commerce international"],
    "Droit du numérique": ["droit du numerique"],
    "Droit européen": ["droit europeen"],
    "Droit international humanitaire": ["droit international humanitaire"],
    "Droit privé": ["droit prive"],
    "Droit économique": ["droit economique"],
    "Dynamique de groupe": ["dynamique de groupe"],
    "Déclaration Sociale Nominative": ["declaration sociale nominative"],
    "Défense nationale": ["defense nationale"],
    "Démantèlement": ["demantelement"],
    "Dématérialisation des procédures": ["dematerialisation des procedures"],
    "Démographie": ["demographie"],
    "Dépannage avancé": ["depannage avance"],
    "Dépendance aux drogues": ["dependance aux drogues"],
    "Déploiement de nouvelles applications": ["deploiement de nouvelles applications"],
    "Déploiement de réseau": ["deploiement de reseau"],
    "Déploiement de solutions": ["deploiement de solutions"],
    "Déploiement de solutions informatiques": ["deploiement de solutions informatiques"],
    "Détection de faux billets": ["detection de faux billets"],
    "Détection des fraudes": ["detection des fraudes"],
    "Développement d'applications mobiles": ["developpement d'applications mobiles"],
    "Développement de jeux vidéo": ["developpement de jeux video"],
    "Développement de logiciels embarqués": ["developpement de logiciels embarques"],
    "Développement de modules de formation": ["developpement de modules de formation"],
    "Développement de nouveaux produits": ["developpement de nouveaux produits"],
    "Développement de partenariats": ["developpement de partenariats"],
    "Développement de pipelines de données": ["developpement de pipelines de donnees"],
    "Développement de propositions commerciales": ["developpement de propositions commerciales"],
    "Développement de solutions informatiques": ["developpement de solutions informatiques"],
    "Développement de tableaux de bord": ["developpement de tableaux de bord"],
    "Développement du personnel": ["developpement du personnel"],
    "Développement durable": ["developpement durable"],
    "Développement en cascade": ["developpement en cascade"],
    "Développement international": ["developpement international"],
    "Développement organisationnel": ["developpement organisationnel"],
    "Développement personnel": ["developpement personnel"],
    "Développement prévisionnel": ["developpement previsionnel"],
    "Développement social": ["developpement social"],
    "Développement économique": ["developpement economique"],
    "E Business": ["e business"],
    "Eclipse IDE": ["eclipse ide"],
    "Eco-conception": ["eco-conception"],
    "Ecologie": ["ecologie"],
    "Economie de la construction": ["economie de la construction"],
    "Economie du développement durable": ["economie du developpement durable"],
    "Economie internationale": ["economie internationale"],
    "Economie sociale": ["economie sociale"],
    "Economie sociale et solidaire": ["economie sociale et solidaire"],
    "Econométrie": ["econometrie"],
    "Ecoute active": ["ecoute active"],
    "Education à la santé": ["education a la sante"],
    "Efficacité énergétique": ["efficacite energetique"],
    "Elaboration de plans de formation": ["elaboration de plans de formation"],
    "Elaboration de politiques de sécurité": ["elaboration de politiques de securite"],
    "Elaboration de spécifications techniques": ["elaboration de specifications techniques"],
    "Electricité": ["electricite"],
    "Electricité industrielle": ["electricite industrielle"],
    "Electromécanique": ["electromecanique"],
    "Electronique analogique": ["electronique analogique"],
    "Electronique de puissance": ["electronique de puissance"],
    "Electronique numérique": ["electronique numerique"],
    "Energies renouvelables": ["energies renouvelables"],
    "Entomologie": ["entomologie"],
    "Entrepreneuriat social": ["entrepreneuriat social"],
    "Entreprise sociale": ["entreprise sociale"],
    "Entretien de véhicules": ["entretien de vehicules"],
    "Entretien des espaces verts": ["entretien des espaces verts"],
    "Epidémiologie": ["epidemiologie"],
    "Equipement informatique": ["equipement informatique"],
    "Equipements de chauffage": ["equipements de chauffage"],
    "Equipements de sécurité": ["equipements de securite"],
    "Ergonomie": ["ergonomie"],
    "Erlang": ["erlang"],
    "Espagnol": ["espagnol"],
    "Espéranto": ["esperanto"],
    "Etablissement de cahiers des charges": ["etablissement de cahiers des charges"],
    "Ethique des affaires": ["ethique des affaires"],
    "Ethologie": ["ethologie"],
    "Etude prospective": ["etude prospective"],
    "Evaluation de la performance": ["evaluation de la performance"],
    "Evaluation de la performance commerciale": ["evaluation de la performance commerciale"],
    "Evaluation de la technologie": ["evaluation de la technologie"],
    "Evaluation de programmes": ["evaluation de programmes"],
    "Evaluation de projet": ["evaluation de projet"],
    "Evaluation des actifs": ["evaluation des actifs"],
    "Evaluation des besoins des utilisateurs": ["evaluation des besoins des utilisateurs"],
    "Evaluation des compétences": ["evaluation des competences"],
    "Evaluation des impacts réglementaires": ["evaluation des impacts reglementaires"],
    "Evaluation des nouvelles technologies": ["evaluation des nouvelles technologies"],
    "Evaluation des risques de crédit": ["evaluation des risques de credit"],
    "Evaluation des risques de sécurité": ["evaluation des risques de securite"],
    "Evaluation des risques financiers": ["evaluation des risques financiers"],
    "Evaluation des risques opérationnels": ["evaluation des risques operationnels"],
    "Evaluation des risques professionnels": ["evaluation des risques professionnels"],
    "Evaluation des écosystèmes": ["evaluation des ecosystemes"],
    "Expertise immobilière": ["expertise immobiliere"],
    "Exploitation de transport": ["exploitation de transport"],
    "Exploitation forestière": ["exploitation forestiere"],
    "Exploration fonctionnelle": ["exploration fonctionnelle"],
    "Extraction de l’information": ["extraction de linformation"],
    "Fabrication de bijoux": ["fabrication de bijoux"],
    "Fabrication de meubles": ["fabrication de meubles"],
    "Faisceaux de câbles": ["faisceaux de cables"],
    "Fibre optique": ["fibre optique"],
    "Finance durable": ["finance durable"],
    "Finance internationale": ["finance internationale"],
    "Financement participatif": ["financement participatif"],
    "Finances publiques": ["finances publiques"],
    "Finnois": ["finnois"],
    "Fireworks": ["fireworks"],
    "Formation continue des équipes": ["formation continue des equipes"],
    "Formation des employés": ["formation des employes"],
    "Formation des nouveaux employés": ["formation des nouveaux employes"],
    "Formation des salariés": ["formation des salaries"],
    "Fourniture de service": ["fourniture de service"],
    "FrameMaker": ["framemaker"],
    "Framework Hibernate": ["framework hibernate"],
    "Framework Yii": ["framework yii"],
    "Framework Zend": ["framework zend"],
    "Freeform": ["freeform"],
    "Froid industriel": ["froid industriel"],
    "Fusion 360": ["fusion 360"],
    "Gallois": ["gallois"],
    "Gaz naturel": ["gaz naturel"],
    "Gestion de Fonds d'investissement": ["gestion de fonds d'investissement"],
    "Gestion de campagnes publicitaires": ["gestion de campagnes publicitaires"],
    "Gestion de classe": ["gestion de classe"],
    "Gestion de collection": ["gestion de collection"],
    "Gestion de conflits": ["gestion de conflits"],
    "Gestion de contenu web": ["gestion de contenu web"],
    "Gestion de groupe": ["gestion de groupe"],
    "Gestion de l'information": ["gestion de l'information"],
    "Gestion de la dette": ["gestion de la dette"],
    "Gestion de la documentation réglementaire": ["gestion de la documentation reglementaire"],
    "Gestion de la maintenance": ["gestion de la maintenance"],
    "Gestion de la performance": ["gestion de la performance"],
    "Gestion de la production": ["gestion de la production"],
    "Gestion de la qualité informatique": ["gestion de la qualite informatique"],
    "Gestion de la relation fournisseur": ["gestion de la relation fournisseur"],
    "Gestion de la virtualisation": ["gestion de la virtualisation"],
    "Gestion de personnel": ["gestion de personnel"],
    "Gestion de portefeuille clients": ["gestion de portefeuille clients"],
    "Gestion de projets IA": ["gestion de projets ia"],
    "Gestion de projets de formation": ["gestion de projets de formation"],
    "Gestion de projets e-commerce": ["gestion de projets e-commerce"],
    "Gestion de projets immobiliers": ["gestion de projets immobiliers"],
    "Gestion de projets innovants": ["gestion de projets innovants"],
    "Gestion de projets internationaux": ["gestion de projets internationaux"],
    "Gestion de projets pédagogiques": ["gestion de projets pedagogiques"],
    "Gestion de projets télécoms": ["gestion de projets telecoms"],
    "Gestion de projets web": ["gestion de projets web"],
    "Gestion de serveurs": ["gestion de serveurs"],
    "Gestion de version de code": ["gestion de version de code"],
    "Gestion des accès réseau": ["gestion des acces reseau"],
    "Gestion des accès sécurisés": ["gestion des acces securises"],
    "Gestion des agendas": ["gestion des agendas"],
    "Gestion des alarmes": ["gestion des alarmes"],
    "Gestion des assurances": ["gestion des assurances"],
    "Gestion des budgets": ["gestion des budgets"],
    "Gestion des budgets de fonctionnement": ["gestion des budgets de fonctionnement"],
    "Gestion des capitaux": ["gestion des capitaux"],
    "Gestion des carrières": ["gestion des carrieres"],
    "Gestion des commandes de pièces": ["gestion des commandes de pieces"],
    "Gestion des comptes utilisateurs": ["gestion des comptes utilisateurs"],
    "Gestion des configurations": ["gestion des configurations"],
    "Gestion des connaissances": ["gestion des connaissances"],
    "Gestion des contrats": ["gestion des contrats"],
    "Gestion des contrats de location": ["gestion des contrats de location"],
    "Gestion des contrats de service": ["gestion des contrats de service"],
    "Gestion des cultures": ["gestion des cultures"],
    "Gestion des documents": ["gestion des documents"],
    "Gestion des dossiers administratifs": ["gestion des dossiers administratifs"],
    "Gestion des dossiers médicaux": ["gestion des dossiers medicaux"],
    "Gestion des droits d'accès": ["gestion des droits d'acces"],
    "Gestion des droits numériques": ["gestion des droits numeriques"],
    "Gestion des déchets": ["gestion des dechets"],
    "Gestion des déchets radioactifs": ["gestion des dechets radioactifs"],
    "Gestion des emails": ["gestion des emails"],
    "Gestion des escalades techniques": ["gestion des escalades techniques"],
    "Gestion des flux de matières": ["gestion des flux de matieres"],
    "Gestion des flux financiers": ["gestion des flux financiers"],
    "Gestion des incidents de production": ["gestion des incidents de production"],
    "Gestion des incidents de sécurité": ["gestion des incidents de securite"],
    "Gestion des incidents réseau": ["gestion des incidents reseau"],
    "Gestion des innovations": ["gestion des innovations"],
    "Gestion des inventaires": ["gestion des inventaires"],
    "Gestion des investissements": ["gestion des investissements"],
    "Gestion des licences logicielles": ["gestion des licences logicielles"],
    "Gestion des liquidités": ["gestion des liquidites"],
    "Gestion des litiges": ["gestion des litiges"],
    "Gestion des niveaux de services": ["gestion des niveaux de services"],
    "Gestion des non-conformités": ["gestion des non-conformites"],
    "Gestion des opérations": ["gestion des operations"],
    "Gestion des opérations de change": ["gestion des operations de change"],
    "Gestion des ordonnances": ["gestion des ordonnances"],
    "Gestion des paiements": ["gestion des paiements"],
    "Gestion des partenariats stratégiques": ["gestion des partenariats strategiques"],
    "Gestion des passagers": ["gestion des passagers"],
    "Gestion des plaintes": ["gestion des plaintes"],
    "Gestion des politiques de sécurité": ["gestion des politiques de securite"],
    "Gestion des preuves": ["gestion des preuves"],
    "Gestion des relations bancaires": ["gestion des relations bancaires"],
    "Gestion des ressources en eau": ["gestion des ressources en eau"],
    "Gestion des ressources humaines": ["gestion des ressources humaines"],
    "Gestion des ressources matérielles": ["gestion des ressources materielles"],
    "Gestion des risques climatiques": ["gestion des risques climatiques"],
    "Gestion des risques d'entreprise": ["gestion des risques d'entreprise"],
    "Gestion des risques financiers": ["gestion des risques financiers"],
    "Gestion des risques informatiques": ["gestion des risques informatiques"],
    "Gestion des risques juridiques": ["gestion des risques juridiques"],
    "Gestion des risques opérationnels": ["gestion des risques operationnels"],
    "Gestion des risques professionnels": ["gestion des risques professionnels"],
    "Gestion des risques projet": ["gestion des risques projet"],
    "Gestion des rémunérations": ["gestion des remunerations"],
    "Gestion des réservations": ["gestion des reservations"],
    "Gestion des réservations en ligne": ["gestion des reservations en ligne"],
    "Gestion des subventions": ["gestion des subventions"],
    "Gestion des ventes": ["gestion des ventes"],
    "Gestion des visites médicales": ["gestion des visites medicales"],
    "Gestion des émotions": ["gestion des emotions"],
    "Gestion des équipements de sécurité": ["gestion des equipements de securite"],
    "Gestion des équipes de développement": ["gestion des equipes de developpement"],
    "Gestion douanière": ["gestion douaniere"],
    "Gestion du Back Office": ["gestion du back office"],
    "Gestion du littoral": ["gestion du littoral"],
    "Gestion du marketing": ["gestion du marketing"],
    "Gestion du personnel": ["gestion du personnel"],
    "Gestion durable des forêts": ["gestion durable des forets"],
    "Gestion financière et budgétaire": ["gestion financiere et budgetaire"],
    "Gestion locative": ["gestion locative"],
    "Gestion prévisionnelle": ["gestion previsionnelle"],
    "Gestion stratégique des organisations": ["gestion strategique des organisations"],
    "Google Docs": ["google docs"],
    "Google Looker": ["google looker"],
    "Google Workspace": ["google workspace"],
    "Gouvernance du SI": ["gouvernance du si"],
    "Grafcet": ["grafcet"],
    "Grammaire": ["grammaire"],
    "Granulométrie": ["granulometrie"],
    "Graphisme": ["graphisme"],
    "Grec": ["grec"],
    "Grec ancien": ["grec ancien"],
    "Gujarati": ["gujarati"],
    "Gynécologie": ["gynecologie"],
    "Génie chimique": ["genie chimique"],
    "Génie des procédés": ["genie des procedes"],
    "Génie des télécommunications": ["genie des telecommunications"],
    "Génie génétique": ["genie genetique"],
    "Génie industriel": ["genie industriel"],
    "Génie informatique": ["genie informatique"],
    "Génie mécanique": ["genie mecanique"],
    "Génie thermique": ["genie thermique"],
    "Génie électrique": ["genie electrique"],
    "Génie énergétique": ["genie energetique"],
    "Génomique": ["genomique"],
    "Généalogie": ["genealogie"],
    "Générateurs électriques": ["generateurs electriques"],
    "Génétique": ["genetique"],
    "Géochimie": ["geochimie"],
    "Géographie": ["geographie"],
    "Géographie des transports": ["geographie des transports"],
    "Géologie": ["geologie"],
    "Géomatique": ["geomatique"],
    "Géométrie": ["geometrie"],
    "Géométrie différentielle": ["geometrie differentielle"],
    "Géophysique": ["geophysique"],
    "Géopolitique": ["geopolitique"],
    "Géorgien": ["georgien"],
    "Géostratégie": ["geostrategie"],
    "Géotechnique": ["geotechnique"],
    "Géothermie": ["geothermie"],
    "Handicap moteur": ["handicap moteur"],
    "Haskell": ["haskell"],
    "Hindi": ["hindi"],
    "Histoire naturelle": ["histoire naturelle"],
    "Histoire-Géographie": ["histoire-geographie"],
    "Histologie": ["histologie"],
    "Holographie": ["holographie"],
    "Hongrois": ["hongrois"],
    "Hospitalisation à domicile": ["hospitalisation a domicile"],
    "Hydraulique": ["hydraulique"],
    "Hydraulique urbaine": ["hydraulique urbaine"],
    "Hydrodynamique": ["hydrodynamique"],
    "Hydrologie": ["hydrologie"],
    "Hypnose": ["hypnose"],
    "Hébreu": ["hebreu"],
    "Hématologie": ["hematologie"],
    "IBM InfoSphere DataStage": ["ibm infosphere datastage"],
    "IBM SPSS Statistics": ["ibm spss statistics"],
    "IBM WebSphere": ["ibm websphere"],
    "IBM WebSphere MQ": ["ibm websphere mq"],
    "Iconographie": ["iconographie"],
    "Identifiants décentralisés": ["identifiants decentralises"],
    "Identification des besoins": ["identification des besoins"],
    "Immunologie": ["immunologie"],
    "Implémentation de solutions techniques": ["implementation de solutions techniques"],
    "Impression numérique": ["impression numerique"],
    "Improvisation théâtrale": ["improvisation theatrale"],
    "Indicateurs statistiques": ["indicateurs statistiques"],
    "Industrie cosmétique": ["industrie cosmetique"],
    "Industrie des télécommunications": ["industrie des telecommunications"],
    "Industrie hydraulique": ["industrie hydraulique"],
    "Industrie pétrolière": ["industrie petroliere"],
    "Industrie textile": ["industrie textile"],
    "Informatique des systèmes embarqués": ["informatique des systemes embarques"],
    "Informatique quantique": ["informatique quantique"],
    "Informatique scientifique": ["informatique scientifique"],
    "Infrastructure ferroviaire": ["infrastructure ferroviaire"],
    "Infrastructures numériques": ["infrastructures numeriques"],
    "Inférence statistique": ["inference statistique"],
    "Ingénierie de projet": ["ingenierie de projet"],
    "Ingénierie de surface": ["ingenierie de surface"],
    "Ingénierie de systèmes": ["ingenierie de systemes"],
    "Ingénierie de sécurité": ["ingenierie de securite"],
    "Ingénierie des matériaux": ["ingenierie des materiaux"],
    "Ingénierie des réseaux": ["ingenierie des reseaux"],
    "Ingénierie des transports": ["ingenierie des transports"],
    "Ingénierie financière": ["ingenierie financiere"],
    "Innovation managériale": ["innovation manageriale"],
    "Installation de composants matériels": ["installation de composants materiels"],
    "Instruments d’assistance": ["instruments dassistance"],
    "Interaction homme-machine": ["interaction homme-machine"],
    "Internet des objets": ["internet des objets"],
    "Interprétation de données financières": ["interpretation de donnees financieres"],
    "Intuit QuickBooks": ["intuit quickbooks"],
    "Intégration de données": ["integration de donnees"],
    "Intégration des systèmes": ["integration des systemes"],
    "Irlandais": ["irlandais"],
    "Italien": ["italien"],
    "J2ME": ["j2me"],
    "Japonais": ["japonais"],
    "JavaScript Framework": ["javascript framework"],
    "Javadoc": ["javadoc"],
    "Joint-ventures": ["joint-ventures"],
    "Joomla": ["joomla"],
    "Journalisme": ["journalisme"],
    "Journalisme numérique": ["journalisme numerique"],
    "KDevelop": ["kdevelop"],
    "Kali Linux": ["kali linux"],
    "Kinésiologie": ["kinesiologie"],
    "LESS": ["less"],
    "LINQ": ["linq"],
    "Langage du corps": ["langage du corps"],
    "Langages de programmation informatique": ["langages de programmation informatique"],
    "Langages de requête": ["langages de requete"],
    "Langue des signes": ["langue des signes"],
    "Latin": ["latin"],
    "Lexicologie": ["lexicologie"],
    "LightWave": ["lightwave"],
    "Linguistique informatique": ["linguistique informatique"],
    "Lisp": ["lisp"],
    "Littérature scientifique": ["litterature scientifique"],
    "Localisation de panne": ["localisation de panne"],
    "Location immobilière": ["location immobiliere"],
    "Logiciel de création": ["logiciel de creation"],
    "Logiciel de négociation": ["logiciel de negociation"],
    "Logiciel de traitement de texte": ["logiciel de traitement de texte"],
    "Logiciel d’édition graphique": ["logiciel dedition graphique"],
    "Logiciels bancaires": ["logiciels bancaires"],
    "Logiciels comptables": ["logiciels comptables"],
    "Logiciels de bureautique": ["logiciels de bureautique"],
    "Logiciels financiers": ["logiciels financiers"],
    "Logiciels industriels": ["logiciels industriels"],
    "Logiciels métiers": ["logiciels metiers"],
    "Logistique maritime": ["logistique maritime"],
    "Luxembourgeois": ["luxembourgeois"],
    "Législation environnementale": ["legislation environnementale"],
    "Législation fiscale": ["legislation fiscale"],
    "Législation sociale": ["legislation sociale"],
    "Machines électriques": ["machines electriques"],
    "Machines-outils": ["machines-outils"],
    "Macroéconomie": ["macroeconomie"],
    "Maintenance de logiciels": ["maintenance de logiciels"],
    "Maintenance de matériel informatique": ["maintenance de materiel informatique"],
    "Maintenance de premier niveau": ["maintenance de premier niveau"],
    "Maintenance de serveurs": ["maintenance de serveurs"],
    "Maintenance de sites web": ["maintenance de sites web"],
    "Maintenance de systèmes informatiques": ["maintenance de systemes informatiques"],
    "Maintenance des systèmes de sécurité": ["maintenance des systemes de securite"],
    "Maintenance des systèmes informatiques": ["maintenance des systemes informatiques"],
    "Maintenance des systèmes électriques": ["maintenance des systemes electriques"],
    "Maintenance préventive et corrective": ["maintenance preventive et corrective"],
    "Management de projet": ["management de projet"],
    "Management de proximité": ["management de proximite"],
    "Management interculturel": ["management interculturel"],
    "Management opérationnel": ["management operationnel"],
    "Management stratégique": ["management strategique"],
    "Manucure": ["manucure"],
    "Manutention portuaire": ["manutention portuaire"],
    "Marathi": ["marathi"],
    "Marché de l’électricité": ["marche de lelectricite"],
    "Marché de l’énergie": ["marche de lenergie"],
    "Marché des énergies": ["marche des energies"],
    "Marché du gaz": ["marche du gaz"],
    "Marché du tourisme": ["marche du tourisme"],
    "Marché du travail": ["marche du travail"],
    "Marché immobilier": ["marche immobilier"],
    "Marchés internationaux": ["marches internationaux"],
    "MarkLogic": ["marklogic"],
    "Marketing des services": ["marketing des services"],
    "Marketing réseau": ["marketing reseau"],
    "Marketo": ["marketo"],
    "Matrice SWOT": ["matrice swot"],
    "Matériaux avancés": ["materiaux avances"],
    "Matériaux composites": ["materiaux composites"],
    "Matériel audiovisuel": ["materiel audiovisuel"],
    "Matériel informatique": ["materiel informatique"],
    "Matériovigilance": ["materiovigilance"],
    "Maîtrise des logiciels de bureautique": ["maitrise des logiciels de bureautique"],
    "Maîtrise des logiciels de gestion": ["maitrise des logiciels de gestion"],
    "Menaces cybernétiques": ["menaces cybernetiques"],
    "Menaces de sécurité": ["menaces de securite"],
    "Menuiserie": ["menuiserie"],
    "Metasploit": ["metasploit"],
    "Microbiologie": ["microbiologie"],
    "Micromécanique": ["micromecanique"],
    "Microprocesseurs": ["microprocesseurs"],
    "Microsoft Access": ["microsoft access"],
    "Microsoft Edge": ["microsoft edge"],
    "Microsoft Exchange Server": ["microsoft exchange server"],
    "Microsoft Visio": ["microsoft visio"],
    "Microsoft Visual C++": ["microsoft visual c++"],
    "Microsoft Visual Studio": ["microsoft visual studio"],
    "Microsoft Word": ["microsoft word"],
    "Microéconomie": ["microeconomie"],
    "Microélectronique": ["microelectronique"],
    "Mise à jour de logiciels": ["mise a jour de logiciels"],
    "Mixage audio": ["mixage audio"],
    "Mixologie": ["mixologie"],
    "Mobile marketing": ["mobile marketing"],
    "Modes de paiement": ["modes de paiement"],
    "Modélisation 3D": ["modelisation 3d"],
    "Modélisation des risques": ["modelisation des risques"],
    "Modélisation et simulation": ["modelisation et simulation"],
    "Modélisation informatique": ["modelisation informatique"],
    "Modélisation mathématique": ["modelisation mathematique"],
    "Modélisation scientifique": ["modelisation scientifique"],
    "Modélisation spatiale": ["modelisation spatiale"],
    "Modélisation statistique": ["modelisation statistique"],
    "Modélisation économique": ["modelisation economique"],
    "Morale": ["morale"],
    "Morphologie": ["morphologie"],
    "Moteurs de recherche": ["moteurs de recherche"],
    "Moteurs électriques": ["moteurs electriques"],
    "Mozilla Firefox": ["mozilla firefox"],
    "Musicologie": ["musicologie"],
    "Musicothérapie": ["musicotherapie"],
    "Muséologie": ["museologie"],
    "Myologie": ["myologie"],
    "Mécanique automobile": ["mecanique automobile"],
    "Mécanique computationnelle": ["mecanique computationnelle"],
    "Mécanique de précision": ["mecanique de precision"],
    "Mécanique des fluides": ["mecanique des fluides"],
    "Mécanique des matériaux": ["mecanique des materiaux"],
    "Mécanique des solides": ["mecanique des solides"],
    "Mécanique des sols": ["mecanique des sols"],
    "Mécanique poids lourds": ["mecanique poids lourds"],
    "Mécanique productique": ["mecanique productique"],
    "Mécatronique": ["mecatronique"],
    "Médecine du travail": ["medecine du travail"],
    "Médecine interne": ["medecine interne"],
    "Médecine nucléaire": ["medecine nucleaire"],
    "Médias interactifs": ["medias interactifs"],
    "Métallerie": ["metallerie"],
    "Métallurgie": ["metallurgie"],
    "Méthode Monte-Carlo": ["methode monte-carlo"],
    "Méthode des 5S": ["methode des 5s"],
    "Méthode six sigma": ["methode six sigma"],
    "Méthodes d'industrialisation": ["methodes d'industrialisation"],
    "Méthodes de conseil": ["methodes de conseil"],
    "Méthodes de paiement": ["methodes de paiement"],
    "Méthodes de prospection": ["methodes de prospection"],
    "Méthodes d’assurance qualité": ["methodes dassurance qualite"],
    "Méthodes process": ["methodes process"],
    "Méthodologie des tests": ["methodologie des tests"],
    "Météorologie": ["meteorologie"],
    "Nanotechnologie": ["nanotechnologie"],
    "Nautisme": ["nautisme"],
    "Navigation maritime": ["navigation maritime"],
    "Nettoyage de données": ["nettoyage de donnees"],
    "Netvibes": ["netvibes"],
    "Neurologie": ["neurologie"],
    "Neuropsychologie": ["neuropsychologie"],
    "Neuroscience": ["neuroscience"],
    "Neutronique": ["neutronique"],
    "Nexpose": ["nexpose"],
    "Norme ISO 50001": ["norme iso 50001"],
    "Normes ISO 14000": ["normes iso 14000"],
    "Normes OTAN": ["normes otan"],
    "Normes de qualité": ["normes de qualite"],
    "Normes de réseau": ["normes de reseau"],
    "Normes de sécurité alimentaire": ["normes de securite alimentaire"],
    "Normes d’accessibilité TIC": ["normes daccessibilite tic"],
    "Normes environnementales": ["normes environnementales"],
    "Normes qualité": ["normes qualite"],
    "Normes rédactionnelles": ["normes redactionnelles"],
    "Normes sanitaires": ["normes sanitaires"],
    "Norvégien": ["norvegien"],
    "Notepad++": ["notepad++"],
    "Nuke": ["nuke"],
    "Numérisation": ["numerisation"],
    "Néerlandais": ["neerlandais"],
    "Néonatalogie": ["neonatalogie"],
    "Néphrologie": ["nephrologie"],
    "OWASP ZAP": ["owasp zap"],
    "ObjectStore": ["objectstore"],
    "Objective-C": ["objective-c"],
    "Occitan": ["occitan"],
    "Octopus Deploy": ["octopus deploy"],
    "Océanographie": ["oceanographie"],
    "Océanologie": ["oceanologie"],
    "OmniPage": ["omnipage"],
    "Ophtalmologie": ["ophtalmologie"],
    "Optimisation de bases de données": ["optimisation de bases de donnees"],
    "Optimisation de la consommation énergétique": ["optimisation de la consommation energetique"],
    "Optimisation de la performance réseau": ["optimisation de la performance reseau"],
    "Optimisation de la performance web": ["optimisation de la performance web"],
    "Optimisation de performances": ["optimisation de performances"],
    "Optimisation des coûts de production": ["optimisation des couts de production"],
    "Optimisation des coûts de transport": ["optimisation des couts de transport"],
    "Optimisation des performances des applications": ["optimisation des performances des applications"],
    "Optimisation des performances des serveurs": ["optimisation des performances des serveurs"],
    "Optimisation des performances web": ["optimisation des performances web"],
    "Optimisation des processus": ["optimisation des processus"],
    "Optimisation des processus DevOps": ["optimisation des processus devops"],
    "Optimisation des processus comptables": ["optimisation des processus comptables"],
    "Optimisation des processus d'affaires": ["optimisation des processus d'affaires"],
    "Optimisation des processus de production": ["optimisation des processus de production"],
    "Optimisation des processus de projet": ["optimisation des processus de projet"],
    "Optimisation des processus de support": ["optimisation des processus de support"],
    "Optimisation des processus de travail": ["optimisation des processus de travail"],
    "Optimisation des processus décisionnels": ["optimisation des processus decisionnels"],
    "Optimisation des processus industriels": ["optimisation des processus industriels"],
    "Optimisation des processus informatiques": ["optimisation des processus informatiques"],
    "Optimisation des processus métier": ["optimisation des processus metier"],
    "Optimisation des processus techniques": ["optimisation des processus techniques"],
    "Optimisation des ressources matérielles": ["optimisation des ressources materielles"],
    "Optimisation fiscale": ["optimisation fiscale"],
    "Optométrie": ["optometrie"],
    "Optoélectronique": ["optoelectronique"],
    "Optronique": ["optronique"],
    "Opérations de maintenance": ["operations de maintenance"],
    "Opérations portuaires": ["operations portuaires"],
    "Oracle Data Integrator": ["oracle data integrator"],
    "Oracle SQL Developer": ["oracle sql developer"],
    "Oracle Warehouse Builder": ["oracle warehouse builder"],
    "Oracle WebLogic": ["oracle weblogic"],
    "Ordre de fabrication": ["ordre de fabrication"],
    "Organisations internationales": ["organisations internationales"],
    "Orthodontie": ["orthodontie"],
    "Orthographe": ["orthographe"],
    "Orthopédie": ["orthopedie"],
    "Ostéopathie": ["osteopathie"],
    "Ourdou": ["ourdou"],
    "Outils d'évaluation": ["outils d'evaluation"],
    "Outils de datavisualisation": ["outils de datavisualisation"],
    "Outils de gestion de contenu": ["outils de gestion de contenu"],
    "Outils de montage": ["outils de montage"],
    "Outils industriels": ["outils industriels"],
    "Oxydation": ["oxydation"],
    "Page Maker": ["page maker"],
    "Painter": ["painter"],
    "Panaya": ["panaya"],
    "Paramétrage de logiciels": ["parametrage de logiciels"],
    "Parapharmacie": ["parapharmacie"],
    "Pascal": ["pascal"],
    "Pathologie": ["pathologie"],
    "Peinture industrielle": ["peinture industrielle"],
    "Pendjabi": ["pendjabi"],
    "Pentaho Data Integration": ["pentaho data integration"],
    "PeopleSoft": ["peoplesoft"],
    "Perse": ["perse"],
    "Pharmacocinétique": ["pharmacocinetique"],
    "Pharmacovigilance": ["pharmacovigilance"],
    "Philanthropie": ["philanthropie"],
    "Philologie": ["philologie"],
    "Photogrammétrie": ["photogrammetrie"],
    "Photographie": ["photographie"],
    "Photographie commerciale": ["photographie commerciale"],
    "Photogravure": ["photogravure"],
    "Photométrie": ["photometrie"],
    "Photonique": ["photonique"],
    "Physiologie": ["physiologie"],
    "Physique computationnelle": ["physique computationnelle"],
    "Physique mathématique": ["physique mathematique"],
    "Physique nucléaire": ["physique nucleaire"],
    "Physique quantique": ["physique quantique"],
    "Phytothérapie": ["phytotherapie"],
    "Plan d'implantation": ["plan d'implantation"],
    "Plan de financement": ["plan de financement"],
    "Plan de travail": ["plan de travail"],
    "Plan de vol": ["plan de vol"],
    "Planification médiatique": ["planification mediatique"],
    "Planning stratégique": ["planning strategique"],
    "Plans d'exécution": ["plans d'execution"],
    "Plasturgie": ["plasturgie"],
    "Plateformes IoT": ["plateformes iot"],
    "Plateformes de gestion de contenu": ["plateformes de gestion de contenu"],
    "Plateformes de service": ["plateformes de service"],
    "Pneumatique": ["pneumatique"],
    "Podologie": ["podologie"],
    "Poids lourds": ["poids lourds"],
    "Politique de rémunération": ["politique de remuneration"],
    "Politique environnementale": ["politique environnementale"],
    "Politiques publiques": ["politiques publiques"],
    "Polonais": ["polonais"],
    "Post-synchronisation": ["post-synchronisation"],
    "Postes d'aiguillage": ["postes d'aiguillage"],
    "Power Automate": ["power automate"],
    "Pratique de langues étrangères": ["pratique de langues etrangeres"],
    "Premier secours": ["premier secours"],
    "Premiers secours": ["premiers secours"],
    "Primavera": ["primavera"],
    "Principes budgétaires": ["principes budgetaires"],
    "Prise de décision stratégique": ["prise de decision strategique"],
    "Prix des pièces": ["prix des pieces"],
    "Prix du marché": ["prix du marche"],
    "Processus d'ingénierie": ["processus d'ingenierie"],
    "Processus d'évaluation": ["processus d'evaluation"],
    "Processus d’innovation": ["processus dinnovation"],
    "Procore": ["procore"],
    "Procédure budgétaire": ["procedure budgetaire"],
    "Procédure civile": ["procedure civile"],
    "Procédures administratives": ["procedures administratives"],
    "Procédures de contrôle": ["procedures de controle"],
    "Procédures de fabrication": ["procedures de fabrication"],
    "Procédures de maintenance": ["procedures de maintenance"],
    "Procédures de nettoyage": ["procedures de nettoyage"],
    "Procédures de secours": ["procedures de secours"],
    "Procédures de tests": ["procedures de tests"],
    "Procédures disciplinaires": ["procedures disciplinaires"],
    "Procédures d’assurance qualité": ["procedures dassurance qualite"],
    "Procédures d’essai": ["procedures dessai"],
    "Procédures judiciaires": ["procedures judiciaires"],
    "Procédures pénales": ["procedures penales"],
    "Procédés de fabrication": ["procedes de fabrication"],
    "Procédés de teinture": ["procedes de teinture"],
    "Production de la documentation": ["production de la documentation"],
    "Productique": ["productique"],
    "Produits bancaires": ["produits bancaires"],
    "Produits capillaires": ["produits capillaires"],
    "Produits chimiques": ["produits chimiques"],
    "Produits d'assurance": ["produits d'assurance"],
    "Produits d'hygiène": ["produits d'hygiene"],
    "Produits de construction": ["produits de construction"],
    "Produits financiers": ["produits financiers"],
    "Produits pharmaceutiques": ["produits pharmaceutiques"],
    "Progiciels comptables": ["progiciels comptables"],
    "Programmation de microcontrôleurs": ["programmation de microcontroleurs"],
    "Programmation informatique": ["programmation informatique"],
    "Programmation logicielle": ["programmation logicielle"],
    "Programmation orientée objet - POO": ["programmation orientee objet - poo"],
    "Programmation web": ["programmation web"],
    "Programmes de fidélité": ["programmes de fidelite"],
    "Programmes scolaires": ["programmes scolaires"],
    "Projets culturels": ["projets culturels"],
    "Prolog": ["prolog"],
    "Protection de l’enfance": ["protection de lenfance"],
    "Protection des biens": ["protection des biens"],
    "Protection des consommateurs": ["protection des consommateurs"],
    "Protection des données numériques": ["protection des donnees numeriques"],
    "Protection des données personnelles": ["protection des donnees personnelles"],
    "Protection des personnes": ["protection des personnes"],
    "Prothèses": ["protheses"],
    "Protocole SIP": ["protocole sip"],
    "Protocoles IP": ["protocoles ip"],
    "Prototypage rapide": ["prototypage rapide"],
    "Prototypage électronique": ["prototypage electronique"],
    "Préparation aux examens": ["preparation aux examens"],
    "Préparation des factures": ["preparation des factures"],
    "Préparation des états financiers": ["preparation des etats financiers"],
    "Prévention des accidents maritimes": ["prevention des accidents maritimes"],
    "Prévention des fuites de données": ["prevention des fuites de donnees"],
    "Prévision budgétaire": ["prevision budgetaire"],
    "Prévision financière": ["prevision financiere"],
    "Prévision météorologique": ["prevision meteorologique"],
    "Prévisions de la demande": ["previsions de la demande"],
    "Prévisions financières": ["previsions financieres"],
    "Prêts aux entreprises": ["prets aux entreprises"],
    "Prêts immobiliers": ["prets immobiliers"],
    "Psychiatrie": ["psychiatrie"],
    "Psychologie cognitive": ["psychologie cognitive"],
    "Psychologie expérimentale": ["psychologie experimentale"],
    "Psychopédagogie": ["psychopedagogie"],
    "Psychosociologie": ["psychosociologie"],
    "Puériculture": ["puericulture"],
    "PyTorch": ["pytorch"],
    "Python (programmation informatique)": ["python (programmation informatique)"],
    "Questions juridiques": ["questions juridiques"],
    "Radioprotection": ["radioprotection"],
    "Radiothérapie": ["radiotherapie"],
    "Rapport d'avancement": ["rapport d'avancement"],
    "Reboisement": ["reboisement"],
    "Recherche action": ["recherche action"],
    "Recherche bibliographique": ["recherche bibliographique"],
    "Recherche clinique": ["recherche clinique"],
    "Recherche en éducation": ["recherche en education"],
    "Recherche iconographique": ["recherche iconographique"],
    "Recherche juridique": ["recherche juridique"],
    "Recherche opérationnelle": ["recherche operationnelle"],
    "Recherche pluridisciplinaire": ["recherche pluridisciplinaire"],
    "Reclassement": ["reclassement"],
    "Reconnaissance d’images": ["reconnaissance dimages"],
    "Reconnaissance vocale": ["reconnaissance vocale"],
    "Renforcement des capacités": ["renforcement des capacites"],
    "Reprographie": ["reprographie"],
    "Respect des délais": ["respect des delais"],
    "Respect des délais de livraison": ["respect des delais de livraison"],
    "Respect des délais de production": ["respect des delais de production"],
    "Respect des délais de traitement": ["respect des delais de traitement"],
    "Respect des normes de sécurité": ["respect des normes de securite"],
    "Respect des normes éthiques": ["respect des normes ethiques"],
    "Respect des procédures administratives": ["respect des procedures administratives"],
    "Respect des protocoles de sécurité": ["respect des protocoles de securite"],
    "Responsabilité civile": ["responsabilite civile"],
    "Rhinocéros 3D": ["rhinoceros 3d"],
    "Rhétorique": ["rhetorique"],
    "Risques incendie": ["risques incendie"],
    "Risques naturels": ["risques naturels"],
    "Risques électriques": ["risques electriques"],
    "Robotique": ["robotique"],
    "Roumain": ["roumain"],
    "Russe": ["russe"],
    "Règles de confidentialité": ["regles de confidentialite"],
    "Réalité augmentée": ["realite augmentee"],
    "Réalité virtuelle": ["realite virtuelle"],
    "Réalité virtuelle et augmentée": ["realite virtuelle et augmentee"],
    "Réassurance": ["reassurance"],
    "Rédaction de comptes rendus": ["redaction de comptes rendus"],
    "Rédaction de rapports d'activité": ["redaction de rapports d'activite"],
    "Rédaction de rapports d'incident": ["redaction de rapports d'incident"],
    "Rédaction de rapports de projet": ["redaction de rapports de projet"],
    "Rédaction de rapports de sécurité": ["redaction de rapports de securite"],
    "Rédaction de rapports de validation": ["redaction de rapports de validation"],
    "Rédaction de rapports scientifiques": ["redaction de rapports scientifiques"],
    "Rédaction de rapports techniques": ["redaction de rapports techniques"],
    "Rédaction de supports d'information": ["redaction de supports d'information"],
    "Régimes alimentaires": ["regimes alimentaires"],
    "Régimes de retraite": ["regimes de retraite"],
    "Réglementation Sociale Européenne": ["reglementation sociale europeenne"],
    "Réglementation bancaire": ["reglementation bancaire"],
    "Réglementation douanière": ["reglementation douaniere"],
    "Réglementation du commerce électronique": ["reglementation du commerce electronique"],
    "Réglementation du transport": ["reglementation du transport"],
    "Réglementations environnementales": ["reglementations environnementales"],
    "Réglementations internationales en vigueur": ["reglementations internationales en vigueur"],
    "Répression des fraudes": ["repression des fraudes"],
    "Réseau de tramway": ["reseau de tramway"],
    "Réseaux associatifs": ["reseaux associatifs"],
    "Réseaux de téléphonie fixe": ["reseaux de telephonie fixe"],
    "Réseaux informatiques et télécoms": ["reseaux informatiques et telecoms"],
    "Réseaux radio mobiles": ["reseaux radio mobiles"],
    "Résilience organisationnelle": ["resilience organisationnelle"],
    "SA8000": ["sa8000"],
    "SAP Data Services": ["sap data services"],
    "SPARQL": ["sparql"],
    "Santé au travail": ["sante au travail"],
    "Santé et sécurité au travail": ["sante et securite au travail"],
    "Satellites géostationnaires": ["satellites geostationnaires"],
    "Science des matériaux": ["science des materiaux"],
    "Sciences de l'éducation": ["sciences de l'education"],
    "Sciences du vivant": ["sciences du vivant"],
    "Sciences exactes": ["sciences exactes"],
    "Sciences humaines et sociales": ["sciences humaines et sociales"],
    "Sciences physiques": ["sciences physiques"],
    "Sciences politiques": ["sciences politiques"],
    "Sciences économiques et sociales": ["sciences economiques et sociales"],
    "Second oeuvre": ["second oeuvre"],
    "Segmentation des clients": ["segmentation des clients"],
    "Semi-conducteurs": ["semi-conducteurs"],
    "Serbe": ["serbe"],
    "Sertissage": ["sertissage"],
    "Serveurs mandataires": ["serveurs mandataires"],
    "Service administratif": ["service administratif"],
    "Service en chambre": ["service en chambre"],
    "Services de covoiturage": ["services de covoiturage"],
    "Services d’annuaire": ["services dannuaire"],
    "Services web": ["services web"],
    "Shell script": ["shell script"],
    "Shiatsu": ["shiatsu"],
    "Signalisation ferroviaire": ["signalisation ferroviaire"],
    "SketchUp": ["sketchup"],
    "Smart grid": ["smart grid"],
    "Sociologie": ["sociologie"],
    "Sociologie des organisations": ["sociologie des organisations"],
    "Soins aigus": ["soins aigus"],
    "Sophrologie": ["sophrologie"],
    "Souscription en assurances": ["souscription en assurances"],
    "Soutien psychologique": ["soutien psychologique"],
    "Spectroscopie": ["spectroscopie"],
    "Stomatologie": ["stomatologie"],
    "Stratégie commerciale": ["strategie commerciale"],
    "Stratégie de développement": ["strategie de developpement"],
    "Stratégie de marque": ["strategie de marque"],
    "Stratégie de publication": ["strategie de publication"],
    "Stratégie d’externalisation": ["strategie dexternalisation"],
    "Stratégie internationale": ["strategie internationale"],
    "Stratégie éditoriale": ["strategie editoriale"],
    "Stratégies d'investissement": ["strategies d'investissement"],
    "Stratégies d'optimisation fiscale": ["strategies d'optimisation fiscale"],
    "Stratégies de tarification": ["strategies de tarification"],
    "Stratégies de vente": ["strategies de vente"],
    "Stratégies pédagogiques": ["strategies pedagogiques"],
    "Structure organisationnelle": ["structure organisationnelle"],
    "Suivi de chantier": ["suivi de chantier"],
    "Suivi des absences et retards": ["suivi des absences et retards"],
    "Suivi des actions correctives": ["suivi des actions correctives"],
    "Suivi des commandes": ["suivi des commandes"],
    "Suivi des contrats de maintenance": ["suivi des contrats de maintenance"],
    "Suivi des dépenses": ["suivi des depenses"],
    "Suivi des expéditions": ["suivi des expeditions"],
    "Suivi des innovations technologiques": ["suivi des innovations technologiques"],
    "Suivi des investissements": ["suivi des investissements"],
    "Suivi des procédures de sécurité": ["suivi des procedures de securite"],
    "Suivi des progrès des élèves": ["suivi des progres des eleves"],
    "Suivi des tendances du marché": ["suivi des tendances du marche"],
    "Suivi des tendances technologiques": ["suivi des tendances technologiques"],
    "Suivi des vaccinations": ["suivi des vaccinations"],
    "Suivi des évolutions réglementaires": ["suivi des evolutions reglementaires"],
    "Suivi et évaluation de projets": ["suivi et evaluation de projets"],
    "Support aux changements": ["support aux changements"],
    "Support technique informatique": ["support technique informatique"],
    "Support utilisateur": ["support utilisateur"],
    "Surveillance de l'environnement": ["surveillance de l'environnement"],
    "Surveillance des marchés financiers": ["surveillance des marches financiers"],
    "Surveillance des performances": ["surveillance des performances"],
    "Surveillance et gestion des incidents": ["surveillance et gestion des incidents"],
    "Surveillance météorologique": ["surveillance meteorologique"],
    "Surveillance vidéo": ["surveillance video"],
    "Suédois": ["suedois"],
    "Symfony2": ["symfony2"],
    "Synoptique": ["synoptique"],
    "Système d'exploitation Windows": ["systeme d'exploitation windows"],
    "Système de défense": ["systeme de defense"],
    "Système de santé": ["systeme de sante"],
    "Système numérique": ["systeme numerique"],
    "Système temps réel": ["systeme temps reel"],
    "Systèmes asservis": ["systemes asservis"],
    "Systèmes automatisés": ["systemes automatises"],
    "Systèmes d'exploitation informatique": ["systemes d'exploitation informatique"],
    "Systèmes d'information géographique": ["systemes d'information geographique"],
    "Systèmes de commande": ["systemes de commande"],
    "Systèmes de refroidissement": ["systemes de refroidissement"],
    "Systèmes de suspension": ["systemes de suspension"],
    "Systèmes de sécurité incendie": ["systemes de securite incendie"],
    "Systèmes d’alarme": ["systemes dalarme"],
    "Systèmes et logiciels": ["systemes et logiciels"],
    "Systèmes multimédia": ["systemes multimedia"],
    "Systèmes mécaniques": ["systemes mecaniques"],
    "Systèmes numériques": ["systemes numeriques"],
    "Systèmes photovoltaïques": ["systemes photovoltaiques"],
    "Sécurisation des marchandises": ["securisation des marchandises"],
    "Sécurité des applications web": ["securite des applications web"],
    "Sécurité des données": ["securite des donnees"],
    "Sécurité des informations": ["securite des informations"],
    "Sécurité des infrastructures critiques": ["securite des infrastructures critiques"],
    "Sécurité des installations": ["securite des installations"],
    "Sécurité des paiements en ligne": ["securite des paiements en ligne"],
    "Sécurité des procédés industriels": ["securite des procedes industriels"],
    "Sécurité des réseaux sans fil": ["securite des reseaux sans fil"],
    "Sécurité des systèmes embarqués": ["securite des systemes embarques"],
    "Sécurité des systèmes informatiques": ["securite des systemes informatiques"],
    "Sécurité des transactions électroniques": ["securite des transactions electroniques"],
    "Sécurité physique des datacenters": ["securite physique des datacenters"],
    "Sécurité sous-marine": ["securite sous-marine"],
    "Sémantique": ["semantique"],
    "Sémiologie": ["semiologie"],
    "Séries temporelles": ["series temporelles"],
    "Sérigraphie": ["serigraphie"],
    "THC Hydra": ["thc hydra"],
    "Taleo": ["taleo"],
    "Tamoul": ["tamoul"],
    "Taux de disponibilité": ["taux de disponibilite"],
    "Taxonomie": ["taxonomie"],
    "Tchèque": ["tcheque"],
    "Technique de production": ["technique de production"],
    "Techniques commerciales": ["techniques commerciales"],
    "Techniques d'impression": ["techniques d'impression"],
    "Techniques d'écriture": ["techniques d'ecriture"],
    "Techniques d'évaluation": ["techniques d'evaluation"],
    "Techniques de biochimie": ["techniques de biochimie"],
    "Techniques de construction": ["techniques de construction"],
    "Techniques de diagnostic": ["techniques de diagnostic"],
    "Techniques de détection": ["techniques de detection"],
    "Techniques de facilitation": ["techniques de facilitation"],
    "Techniques de formation": ["techniques de formation"],
    "Techniques de gestion administrative": ["techniques de gestion administrative"],
    "Techniques de growth hacking": ["techniques de growth hacking"],
    "Techniques de management": ["techniques de management"],
    "Techniques de masquage": ["techniques de masquage"],
    "Techniques de modélisation": ["techniques de modelisation"],
    "Techniques de nettoyage": ["techniques de nettoyage"],
    "Techniques de numérisation": ["techniques de numerisation"],
    "Techniques de prévision": ["techniques de prevision"],
    "Techniques de soudure": ["techniques de soudure"],
    "Techniques du génie": ["techniques du genie"],
    "Techniques d’audit": ["techniques daudit"],
    "Techniques numériques": ["techniques numeriques"],
    "Techniques éditoriales": ["techniques editoriales"],
    "Technologie aéronautique": ["technologie aeronautique"],
    "Technologie de l'internet": ["technologie de l'internet"],
    "Technologie d’imagerie médicale": ["technologie dimagerie medicale"],
    "Technologie informatique": ["technologie informatique"],
    "Technologies HADOOP": ["technologies hadoop"],
    "Technologies durables": ["technologies durables"],
    "Technologies d’apprentissage": ["technologies dapprentissage"],
    "Technologies embarquées": ["technologies embarquees"],
    "Technologies informatiques": ["technologies informatiques"],
    "Technologies numériques": ["technologies numeriques"],
    "Technologies sans fil": ["technologies sans fil"],
    "Technologies télécoms": ["technologies telecoms"],
    "Technologies émergentes": ["technologies emergentes"],
    "Terminologie": ["terminologie"],
    "Terminologie juridique": ["terminologie juridique"],
    "Tests physiques": ["tests physiques"],
    "Tests psychométriques": ["tests psychometriques"],
    "Thermique": ["thermique"],
    "Thermodynamique": ["thermodynamique"],
    "Thélia": ["thelia"],
    "Théologie": ["theologie"],
    "Théorie des contraintes": ["theorie des contraintes"],
    "Théorie des jeux": ["theorie des jeux"],
    "Théorie des probabilités": ["theorie des probabilites"],
    "Théorie des systèmes": ["theorie des systemes"],
    "Titres de transports": ["titres de transports"],
    "Topométrie": ["topometrie"],
    "Torréfaction de café": ["torrefaction de cafe"],
    "Tournage sur bois": ["tournage sur bois"],
    "Toxicologie": ["toxicologie"],
    "Traduction automatique": ["traduction automatique"],
    "Traitement des commandes": ["traitement des commandes"],
    "Traitement des formalités administratives": ["traitement des formalites administratives"],
    "Traitement des opérations sur titres": ["traitement des operations sur titres"],
    "Traitement des signaux": ["traitement des signaux"],
    "Traitement numérique": ["traitement numerique"],
    "Traitement thermique": ["traitement thermique"],
    "Trajectographie": ["trajectographie"],
    "Transferts thermiques": ["transferts thermiques"],
    "Transfusion sanguine": ["transfusion sanguine"],
    "Transport ferroviaire": ["transport ferroviaire"],
    "Transport scolaire": ["transport scolaire"],
    "Travail des métaux": ["travail des metaux"],
    "Travail social clinique": ["travail social clinique"],
    "Traçabilité des produits": ["tracabilite des produits"],
    "Turc": ["turc"],
    "Typographie": ["typographie"],
    "Typologie de clientèle": ["typologie de clientele"],
    "Télougou": ["telougou"],
    "Télédétection": ["teledetection"],
    "Télémarketing": ["telemarketing"],
    "Téléprocédures": ["teleprocedures"],
    "Tôlerie": ["tolerie"],
    "Ukrainien": ["ukrainien"],
    "Unreal Engine": ["unreal engine"],
    "Urbanisation des systèmes d'information": ["urbanisation des systemes d'information"],
    "Utilisation d'outils de diagnostic": ["utilisation d'outils de diagnostic"],
    "Utilisation de frameworks de test": ["utilisation de frameworks de test"],
    "Utilisation de logiciels de gestion": ["utilisation de logiciels de gestion"],
    "Utilisation de logiciels spécialisés": ["utilisation de logiciels specialises"],
    "Utilisation de tableaux de bord": ["utilisation de tableaux de bord"],
    "VB.NET": ["vb.net"],
    "VBScript": ["vbscript"],
    "Vagrant": ["vagrant"],
    "Valeurs mobilières": ["valeurs mobilieres"],
    "Veille réglementaire continue": ["veille reglementaire continue"],
    "Veille stratégique": ["veille strategique"],
    "Veille technologique en BI": ["veille technologique en bi"],
    "Veille technologique et innovation": ["veille technologique et innovation"],
    "Veille économique": ["veille economique"],
    "Vente multiniveau": ["vente multiniveau"],
    "Verrerie": ["verrerie"],
    "Vidange": ["vidange"],
    "Vietnamien": ["vietnamien"],
    "Virtualisation des serveurs": ["virtualisation des serveurs"],
    "Visioconférences": ["visioconferences"],
    "Vision par ordinateur": ["vision par ordinateur"],
    "Visualisation de données": ["visualisation de donnees"],
    "Viticulture": ["viticulture"],
    "Véhicules utilitaires": ["vehicules utilitaires"],
    "WLangage": ["wlangage"],
    "Wallon": ["wallon"],
    "Web dynamique": ["web dynamique"],
    "Web sémantique": ["web semantique"],
    "XQuery": ["xquery"],
    "Xcode": ["xcode"],
    "Zbrush": ["zbrush"],
    "Économie circulaire": ["economie circulaire"],
    "Économie du développement": ["economie du developpement"],
    "Économie mathématique": ["economie mathematique"],
    "Économies d’énergie": ["economies denergie"],
    "Écritures comptables": ["ecritures comptables"],
    "Éditeur audio": ["editeur audio"],
    "Électrochimie": ["electrochimie"],
    "Électronique grand public": ["electronique grand public"],
    "Énergie nucléaire": ["energie nucleaire"],
    "Énergie solaire": ["energie solaire"],
    "Équipement d’interconnexion réseau": ["equipement dinterconnexion reseau"],
    "Équipements de protection": ["equipements de protection"],
    "États financiers": ["etats financiers"],
    "Éthique des données": ["ethique des donnees"],
    "Étiquetage des aliments": ["etiquetage des aliments"],
    "Étude de marché": ["etude de marche"],
    "Étude des tendances": ["etude des tendances"],
    "Études de droit": ["etudes de droit"],
    "Évènements sportifs": ["evenements sportifs"],
    "Œnologie": ["oenologie"],
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
#
# "projet social" found via a 33 574-profile production scan (2026-09-17):
# it's meant as the HR/labor-relations sense ("plan social d'entreprise"),
# but as a bare 2-word phrase it also matches inside the unrelated,
# extremely common CV job title "Chef de projet social media" -- the
# n-gram matcher has no way to tell "social" belongs to "social media"
# rather than being the end of the phrase.
_ROME_ALIAS_STOPWORDS: frozenset[str] = frozenset({"son", "projet social"})


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

    # Lower-priority layer: bulk ESCO vocabulary, same "fill gaps only"
    # rule as ROME above, and checked after it so a ROME alias always wins
    # a conflict (ROME's short keyword-style labels are the better fit for
    # this dictionary's exact-phrase matching — see _esco_skills()).
    for canonical, aliases in _esco_skills().items():
        for alias in aliases:
            key = _fold(alias)
            if key and len(key) >= 2 and key not in lookup:
                lookup[key] = canonical

    # Lowest-priority layer: hand-mapped O*NET "Hot Technology" tools --
    # see _onet_skills(). Checked last so nothing above it is ever
    # shadowed; in practice the generation script already excludes any
    # alias resolvable through an earlier layer.
    for canonical, aliases in _onet_skills().items():
        for alias in aliases:
            key = _fold(alias)
            if key and len(key) >= 2 and key not in lookup:
                lookup[key] = canonical

    for canonical, aliases in _ecf_skills().items():
        for alias in aliases:
            key = _fold(alias)
            if key and len(key) >= 2 and key not in lookup:
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
# were counted as missing hard skills alongside SAS/SQL/SGBD.
#
# Second pass (2026-09-11): cross-checked both this dict and the ROME import
# against France Travail's own RECTEC referential -- an official, EU-funded
# framework of 12 "compétences transversales" (transversal competencies)
# specifically designed to identify skills that apply across virtually every
# occupation regardless of domain (pôles communicationnel/organisationnel/
# réflexif: communiquer à l'oral/écrit, utiliser les ressources numériques,
# piloter l'activité, agir face à l'imprévu, coopérer, gérer les données
# mathématiques/budgétaires, traiter l'information, assurer les procédures
# et la qualité, construire son parcours professionnel, développer des
# compétences). Six more canonicals matched one of these 12 domains clearly
# enough to add; three borderline candidates (Planification, Coordination,
# Parties prenantes) were deliberately left out -- they have real,
# discriminating domain-specific use in project-management-heavy roles, and
# excluding them without concrete evidence of a production over-broadening
# case would risk the same class of error this fix addresses, just inverted.
#
# This is still a starting list, not an audit of the full 8500+-entry ROME
# import -- other entries in that vocabulary may be similarly over-broad and
# are not yet reviewed.
_GENERIC_SKILL_CANONICALS: frozenset[str] = frozenset({
    "Communication",
    "Service client",
    "Contrôle qualité",
    "Mathématiques",
    "Outils bureautiques",
    "Qualité",
    "Résolution de problèmes",
    "Présentation",
    "Ecoute active",
    "Gestion du temps",
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


_ESCO_SKILLS_PATH = Path(__file__).with_name("esco_skills_data.json")


@lru_cache(maxsize=1)
def _esco_skills() -> dict[str, list[str]]:
    """Bulk skill vocabulary from ESCO v1.2.1's French classification
    (skills_fr.csv), scoped to skillType=="knowledge" rows with a
    preferredLabel of at most 3 words.

    Unlike ROME's "referentiel savoir", ESCO's skill labels are mostly full
    task-phrase sentences ("gerer des demandes d'indemnisation"), not
    keyword-style terms -- see _rome_skills()'s docstring for why ROME was
    picked first. Importing all ~14k rows verbatim would mostly add dead
    weight (sentences that never match any CV/job text via find_skills()'s
    substring matching) and reintroduce the exact bare-generic-sector-word
    false positive already fixed once for ROME ("informatique", "finance"
    are real ESCO preferredLabels too). The word-count + skillType filter
    and a generic-word stoplist are applied once, offline, when generating
    esco_skills_data.json -- see backend/scripts is not committed (same as
    rome_skills_data.json's own one-off generator); only the filtered
    output is.

    Treated as a strictly lower-priority layer than both the hand-curated
    _SKILLS and the ROME bulk import: a conflicting alias from either of
    those always wins (see _build_lookup()).
    """
    try:
        with _ESCO_SKILLS_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("ESCO skills data file not found: %s", _ESCO_SKILLS_PATH)
        return {}


_ONET_SKILLS_PATH = Path(__file__).with_name("onet_skills_data.json")


@lru_cache(maxsize=1)
def _onet_skills() -> dict[str, list[str]]:
    """Named tools/technologies from O*NET 31.0's software_skills.csv
    (public bulk download, no API key needed: onetcenter.org/database.html),
    filtered to Hot Technology=="Y" (O*NET's own curation flag for
    prominent/trending tools) then hand-mapped to clean canonical/alias
    pairs -- only ~100 entries, small enough to hand-review like _SKILLS
    rather than bulk-imported like ROME/ESCO. English-labelled (US
    Dept. of Labor source) but that's immaterial here: these are product/
    brand names (Kubernetes, Snowflake, Terraform...), not translated
    skill descriptions, so they match the same in French CV/job text.

    Lowest-priority layer, checked last: a conflicting alias from
    _SKILLS, ROME, or ESCO always wins (see _build_lookup()). In practice
    there's no real conflict -- the generation script only ever wrote an
    entry here for aliases not already resolvable through those layers.
    """
    try:
        with _ONET_SKILLS_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("O*NET skills data file not found: %s", _ONET_SKILLS_PATH)
        return {}


_ECF_SKILLS_PATH = Path(__file__).with_name("ecf_skills_data.json")


@lru_cache(maxsize=1)
def _ecf_skills() -> dict[str, list[str]]:
    """The European e-Competence Framework (e-CF) 3.0's 40 ICT
    competences (CWA 16234-1:2014, CEN), French edition -- a small,
    fixed, official EU standard, not a bulk vocabulary import. Hand-
    reviewed like O*NET's Hot Technology subset: "Innovation" and
    "Tests" excluded as too generic standalone (same risk class as
    "informatique"/"migration"), everything else kept as its own
    multi-word French phrase, which is inherently low false-positive
    risk (see _rome_skills()'s docstring on why short EXACT phrases,
    not bare single words, are the safe shape for this dictionary).

    Lowest-priority layer alongside O*NET, checked last: a conflicting
    alias from any earlier layer always wins (see _build_lookup()).
    """
    try:
        with _ECF_SKILLS_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("e-CF skills data file not found: %s", _ECF_SKILLS_PATH)
        return {}

    return added
