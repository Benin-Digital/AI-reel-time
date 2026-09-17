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
