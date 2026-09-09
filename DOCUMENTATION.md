# Documentation Technique — AI Real-Time

> Plateforme de matching CV ↔ Offres d'emploi en temps réel  
> FastAPI · pgvector · Redis · sentence-transformers · Vanilla JS

---

## Résumé

AI Real-Time est une plateforme de recrutement intelligente qui automatise la mise en correspondance entre candidats et offres d'emploi.

Les CVs et les offres d'emploi sont déposés dans des dossiers surveillés ou soumis via le dashboard. Le système les analyse automatiquement et calcule un **score de compatibilité de 0 à 100** pour chaque paire CV ↔ Offre. Les résultats sont disponibles en temps réel dans une interface web, accompagnés pour chaque match d'une explication lisible : points forts, éléments manquants, et extraits du document en preuve.

**Le scoring combine deux approches complémentaires :**
- Un moteur **lexical** qui compare les compétences, l'expérience, les langues et le type de contrat (70 %)
- Un modèle **sémantique** (cross-encoder ML) qui évalue l'adéquation globale indépendamment des termes exacts utilisés (30 %)

Les poids sont ajustés automatiquement selon le secteur détecté : les postes tech privilégient les compétences techniques, la santé les diplômes, le commercial l'expérience terrain.

**Stack technique :** API REST FastAPI (Python), PostgreSQL + pgvector pour la recherche vectorielle, Redis pour la file de traitement, sentence-transformers pour les embeddings (384 dim), spaCy pour l'extraction d'entités, Tesseract OCR pour les PDFs scannés, et un dashboard Vanilla JS sans framework.

| Composant | Technologie |
|-----------|-------------|
| API | FastAPI + uvicorn |
| Base de données | PostgreSQL 16 + pgvector |
| File de messages | Redis Streams |
| Embeddings | all-MiniLM-L6-v2 (384 dim) |
| Re-ranking | antoinelouis/crossencoder-camembert-base-mmarcoFR |
| NER | spaCy (fr_core_news_sm · en_core_web_sm) |
| OCR | Tesseract (fra+eng) |
| Frontend | Vanilla JS / HTML (8 composants) |
| Déploiement | Docker Compose (local + cloud) |

---

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture globale](#2-architecture-globale)
3. [Flux de données](#3-flux-de-données)
4. [Base de données](#4-base-de-données)
5. [API REST](#5-api-rest)
6. [Authentification & Sécurité](#6-authentification--sécurité)
7. [Algorithmes de scoring](#7-algorithmes-de-scoring)
8. [Services backend](#8-services-backend)
9. [Frontend](#9-frontend)
10. [Agent de synchronisation](#10-agent-de-synchronisation)
11. [Configuration](#11-configuration)
12. [Déploiement](#12-déploiement)
13. [Migrations Alembic](#13-migrations-alembic)
14. [Tests](#14-tests)

---

## 1. Vue d'ensemble

AI Real-Time est une plateforme de recrutement intelligente qui :

- **Surveille** des dossiers pour détecter l'arrivée de CV et d'offres d'emploi (PDF / DOCX / TXT)
- **Extrait** le texte brut (pypdf, python-docx, OCR Tesseract en fallback)
- **Profile** les documents (sections, compétences, expérience, langues) via NER spaCy
- **Génère** des embeddings vectoriels (sentence-transformers `all-MiniLM-L6-v2`, 384 dim)
- **Calcule** un score hybride lexical + sémantique pour chaque paire CV ↔ Offre
- **Expose** 40+ endpoints REST consommés par un tableau de bord Vanilla JS

```mermaid
graph LR
    A[📄 Fichier CV / Offre] --> B[File Watcher / POST /ingest]
    B --> C[Event Queue\nRedis Streams]
    C --> D[Event Worker]
    D --> E[Extraction\nPDF · DOCX · OCR]
    E --> F[Profiling\nspaCy NER]
    F --> G[Embeddings\nall-MiniLM-L6-v2]
    F --> H[Scoring hybride\nLexical + Sémantique]
    G --> H
    H --> I[(PostgreSQL\n+ pgvector)]
    I --> J[REST API\nFastAPI]
    J --> K[Dashboard\nVanilla JS]
```

---

## 2. Architecture globale

### 2.1 Vue des composants

```mermaid
flowchart TD
    A[🌐 Navigateur\nVanilla JS] --> B[CORS · Auth · Rate Limit\nMiddlewares]
    C[🤖 Sync Agent\nsync_agent.py] --> B

    B --> D[40+ Endpoints REST\nFastAPI Routes]

    D --> E[Extraction\nPDF · DOCX · OCR]
    D --> F[Profiling\nspaCy NER]
    D --> G[Embeddings\nall-MiniLM-L6-v2]
    D --> H[Scoring hybride\nLexical + Cross-Encoder]

    E & F & G & H --> I[(PostgreSQL\n+ pgvector)]

    J[📁 Dossiers surveillés\ncv/ · job/] --> K[LocalFolderWatcher\nwatchdog]
    K --> L[Event Queue\nRedis Streams]
    L --> M[Event Worker\nthread retry × 3]
    M --> E

    I --> D
```

### 2.2 Structure des répertoires

```
AI reel-time/
├── backend/
│   ├── app/
│   │   ├── main.py          # 40+ endpoints FastAPI
│   │   ├── models.py        # ORM SQLAlchemy (13 tables)
│   │   ├── schemas.py       # Pydantic I/O
│   │   ├── settings.py      # Config (AI_REALTIME_* env vars)
│   │   ├── auth.py          # JWT HS256 + bcrypt
│   │   ├── security.py      # API key + rate limiting
│   │   ├── db.py            # Session SQLAlchemy
│   │   ├── observability.py # Métriques Prometheus
│   │   └── services/
│   │       ├── extraction.py    # PDF / DOCX / TXT + OCR
│   │       ├── embeddings.py    # Vecteurs 384-dim
│   │       ├── scoring.py       # Score hybride
│   │       ├── structured.py    # Profiling NER (1060 lignes)
│   │       ├── matcher.py       # Cross-encoder + scores structurés
│   │       ├── parser.py        # Détection de domaine + parsing
│   │       ├── taxonomy.py      # Taxonomie des compétences
│   │       ├── explain.py       # Explication des matchs
│   │       ├── worker.py        # Thread consommateur
│   │       ├── watcher.py       # Surveillance FS watchdog
│   │       ├── event_queue.py   # Redis Streams / mémoire
│   │       ├── rate_limit.py    # Sliding window Redis
│   │       └── fingerprint.py   # SHA256 déduplication
│   ├── alembic/             # 12 migrations
│   ├── tests/               # Pytest
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── index.html           # Shell HTML + modales
│   ├── js/
│   │   ├── main.js          # Bootstrap + routage
│   │   ├── auth.js          # Login / logout / JWT
│   │   ├── api.js           # Client HTTP
│   │   ├── store.js         # État client
│   │   ├── router.js        # Routage panels
│   │   ├── components/      # 8 composants fonctionnels
│   │   └── utils/           # format · dom · upload · docs
│   └── styles/main.css
├── agent/
│   └── sync_agent.py        # Watcher standalone → POST /ingest
├── deploy/
│   ├── local/docker-compose.local.yml
│   └── cloud/docker-compose.cloud.yml
└── storage/
    ├── cv/                  # Dossier surveillé CVs
    ├── job/                 # Dossier surveillé Offres
    └── archive/             # Sessions exportées
```

---

## 3. Flux de données

### 3.1 Pipeline complet (ingestion → matching)

```mermaid
sequenceDiagram
    participant FS as Fichier Système
    participant WT as File Watcher
    participant Q  as Event Queue (Redis)
    participant WK as Event Worker
    participant EX as Extraction
    participant PR as Profiling (NER)
    participant EM as Embeddings
    participant SC as Scoring
    participant DB as PostgreSQL

    FS->>WT: Nouveau fichier détecté (watchdog)
    WT->>Q: enqueue_event(path, type)
    Q-->>WK: dequeue_event() [polling 1s]
    WK->>EX: extract_text(path)
    EX->>DB: UPSERT extracted_text
    EX-->>WK: ExtractedTextRead
    WK->>PR: build_document_profile(text)
    PR->>DB: UPDATE parsed_profile (JSON)
    PR-->>WK: StructuredDocument
    WK->>EM: embed_texts(chunks)
    EM->>DB: UPSERT cv_embeddings / job_embeddings
    WK->>SC: match_cv_to_job(cv_text, job_text)
    SC-->>WK: MatchResult {score, skills, semantic...}
    WK->>DB: UPSERT match_results
```

### 3.2 Flux d'authentification

```mermaid
sequenceDiagram
    participant U as Utilisateur
    participant FE as Frontend
    participant API as FastAPI
    participant DB as PostgreSQL

    U->>FE: Saisit email + password
    FE->>API: POST /auth/login {email, password}
    API->>DB: SELECT user WHERE email=?
    DB-->>API: User {hash, role}
    API->>API: bcrypt.verify(password, hash)
    alt Succès
        API-->>FE: {access_token, token_type, user}
        FE->>FE: localStorage.setItem(token)
        FE-->>U: Affiche tableau de bord
    else Échec
        API-->>FE: 401 Unauthorized
        FE-->>U: Message d'erreur
    end

    Note over FE,API: Requêtes suivantes
    FE->>API: GET /cv-documents\nAuthorization: Bearer <token>
    API->>API: decode_jwt(token)
    API->>DB: SELECT user WHERE id=sub
    DB-->>API: User
    API-->>FE: 200 OK + données
```

### 3.3 Flux de scoring hybride

```mermaid
flowchart TD
    A[CV text + Job text] --> B[Profiling structuré]
    B --> C[Sections extraites\nskills · expérience · langues]
    B --> D[Termes de compétences\ntaxonomie + fuzzy match]

    C --> E[Scores composants]
    D --> E

    E --> E1[Score lexical\nJaccard pondéré]
    E --> E2[Couverture skills]
    E --> E3[Compétences requises]
    E --> E4[Expérience années]
    E --> E5[Langues]
    E --> E6[Type contrat]

    A --> F[Cross-Encoder\ncamembert-base-mmarcoFR]
    F --> G[Score sémantique\n0.0 → 1.0]

    E1 & E2 & E3 & E4 & E5 & E6 --> H[Pondération domaine]
    G --> H

    H --> I[Score final\n0 → 100]

    I --> J{Domaine détecté}
    J -->|tech| K[skills × 0.40\nsemantic × 0.35]
    J -->|santé| L[education × 0.20\nsemantic × 0.35]
    J -->|commercial| M[experience × 0.20\nsemantic × 0.35]
    J -->|défaut| N[semantic × 0.40\nskills × 0.30]
```

---

## 4. Base de données

### 4.1 Schéma Entité-Relation

```mermaid
erDiagram
    users {
        int id PK
        string email UK
        string password_hash
        string first_name
        string last_name
        string role
        bool is_active
        datetime created_at
        datetime updated_at
    }

    event_logs {
        int id PK
        string source
        string event_type
        string path
        string fingerprint
        datetime observed_at
        datetime created_at
    }

    extracted_text {
        int id PK
        string file_path UK
        string content_hash
        text extracted_text
        string extraction_method
        bool extraction_success
        string error_message
        json parsed_profile
        string parsed_profile_hash
        datetime parsed_profile_updated_at
        datetime created_at
        datetime updated_at
    }

    cv_documents {
        int id PK
        string path UK
        string content_hash
        string status
        string last_error
        int session_id FK
        datetime created_at
        datetime updated_at
    }

    job_documents {
        int id PK
        string path UK
        string content_hash
        string status
        string last_error
        int session_id FK
        datetime created_at
        datetime updated_at
    }

    cv_embeddings {
        int id PK
        int cv_id FK
        string content_hash
        vector embedding
        datetime created_at
        datetime updated_at
    }

    job_embeddings {
        int id PK
        int job_id FK
        string content_hash
        vector embedding
        datetime created_at
        datetime updated_at
    }

    match_results {
        int id PK
        int cv_id FK
        int job_id FK
        float score
        text common_keywords
        float score_semantic
        float score_skills
        float score_experience
        float score_education
        float score_languages
        float score_contract
        string match_domain
        datetime created_at
        datetime updated_at
    }

    match_feedback {
        int id PK
        int match_id FK
        string decision
        int rating
        string comment
        datetime created_at
        datetime updated_at
    }

    job_offers {
        int id PK
        string title
        json meta_keywords
        string contract_type
        string category
        string job_type
        json skills
        json strong_constraints
        json languages
        text description
        text rendered_text
        string status
        string published_document_path
        datetime created_at
        datetime updated_at
    }

    analysis_sessions {
        int id PK
        string name
        string description
        string status
        datetime closed_at
        datetime created_at
        datetime updated_at
    }

    parser_feedback {
        int id PK
        string kind
        int doc_id
        json corrections
        int user_id FK
        datetime created_at
        datetime updated_at
    }

    cv_documents ||--o{ cv_embeddings : "1 CV → 1 embedding"
    job_documents ||--o{ job_embeddings : "1 Job → 1 embedding"
    cv_documents ||--o{ match_results : "1 CV → N matchs"
    job_documents ||--o{ match_results : "1 Job → N matchs"
    match_results ||--o{ match_feedback : "1 match → N feedbacks"
    analysis_sessions ||--o{ cv_documents : "session ← CVs"
    analysis_sessions ||--o{ job_documents : "session ← Jobs"
    users ||--o{ parser_feedback : "user → feedbacks"
```

### 4.2 Index principaux

| Table | Index | Colonnes |
|-------|-------|----------|
| `cv_documents` | idx_cv_status | status |
| `cv_documents` | idx_cv_session | session_id |
| `job_documents` | idx_job_status | status |
| `match_results` | idx_match_cv_job | (cv_id, job_id) UNIQUE |
| `match_results` | idx_match_score | score DESC |
| `cv_embeddings` | hnsw_cv_embedding | embedding (HNSW cosine) |
| `job_embeddings` | hnsw_job_embedding | embedding (HNSW cosine) |
| `event_logs` | idx_event_path | path |

> Les index HNSW (Hierarchical Navigable Small World) permettent la recherche par similarité cosinus en O(log n).

---

## 5. API REST

### 5.1 Vue d'ensemble des endpoints

```mermaid
mindmap
  root((API\n:8000))
    Santé
      GET /health
      GET /ready
      GET /metrics
      GET /metrics/prometheus
      GET /queue-status
      GET /worker-status
    Auth
      POST /auth/login
      GET /auth/me
      GET /auth/users
      POST /auth/users
      PATCH /auth/users/id
    Ingestion
      POST /ingest
      POST /ingest/delete
      POST /ingest/delete-batch
      POST /extract
    CV
      POST /cv-profiles
      GET /cv-documents
      GET /cv-documents/id
      GET /cv-documents/id/details
      GET /cv-documents/id/pdf
      GET /cv-documents/id/parsed-json
    Offres
      POST /job-offers
      GET /job-documents
      GET /job-documents/id
      GET /job-documents/id/details
      GET /job-documents/id/pdf
    Matching
      GET /matches
      GET /matches/id
      GET /matches/id/explain
      POST /matches/id/feedback
      POST /matches/analyze
      GET /scoring/weights
    Sessions
      GET /sessions
      POST /sessions
      GET /sessions/id
      PATCH /sessions/id
      DELETE /sessions/id
      POST /sessions/id/assign
    Maintenance
      POST /maintenance/cleanup
      POST /maintenance/purge-orphans
      POST /maintenance/backfill-embeddings
```

### 5.2 Référence des endpoints

#### Santé & Monitoring

| Méthode | Path | Auth | Description |
|---------|------|------|-------------|
| GET | `/health` | — | État du service |
| GET | `/ready` | — | Vérif DB + Redis |
| GET | `/metrics` | JWT | Métriques JSON |
| GET | `/metrics/prometheus` | JWT | Format Prometheus |
| GET | `/queue-status` | JWT | Profondeur de la queue |
| GET | `/worker-status` | JWT | Statut du worker thread |

#### Authentification

| Méthode | Path | Auth | Body | Description |
|---------|------|------|------|-------------|
| POST | `/auth/login` | — | `{email, password}` | Retourne `access_token` |
| GET | `/auth/me` | JWT | — | Profil utilisateur |
| GET | `/auth/users` | Admin | — | Liste des utilisateurs |
| POST | `/auth/users` | Admin | `UserCreate` | Créer un utilisateur |
| PATCH | `/auth/users/{id}` | Admin | `UserUpdate` | Modifier rôle/infos |

#### Ingestion de fichiers

| Méthode | Path | Auth | Description |
|---------|------|------|-------------|
| POST | `/ingest` | JWT | Upload CV ou Offre (`multipart/form-data`, champ `folder=cv|job`) |
| POST | `/ingest/delete` | JWT | Supprimer un fichier par path |
| POST | `/ingest/delete-batch` | JWT | Suppression en lot |
| POST | `/extract` | JWT | Extraction de texte brut direct |

**Exemple requête upload :**
```http
POST /ingest
Authorization: Bearer <token>
Content-Type: multipart/form-data

folder=cv
file=@/path/to/cv.pdf
```

#### Documents CV

| Méthode | Path | Params | Description |
|---------|------|--------|-------------|
| POST | `/cv-profiles` | — | Publier un CV structuré (formulaire) |
| GET | `/cv-documents` | `offset, limit` | Liste paginée |
| GET | `/cv-documents/{id}` | — | Détail document |
| GET | `/cv-documents/{id}/details` | `limit=6` | Détail + top matchs + extraction |
| GET | `/cv-documents/{id}/pdf` | — | Fichier PDF original |
| GET | `/cv-documents/{id}/parsed-text` | — | Texte extrait |
| GET | `/cv-documents/{id}/parsed-pdf` | — | PDF OCR |
| GET | `/cv-documents/{id}/parsed-json` | — | Profil structuré JSON |

#### Matchs

| Méthode | Path | Params | Description |
|---------|------|--------|-------------|
| GET | `/matches` | `cv_id, job_id, min_score, max_score, sort, offset, limit` | Liste filtrée |
| GET | `/matches/{id}` | — | Détail d'un match |
| GET | `/matches/{id}/explain` | — | Explication (why_match, vigilance, evidence) |
| POST | `/matches/{id}/feedback` | — | Soumettre un avis (accept/reject/review) |
| POST | `/matches/analyze` | — | Score ad-hoc sans persistance |
| GET | `/scoring/weights` | — | Poids actuels de l'algorithme |

**Exemple réponse explain :**
```json
{
  "match_id": 42,
  "score": 78.5,
  "summary": "Bon match — 8 mots-clés communs",
  "why_match": ["Python présent", "3 ans d'expérience", "CDI compatible"],
  "vigilance": ["Docker manquant", "anglais non mentionné"],
  "evidence": ["Développé des APIs avec FastAPI..."],
  "keyword_hits": ["python", "fastapi", "sql", "docker"]
}
```

#### Recherche vectorielle

```http
POST /search
{
  "kind": "cv",
  "query": "développeur Python senior",
  "top_k": 10,
  "vector_weight": 0.7,
  "lexical_weight": 0.3
}
```

Retourne une liste de `SearchHit` triés par score combiné.

---

## 6. Authentification & Sécurité

### 6.1 Modèle d'autorisation

```mermaid
graph TD
    A[Requête HTTP] --> B{OPTIONS\nPreflight?}
    B -->|Oui| C[Autoriser\nCORS headers]
    B -->|Non| D{require_api_key?}
    D -->|Oui| E{X-API-Key valide?}
    E -->|Non| F[401 Invalid API key]
    E -->|Oui| G[Rate limit check]
    D -->|Non| G
    G -->|> 120 req/min| H[429 Rate limit exceeded]
    G -->|OK| I{auth_enabled?}
    I -->|Non| J[Autoriser]
    I -->|Oui| K{Authorization header?}
    K -->|Non| L{Path public?}
    L -->|/health /ready /auth/login| J
    L -->|autre| M[401 Authentication required]
    K -->|Oui| N[decode_jwt token]
    N -->|Invalide/Expiré| M
    N -->|Valide| O[Charger User depuis DB]
    O --> P{Rôle suffisant?}
    P -->|superadmin/admin/member| J
    P -->|Insuffisant| Q[403 Forbidden]
```

### 6.2 Rôles et permissions

| Action | member | admin | superadmin |
|--------|--------|-------|------------|
| Voir CV / Offres / Matchs | ✅ | ✅ | ✅ |
| Uploader des fichiers | ✅ | ✅ | ✅ |
| Soumettre du feedback | ✅ | ✅ | ✅ |
| Gérer les sessions | ✅ | ✅ | ✅ |
| Gérer les utilisateurs | ❌ | ✅ | ✅ |
| Maintenance / purge | ❌ | ❌ | ✅ |
| Créer des admins | ❌ | ❌ | ✅ |

### 6.3 Format du token JWT

```json
{
  "sub": "42",
  "role": "admin",
  "exp": 1718200000
}
```

Durée de validité : **12 heures** (720 minutes, configurable via `AI_REALTIME_JWT_ACCESS_TOKEN_MINUTES`).

---

## 7. Algorithmes de scoring

### 7.1 Architecture du scoring hybride

```mermaid
graph LR
    subgraph Entrée
        CV[Texte CV]
        JO[Texte Offre]
    end

    subgraph Profiling
        PR1[Sections\nextraction]
        PR2[Skill terms\ntaxonomie]
        PR3[NER spaCy\nentités nommées]
    end

    subgraph Lexical["Scoring Lexical (scoring.py)"]
        S1[Jaccard pondéré\nlexical_weight=0.18]
        S2[Skill overlap\nskill_weight=0.28]
        S3[Requis coverage\nmust_have_weight=0.22]
        S4[Expérience\nexperience_weight=0.12]
        S5[Langues\nlanguage_weight=0.06]
        S6[Contrat\ncontract_weight=0.05]
        S7[Résumé\nsummary_weight=0.04]
        S8[Formation\neducation_weight=0.05]
    end

    subgraph Sémantique["Scoring Sémantique (matcher.py)"]
        CE[Cross-Encoder\ncamembert-base-mmarcoFR]
        SEM[Score sémantique\n0.0 → 1.0]
    end

    subgraph Domaine
        DD[Détection domaine\n11 domaines]
        DW[Poids domaine\n5 profils]
    end

    CV --> PR1
    JO --> PR1
    PR1 --> PR2
    PR2 --> PR3
    PR3 --> S1 & S2 & S3 & S4 & S5 & S6 & S7 & S8
    CV --> CE
    JO --> CE
    CE --> SEM
    S1 & S2 & S3 & S4 & S5 & S6 & S7 & S8 --> DD
    SEM --> DD
    DD --> DW
    DW --> FINAL[Score final\n0 → 100]
```

### 7.2 Formule de scoring

```
score = Σ(composants × poids) + phrase_bonus − pénalités

Composants :
  lexical_overlap    × 0.18   # Jaccard mots en commun
  skill_overlap      × 0.28   # Compétences en commun / union
  required_coverage  × 0.22   # Compétences requises couvertes
  experience         × 0.12   # Adéquation années d'expérience
  language           × 0.06   # Couverture langues demandées
  contract           × 0.05   # Correspondance type contrat
  summary            × 0.04   # Jaccard résumés
  education          × 0.05   # Jaccard formations
  certifications     × 0.025  # Jaccard certifications
  nice_coverage      × 0.077  # Compétences souhaitées couvertes

Bonus :
  +0.05 par expression multi-mots trouvée (max +0.25)

Pénalités :
  −0.20 × ratio_compétences_requises_manquantes
  −0.05 si expérience insuffisante ou sur-qualification

Résultat clampé → [0, 100]
```

### 7.3 Poids par domaine

```mermaid
xychart-beta
    title "Poids skill vs sémantique par domaine"
    x-axis ["Tech", "Santé", "Commercial", "Finance/Légal", "Défaut"]
    y-axis "Poids" 0 --> 0.5
    bar [0.40, 0.25, 0.25, 0.25, 0.30]
    line [0.35, 0.35, 0.35, 0.35, 0.40]
```

> Barres = poids `skills` · Ligne = poids `semantic`

| Domaine | semantic | skills | exp | education | language | contract |
|---------|----------|--------|-----|-----------|----------|---------|
| tech | 0.35 | **0.40** | 0.12 | 0.08 | 0.03 | 0.02 |
| health | 0.35 | 0.25 | 0.12 | **0.20** | 0.05 | 0.03 |
| commercial | 0.35 | 0.25 | **0.20** | 0.10 | 0.05 | 0.05 |
| legal/finance | 0.35 | 0.25 | 0.12 | **0.20** | 0.05 | 0.03 |
| défaut | **0.40** | 0.30 | 0.12 | 0.08 | 0.05 | 0.05 |

### 7.4 Extraction de texte

```mermaid
flowchart TD
    A[Fichier reçu] --> B{Extension?}
    B -->|.pdf| C[pypdf extraction]
    B -->|.docx| D[python-docx\nparagraphes + tableaux]
    B -->|.txt| E[UTF-8 / latin-1]

    C --> F{len text < 20 ?}
    F -->|Oui| G[Tesseract OCR\n200 DPI · psm=6]
    F -->|Non| H[clean_text]
    G --> H
    D --> H
    E --> H

    H --> I[Fixe césures\n-\nword]
    I --> J[Déduplique\nlignes identiques]
    J --> K[Supprime bullets\net espaces]
    K --> L[Texte propre ✓]
```

---

## 8. Services backend

### 8.1 Vue des services

```mermaid
graph TB
    subgraph "services/"
        EXT[extraction.py\nPDF · DOCX · OCR]
        EMB[embeddings.py\nSentenceTransformer]
        SCO[scoring.py\nScore hybride]
        STR[structured.py\nProfiling + NER]
        MAT[matcher.py\nCross-Encoder]
        PAR[parser.py\nDétection domaine]
        TAX[taxonomy.py\nTaxonomie skills]
        EXP[explain.py\nExplication]
        WRK[worker.py\nThread consommateur]
        WAT[watcher.py\nFS watchdog]
        EVQ[event_queue.py\nRedis Streams]
        RLM[rate_limit.py\nSlidingWindow]
        FPR[fingerprint.py\nSHA256]
    end

    WAT --> EVQ
    EVQ --> WRK
    WRK --> EXT
    WRK --> STR
    WRK --> EMB
    WRK --> MAT
    MAT --> PAR
    MAT --> TAX
    MAT --> SCO
    SCO --> EXP
```

### 8.2 structured.py — Profiling de documents

Le service le plus complexe (1060 lignes). Il construit un `StructuredDocument` :

```mermaid
flowchart LR
    T[Texte brut] --> HD[Détection\nde sections]
    HD --> SEC{Section}
    SEC -->|résumé| SUM[summary_text]
    SEC -->|compétences| SKI[skills_text]
    SEC -->|expérience| EXP[experience_text]
    SEC -->|formation| EDU[education_text]
    SEC -->|langues| LNG[languages_text]
    SEC -->|requis/job| REQ[job_required_text]

    T --> NER[spaCy NER\nfr_core_news_sm]
    NER --> PER[person_name]
    NER --> ORG[organization_terms]
    NER --> LOC[location_terms]

    T --> RGX[Regex Expérience]
    RGX --> YRS[experience_years]

    SKI --> TRM[Extraction terms\ntaxonomie + fuzzy]
    TRM --> STR[skill_terms\nrequired_skill_terms]
```

**Détection de sections (12 types) :**

| Pattern | Section |
|---------|---------|
| expérience, experience, parcours | `experience` |
| formation, diplôme, études, education | `education` |
| compétences, skills, expertise | `skills` |
| résumé, profil, about, summary | `summary` |
| langues, languages | `languages` |
| certifications, diplômes | `certifications` |
| requis, required, obligatoire | `job_required` |
| souhaité, nice-to-have, plus | `job_nice` |
| contrat, type de poste | `contract` |

### 8.3 worker.py — Traitement des événements

```mermaid
stateDiagram-v2
    [*] --> Idle : Worker démarré
    Idle --> Dequeue : Poll queue (1s)
    Dequeue --> Idle : Queue vide
    Dequeue --> Processing : Événement reçu
    Processing --> Success : Handler OK
    Processing --> RetryWait : Exception (tentative 1/2)
    RetryWait --> Processing : Backoff exp. (0.5s → 10s)
    Processing --> Failed : 3 tentatives épuisées
    Success --> Ack : Marquer comme traité
    Failed --> Ack : ack_on_failure = true
    Ack --> Idle
```

### 8.4 event_queue.py — File de messages

```mermaid
graph LR
    subgraph Producers
        WT[Watcher]
        API[POST /ingest]
    end

    subgraph Queue
        RS{Redis\ndisponible?}
        RS -->|Oui| STREAM[Redis Streams\nXADD · XREAD · XACK]
        RS -->|Non| MEM[In-Memory Queue\ndeque max 1000]
    end

    subgraph Consumers
        WK[Event Worker]
    end

    WT --> RS
    API --> RS
    STREAM --> WK
    MEM --> WK
```

---

## 9. Frontend

### 9.1 Architecture des composants

```mermaid
graph TB
    subgraph Shell
        HTML[index.html\nAuth Gate + App Shell]
        CSS[styles/main.css\nThème Dark/Light]
    end

    subgraph Core["Core JS"]
        MAIN[main.js\nInit + routing]
        AUTH[auth.js\nJWT management]
        API[api.js\nHTTP client]
        STORE[store.js\nÉtat client]
        ROUTER[router.js\nPanel routing]
    end

    subgraph Components["Composants (js/components/)"]
        DASH[dashboard.js\nMétriques temps réel]
        CVLIB[cv-library.js\nBibliothèque CVs]
        PUBCV[publish-cv.js\nPublier CV]
        JOBL[job-library.js\nBibliothèque Offres]
        PUBJOB[publish-job.js\nPublier Offre]
        MATCH[matches.js\nRésultats matching]
        ARCH[archives.js\nSessions d'analyse]
        ADM[admin.js\nGestion utilisateurs]
    end

    subgraph Utils
        FMT[format.js]
        DOM[dom.js]
        UPL[upload.js]
        DOCS[docs.js]
    end

    HTML --> MAIN
    MAIN --> AUTH
    MAIN --> ROUTER
    ROUTER --> DASH & CVLIB & PUBCV & JOBL & PUBJOB & MATCH & ARCH & ADM
    DASH & CVLIB & PUBJOB & MATCH --> API
    API --> AUTH
    DASH & CVLIB --> STORE
    Components --> Utils
```

### 9.2 Composants principaux

| Composant | Endpoints consommés | Fonctionnalité |
|-----------|---------------------|----------------|
| `dashboard.js` | `/health`, `/queue-status`, `/worker-status`, `/metrics` | Uptime, stats temps réel (refresh 5s) |
| `cv-library.js` | `GET /cv-documents`, `GET /cv-documents/{id}/details` | Liste + filtres + détail CV |
| `publish-cv.js` | `POST /cv-profiles`, `POST /ingest` | Formulaire + upload CV |
| `job-library.js` | `GET /job-documents`, `GET /job-documents/{id}/details` | Liste + filtres + détail offre |
| `publish-job.js` | `POST /job-offers`, `POST /ingest` | Formulaire offre structurée |
| `matches.js` | `GET /matches`, `GET /matches/{id}/explain`, `POST /matches/{id}/feedback` | Tableau matchs + explication + feedback |
| `archives.js` | `GET/POST /sessions`, `POST /sessions/{id}/assign` | Sessions d'analyse groupées |
| `admin.js` | `GET/POST/PATCH /auth/users` | Gestion des comptes (admin+) |

### 9.3 Routing côté client

```mermaid
stateDiagram-v2
    [*] --> AuthCheck : Chargement page
    AuthCheck --> Login : Token absent/expiré
    AuthCheck --> Dashboard : Token valide

    Login --> Dashboard : POST /auth/login OK

    Dashboard --> CVLibrary : Clic "CVs"
    Dashboard --> PublishCV : Clic "Publier CV"
    Dashboard --> JobLibrary : Clic "Offres"
    Dashboard --> PublishJob : Clic "Publier Offre"
    Dashboard --> Matches : Clic "Matchs"
    Dashboard --> Archives : Clic "Sessions"
    Dashboard --> Admin : Clic "Admin" [admin+]

    CVLibrary --> Dashboard : Retour
    Matches --> MatchExplain : Clic ligne match
    MatchExplain --> Matches : Fermer modale
```

---

## 10. Agent de synchronisation

L'agent (`agent/sync_agent.py`) est un programme **standalone** (sans Docker) qui surveille des dossiers locaux et pousse les fichiers vers l'API.

```mermaid
sequenceDiagram
    participant FS as Dossier local
    participant AG as sync_agent.py
    participant ST as state.json
    participant API as POST /ingest

    AG->>FS: Surveille cv_dir + job_dir (watchdog)
    FS-->>AG: Nouveau fichier détecté

    AG->>AG: Calcule SHA256(fichier)
    AG->>ST: Hash déjà connu ?
    alt Nouveau ou modifié
        AG->>API: POST /ingest\n(folder=cv, file=...)
        API-->>AG: 200 OK
        AG->>ST: Sauvegarder hash
    else Inchangé
        AG->>AG: Ignorer
    end

    Note over AG: Toutes les 5 min (resync)
    AG->>FS: Scan complet dossiers
    AG->>AG: Fichiers supprimés → POST /ingest/delete

    Note over AG: Retry queue
    loop Toutes les 30s
        AG->>AG: Reprendre uploads échoués
    end
```

**Usage :**

```bash
python agent/sync_agent.py \
  --cv-dir /chemin/vers/cv \
  --job-dir /chemin/vers/offres \
  --api-base http://localhost:8000 \
  --api-key MA_CLE_API
```

**Options disponibles :**

| Option | Défaut | Description |
|--------|--------|-------------|
| `--cv-dir` | — | Dossier CVs à surveiller |
| `--job-dir` | — | Dossier offres à surveiller |
| `--api-base` | `http://localhost:8000` | URL de l'API |
| `--api-key` | — | Clé API (header `X-API-Key`) |
| `--debounce` | `1.0` | Délai anti-rebond (secondes) |
| `--retry-interval` | `30` | Intervalle retry échecs (secondes) |
| `--resync-interval` | `300` | Rescan complet (secondes) |

---

## 11. Configuration

Toutes les variables d'environnement utilisent le préfixe `AI_REALTIME_`.

### 11.1 Variables essentielles

```bash
# Base de données
AI_REALTIME_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db

# Cache / Queue
AI_REALTIME_REDIS_URL=redis://localhost:6379/0
AI_REALTIME_QUEUE_BACKEND=stream   # stream | memory

# Sécurité
AI_REALTIME_JWT_SECRET_KEY=votre-secret-256-bits
AI_REALTIME_JWT_ACCESS_TOKEN_MINUTES=720
AI_REALTIME_AUTH_ENABLED=true
AI_REALTIME_REQUIRE_API_KEY=false
AI_REALTIME_API_KEYS=cle1,cle2

# Dossiers surveillés
AI_REALTIME_WATCH_CV_DIR=/srv/ai-realtime/storage/cv
AI_REALTIME_WATCH_JOB_DIR=/srv/ai-realtime/storage/job

# CORS
AI_REALTIME_CORS_ALLOW_ORIGINS=*
AI_REALTIME_CORS_ALLOW_METHODS=GET,POST,PUT,PATCH,DELETE,OPTIONS
AI_REALTIME_CORS_ALLOW_HEADERS=Authorization,Content-Type,X-API-Key
```

### 11.2 Modèles ML

```bash
AI_REALTIME_EMBEDDING_ENABLED=true
AI_REALTIME_EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
AI_REALTIME_EMBEDDING_DEVICE=cpu   # cpu | cuda
AI_REALTIME_EMBEDDING_DIM=384
AI_REALTIME_EMBEDDING_BATCH_SIZE=16

AI_REALTIME_NER_ENABLED=true
AI_REALTIME_NER_MODEL_MAP=fr:fr_core_news_sm,en:en_core_web_sm

AI_REALTIME_CROSSENCODER_ENABLED=true
AI_REALTIME_CROSSENCODER_MODEL_NAME=antoinelouis/crossencoder-camembert-base-mmarcoFR
```

### 11.3 Poids de scoring

```bash
# Scoring hybride global
AI_REALTIME_HYBRID_SCORING_ENABLED=true
AI_REALTIME_HYBRID_VECTOR_WEIGHT=0.3
AI_REALTIME_HYBRID_LEXICAL_WEIGHT=0.7

# Composants du scoring structuré
AI_REALTIME_STRUCTURED_LEXICAL_WEIGHT=0.18
AI_REALTIME_STRUCTURED_SKILL_WEIGHT=0.28
AI_REALTIME_STRUCTURED_MUST_HAVE_WEIGHT=0.22
AI_REALTIME_STRUCTURED_EXPERIENCE_WEIGHT=0.12
AI_REALTIME_STRUCTURED_LANGUAGE_WEIGHT=0.06
AI_REALTIME_STRUCTURED_CONTRACT_WEIGHT=0.05
AI_REALTIME_STRUCTURED_SUMMARY_WEIGHT=0.04
AI_REALTIME_STRUCTURED_EDUCATION_WEIGHT=0.05

# Pénalités
AI_REALTIME_STRUCTURED_MISSING_REQUIRED_PENALTY=0.20
AI_REALTIME_STRUCTURED_MISSING_EXPERIENCE_PENALTY=0.10
```

### 11.4 OCR (Tesseract)

```bash
AI_REALTIME_OCR_MIN_TEXT_LENGTH=20   # Déclenche OCR si texte < 20 chars
AI_REALTIME_OCR_DPI=200
AI_REALTIME_OCR_LANGUAGES=fra+eng
AI_REALTIME_OCR_PSM=6                # Page Segmentation Mode
AI_REALTIME_OCR_OEM=3                # OCR Engine Mode
```

### 11.5 Rétention des données

```bash
AI_REALTIME_RETENTION_EVENT_DAYS=30
AI_REALTIME_RETENTION_EXTRACTION_DAYS=30
AI_REALTIME_RETENTION_SCORE_DAYS=60
```

---

## 12. Déploiement

### 12.1 Déploiement local (Docker Compose)

```mermaid
graph TB
    subgraph "docker-compose.local.yml"
        API["api\n:8000\nFastAPI + uvicorn"]
        PG["postgres\n:5432\npgvector/pgvector:pg16"]
        RD["redis\n:6379\nredis:8-alpine"]
    end

    API --> PG
    API --> RD
    BROWSER["Navigateur\n:5173"] --> API
    FS_CV["/storage/cv"] --> API
    FS_JOB["/storage/job"] --> API
```

**Commandes :**

```bash
# Démarrer
docker compose -f deploy/local/docker-compose.local.yml up -d --build

# Migrations
docker exec airealtime-api alembic -c /app/alembic.ini upgrade head

# Vérifier
curl -s http://localhost:8000/health

# Arrêter + supprimer volumes
docker compose -f deploy/local/docker-compose.local.yml down -v
```

### 12.2 Déploiement cloud

```bash
# Copier et configurer l'env
cp deploy/cloud/.env.cloud.example deploy/cloud/.env.cloud
# Éditer .env.cloud : DB_URL, JWT_SECRET, etc.

# Démarrer
docker compose --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml up -d --build

# Migrations
docker compose --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml run --rm api \
  alembic -c /app/alembic.ini upgrade head
```

### 12.3 Développement sans Docker

```bash
# Backend
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m spacy download fr_core_news_sm
python -m spacy download en_core_web_sm
alembic -c backend/alembic.ini upgrade head
cd backend && uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && python -m http.server 5173

# Agent (optionnel)
python agent/sync_agent.py --cv-dir ./storage/cv --job-dir ./storage/job
```

### 12.4 Sécurité du conteneur

Le conteneur API est durci :

```yaml
read_only: true          # Filesystem en lecture seule
tmpfs: [/tmp]            # /tmp en RAM uniquement
security_opt:
  - no-new-privileges:true
cap_drop:
  - ALL                  # Aucune capability Linux
```

---

## 13. Migrations Alembic

```mermaid
gitGraph
    commit id: "0001_init\nevent_logs · extracted_text · score_results"
    commit id: "0002_documents_and_matches\ncv_documents · job_documents · match_results"
    commit id: "0003_embeddings\ncv_embeddings · job_embeddings (pgvector)"
    commit id: "0004_embeddings_index\nHNSW index cosine similarity"
    commit id: "0005_users\ntable users + roles"
    commit id: "0006_add_user_names\nfirst_name · last_name"
    commit id: "0007_job_offers\ntable job_offers"
    commit id: "0008_match_feedback\ntable match_feedback"
    commit id: "0009_parser_feedback\ntable parser_feedback"
    commit id: "0010_add_parsed_profile\nparsed_profile JSON dans extracted_text"
    commit id: "0011_analysis_sessions\ntable sessions + FK sur cv/job docs"
    commit id: "0012_match_component_scores\nscore_semantic · score_skills · match_domain"
```

| Révision | Schéma modifié | Description |
|----------|----------------|-------------|
| `0001` | Création | `event_logs`, `extracted_text`, `score_results` |
| `0002` | Création | `cv_documents`, `job_documents`, `match_results` |
| `0003` | Création | `cv_embeddings`, `job_embeddings` + extension `vector` |
| `0004` | Index | HNSW index sur embedding (cosine) |
| `0005` | Création | `users` (id, email, hash, role, is_active) |
| `0006` | ALTER | `first_name`, `last_name` dans `users` |
| `0007` | Création | `job_offers` (titre, skills JSON, description…) |
| `0008` | Création | `match_feedback` (decision, rating, comment) |
| `0009` | Création | `parser_feedback` (corrections JSON) |
| `0010` | ALTER | `parsed_profile` + hash dans `extracted_text` |
| `0011` | Création + FK | `analysis_sessions` + `session_id` dans cv/job docs |
| `0012` | ALTER | 7 colonnes de scores dans `match_results` |

**Commandes utiles :**

```bash
# État actuel
docker exec airealtime-api alembic -c /app/alembic.ini current

# Historique
docker exec airealtime-api alembic -c /app/alembic.ini history

# Upgrade
docker exec airealtime-api alembic -c /app/alembic.ini upgrade head

# Rollback
docker exec airealtime-api alembic -c /app/alembic.ini downgrade -1

# Générer nouvelle migration
alembic -c backend/alembic.ini revision --autogenerate -m "description"
```

---

## 14. Tests

```bash
# Tous les tests
pytest backend/tests

# Test spécifique
pytest backend/tests/test_scoring.py -v

# Sans rate limiting (pour CI)
AI_REALTIME_RATE_LIMIT_ENABLED=false pytest backend/tests

# Avec couverture
pytest backend/tests --cov=backend/app --cov-report=html
```

**Variables pour les tests :**

```bash
AI_REALTIME_DATABASE_URL=sqlite:///:memory:
AI_REALTIME_QUEUE_BACKEND=memory
AI_REALTIME_EMBEDDING_ENABLED=false
AI_REALTIME_NER_ENABLED=false
AI_REALTIME_RATE_LIMIT_ENABLED=false
```

---

## Annexes

### Codes de statut des documents

| Statut | Signification |
|--------|---------------|
| `pending` | Fichier enregistré, traitement en attente |
| `ready` | Extraction + scoring terminés |
| `failed` | Erreur lors de l'extraction ou du scoring |

### Types de contrats reconnus

`CDI`, `CDD`, `Freelance`, `Stage`, `Alternance`, `Intérim`, `Temps partiel`

### Formats de fichiers supportés

| Extension | Méthode | OCR Fallback |
|-----------|---------|--------------|
| `.pdf` | pypdf | ✅ Tesseract |
| `.docx` | python-docx | ❌ |
| `.txt` | UTF-8 / latin-1 | ❌ |

### Langues supportées pour le NER

| Code | Modèle spaCy |
|------|-------------|
| `fr` | `fr_core_news_sm` |
| `en` | `en_core_web_sm` |

### Domaines de détection automatique

`tech` · `commercial` · `finance` · `rh` · `marketing` · `legal` · `logistics` · `health` · `construction` · `education` · `management`

---

*Documentation générée le 2026-06-12 — AI Real-Time v0.1.0*
