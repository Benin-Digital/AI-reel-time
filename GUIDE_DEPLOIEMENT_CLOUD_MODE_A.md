# Guide de déploiement Cloud — Mode A : CI/CD via pipeline (GitHub Actions ou GitLab CI)

**Projet** : AI Real-Time — Plateforme de matching CV ↔ Offres d'emploi  
**Cible** : VPS OVH, Ubuntu 24.04  
**Mode** : Pipeline automatisé (CI/CD → SSH vers serveur → build Docker in situ)  
**Audience** : Développeur junior / stagiaire  
**Dernière mise à jour** : Juin 2026

---

## Table des matières

1. [Architecture de déploiement](#1-architecture-de-déploiement)
2. [Règles d'or](#2-règles-dor)
3. [Variables à collecter avant de commencer](#3-variables-à-collecter-avant-de-commencer)
4. [Catalogue complet des variables d'environnement](#4-catalogue-complet-des-variables-denvironnement)
5. [Préparation du serveur OVH](#5-préparation-du-serveur-ovh)
6. [Préparation du dépôt (GitHub ou GitLab)](#6-préparation-du-dépôt-github-ou-gitlab)
7. [Configuration du pipeline CI/CD](#7-configuration-du-pipeline-cicd)
   - [7.1 Option A — GitHub Actions](#71-option-a--github-actions)
   - [7.2 Option B — GitLab CI/CD](#72-option-b--gitlab-cicd)
8. [Premier déploiement](#8-premier-déploiement)
9. [Vérification go-live](#9-vérification-go-live)
10. [Sauvegardes et restauration](#10-sauvegardes-et-restauration)
11. [Surveillance et logs](#11-surveillance-et-logs)
12. [Procédure de rollback](#12-procédure-de-rollback)
13. [Erreurs courantes](#13-erreurs-courantes)
14. [Escalade](#14-escalade)

---

## 1. Architecture de déploiement

### 1.1 Schéma des services

```mermaid
graph TD
    GH[GitHub — push sur main]
    GH -->|SSH + git pull| SERVER[VPS OVH Ubuntu 24.04]

    subgraph SERVER[VPS OVH — Docker Compose]
        TK[Traefik :80/:443\nLet's Encrypt TLS]
        API[airealtime-api\nFastAPI :8000]
        PG[airealtime-postgres\npgvector/pg16 :5432]
        RD[airealtime-redis\nRedis 8 Alpine :6379]

        TK -->|reverse proxy HTTPS| API
        API -->|SQL + pgvector| PG
        API -->|streams| RD
    end

    BROWSER[Navigateur / Client API]
    BROWSER -->|HTTPS| TK

    subgraph STORAGE[Volumes persistants]
        SCV["/srv/ai-realtime/storage/cv"]
        SJOB["/srv/ai-realtime/storage/job"]
        SARC["/srv/ai-realtime/storage/archive"]
        VPG[(postgres_data)]
        VRD[(redis_data)]
        VESCO[(airealtime_esco)]
        VMDL[(airealtime_models)]
        VHF[(airealtime_hf_cache)]
    end

    API --- SCV
    API --- SJOB
    API --- SARC
    PG --- VPG
    RD --- VRD
    API --- VESCO
    API --- VMDL
    API --- VHF
```

### 1.2 Flux CI/CD

```mermaid
flowchart LR
    PUSH([push main]) --> CI[CI\nruff · pytest]
    CI -->|OK| DEPLOY[SSH · git pull\nbuild · migrate]
    CI -->|KO| STOP([bloqué])
    DEPLOY -->|health ok| OK([production])
    DEPLOY -->|health KO| ERR([rollback])
```

### 1.3 Ports et pare-feu

| Port | Protocole | Ouvert vers l'extérieur | Usage |
|------|-----------|------------------------|-------|
| 22   | TCP       | Oui (restreindre par IP si possible) | SSH |
| 80   | TCP       | Oui | Traefik HTTP → redirect HTTPS |
| 443  | TCP       | Oui | Traefik HTTPS (API + dashboard) |
| 5432 | TCP       | Non (interne Docker) | PostgreSQL |
| 6379 | TCP       | Non (interne Docker) | Redis |
| 8000 | TCP       | Non (interne Docker) | FastAPI (via Traefik) |

> **Note importante** : Le port 8000 n'est jamais exposé directement. Tout le trafic passe par Traefik sur les ports 80/443. Ne jamais ouvrir le port 8000 dans le pare-feu OVH.

---

## 2. Règles d'or

> Ces règles s'appliquent **en toutes circonstances**. En cas de doute, ne pas agir et escalader.

1. **Ne jamais modifier `.env.cloud` en production sans en informer l'équipe** — un redémarrage des conteneurs applique immédiatement les changements.
2. **Toujours sauvegarder la base de données avant une migration Alembic** — les migrations ne sont pas automatiquement réversibles.
3. **Le build Docker prend 20 à 40 minutes la première fois** — ne pas interrompre le pipeline. Les builds suivants sont plus rapides grâce au cache des layers.
4. **`AI_REALTIME_JWT_SECRET_KEY` doit être un secret fort en production** — la valeur par défaut `change-me` ouvre toutes les sessions JWT à une attaque de force brute triviale.
5. **Ne jamais committer `.env.cloud` dans Git** — ce fichier contient les mots de passe de base de données et les clés API.
6. **Traefik gère TLS automatiquement** — ne pas installer Nginx ni Certbot manuellement, cela entrerait en conflit.
7. **Les volumes Docker sont la seule source de vérité pour les données** — ne pas supprimer les volumes sans sauvegarde préalable (`docker compose down -v` détruit toutes les données).

---

## 3. Variables à collecter avant de commencer

Avant toute intervention, rassembler les informations suivantes :

| Information | Exemple | Où la trouver |
|-------------|---------|---------------|
| IP publique du VPS | `51.178.42.10` | Espace client OVH |
| Nom de domaine pointant vers le VPS | `api.monentreprise.com` | Gestionnaire DNS |
| Adresse email pour Let's Encrypt | `devops@monentreprise.com` | Équipe |
| Clé SSH privée pour le déploiement | `~/.ssh/id_ed25519_deploy` | Générée à l'étape 5 |
| Mot de passe PostgreSQL | (générer avec `openssl rand -hex 32`) | À définir |
| Clé(s) API pour l'application | (générer avec `openssl rand -hex 32`) | À définir |
| Secret JWT | (générer avec `openssl rand -hex 32`) | À définir |

---

## 4. Catalogue complet des variables d'environnement

### 4.1 Variables du fichier `.env.cloud` (obligatoires)

| Variable | Défaut fourni | Obligatoire | Remarques |
|----------|---------------|-------------|-----------|
| `AIREALTIME_DOMAIN` | `example.com` | Oui | Domaine complet sans protocole (`api.monentreprise.com`) |
| `TRAEFIK_EMAIL` | `admin@example.com` | Oui | Email pour les notifications Let's Encrypt |
| `POSTGRES_DB` | `airealtime` | Oui | Nom de la base de données |
| `POSTGRES_USER` | `airealtime` | Oui | Utilisateur PostgreSQL |
| `POSTGRES_PASSWORD` | `change-me` | Oui | **Changer impérativement** — `openssl rand -hex 32` |
| `AIREALTIME_API_KEYS` | `change-me` | Oui | Clé(s) API séparées par virgule — `openssl rand -hex 32` |
| `AIREALTIME_CORS_ALLOW_ORIGINS` | `https://example.com` | Oui | Origines CORS autorisées (domaine du frontend) |

### 4.2 Variables d'environnement supplémentaires (injectées dans le compose ou en extra)

| Variable | Défaut | Obligatoire | Remarques |
|----------|--------|-------------|-----------|
| `AI_REALTIME_JWT_SECRET_KEY` | `change-me` | **Oui en prod** | Secret JWT HS256 — **à ajouter dans `.env.cloud`** |
| `AI_REALTIME_QUEUE_BACKEND` | `stream` | Non | `stream` (Redis activé) ou `memory` (pas de Redis, dev only) |
| `AI_REALTIME_NER_ENABLED` | `true` | Non | Active l'extraction NER (CamemBERT + spaCy) |
| `AI_REALTIME_EMBEDDING_ENABLED` | `true` | Non | Active les embeddings sémantiques (sentence-transformers) |
| `AI_REALTIME_LOG_LEVEL` | `INFO` | Non | `INFO` ou `DEBUG` (verbeux, éviter en prod) |
| `AI_REALTIME_LOG_JSON` | `true` | Non | Format JSON structuré (recommandé en prod) |
| `AI_REALTIME_REQUIRE_API_KEY` | `true` | Non | Exiger une clé API sur tous les endpoints |
| `AI_REALTIME_HYBRID_SCORING_ENABLED` | `true` | Non | Active le scoring hybride (vectoriel + lexical) |
| `AI_REALTIME_HYBRID_VECTOR_WEIGHT` | `0.3` | Non | Poids du score vectoriel dans le score hybride |
| `AI_REALTIME_HYBRID_LEXICAL_WEIGHT` | `0.7` | Non | Poids du score lexical dans le score hybride |
| `AI_REALTIME_OCR_LANGUAGES` | `fra+eng` | Non | Langues Tesseract pour l'OCR |
| `AI_REALTIME_ESCO_ENRICH_SKILLS` | `true` | Non | Enrichit les compétences avec la taxonomie ESCO |

> **Recommandation** : Ajouter `AI_REALTIME_JWT_SECRET_KEY` dans `.env.cloud.example` (actuellement absent) pour éviter d'oublier de le définir en production.

---

## 5. Préparation du serveur OVH

### 5.1 Connexion initiale et sécurisation SSH

```bash
# Depuis votre machine locale — connexion initiale en root
ssh root@<IP_VPS>

# Créer un utilisateur dédié (remplacer "deploy" par le nom souhaité)
adduser deploy
usermod -aG sudo deploy

# Passer sur l'utilisateur deploy
su - deploy
```

### 5.2 Génération de la clé SSH de déploiement

Cette clé sera utilisée par GitHub Actions pour se connecter au serveur.

```bash
# Sur votre machine locale (pas le serveur)
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/id_ed25519_airealtime_deploy

# Afficher la clé publique — la copier pour l'étape suivante
cat ~/.ssh/id_ed25519_airealtime_deploy.pub
```

```bash
# Sur le serveur — ajouter la clé publique
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "<COLLER_LA_CLE_PUBLIQUE_ICI>" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### 5.3 Bootstrap du serveur

Le script `scripts/vm/bootstrap_ubuntu.sh` installe automatiquement Docker, Python 3.11, Node.js 22, Tesseract, LibreOffice et crée les répertoires de stockage.

```bash
# Sur le serveur — cloner le dépôt d'abord (une seule fois)
git clone https://github.com/99ch/AI-reel-time.git /srv/ai-realtime/app
cd /srv/ai-realtime/app

# Lancer le bootstrap (requiert sudo)
sudo bash scripts/vm/bootstrap_ubuntu.sh
```

> **Attention** : Après le bootstrap, se déconnecter et se reconnecter pour que l'appartenance au groupe `docker` prenne effet.

```bash
# Après reconnexion — vérifier l'installation
bash scripts/vm/verify_stack.sh
```

Sortie attendue : tous les éléments affichent `[OK]`.

### 5.4 Vérification des ports OVH (pare-feu)

Dans l'espace client OVH → section "Pare-feu réseau" ou "Security Groups", s'assurer que les règles suivantes sont actives :

| Règle | Action | Port(s) | Source |
|-------|--------|---------|--------|
| SSH   | Autoriser | 22/TCP | Votre IP (ou `0.0.0.0/0` si nécessaire) |
| HTTP  | Autoriser | 80/TCP | `0.0.0.0/0` |
| HTTPS | Autoriser | 443/TCP | `0.0.0.0/0` |
| Tout le reste | Bloquer | — | — |

---

## 6. Préparation du dépôt (GitHub ou GitLab)

### 6.1 Secrets à configurer — GitHub Actions

Dans GitHub → Settings → Secrets and variables → Actions → New repository secret :

| Nom du secret | Valeur |
|---|---|
| `SSH_PRIVATE_KEY` | Contenu de `~/.ssh/id_ed25519_airealtime_deploy` (clé privée complète) |
| `SSH_HOST` | IP publique du VPS (ex : `51.178.42.10`) |
| `SSH_USER` | Nom de l'utilisateur sur le serveur (ex : `deploy`) |
| `SSH_PORT` | `22` (ou le port SSH personnalisé si modifié) |

### 6.2 Secrets à configurer — GitLab CI/CD

Dans GitLab → Settings → CI/CD → Variables → Add variable (cocher **Protected** + **Masked**) :

| Nom de la variable | Valeur |
|---|---|
| `SSH_PRIVATE_KEY` | Contenu de `~/.ssh/id_ed25519_airealtime_deploy` (clé privée complète) |
| `SSH_HOST` | IP publique du VPS (ex : `51.178.42.10`) |
| `SSH_USER` | Nom de l'utilisateur sur le serveur (ex : `deploy`) |
| `SSH_PORT` | `22` (ou le port SSH personnalisé si modifié) |

> Les noms de variables sont identiques entre GitHub et GitLab — seul l'endroit où vous les saisissez change.

---

## 7. Configuration du pipeline CI/CD

> Choisissez l'option qui correspond à votre hébergeur de code. Les deux options aboutissent au même résultat : un push sur `main` déclenche les tests puis déploie sur le serveur via SSH.

### 7.1 Option A — GitHub Actions

Créer le répertoire `.github/workflows/` à la racine du dépôt, puis créer les deux fichiers suivants.

#### Workflow CI — `.github/workflows/ci.yml`

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main]

jobs:
  lint-and-test:
    name: Lint + Tests
    runs-on: ubuntu-latest

    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: airealtime_test
          POSTGRES_USER: airealtime
          POSTGRES_PASSWORD: testpassword
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U airealtime -d airealtime_test"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 20

      redis:
        image: redis:8-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 20

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: |
          pip install -r backend/requirements.txt -r backend/requirements-dev.txt

      - name: Download spaCy models
        run: |
          python -m spacy download fr_core_news_sm
          python -m spacy download en_core_web_sm

      - name: Lint with ruff
        run: |
          cd backend
          ruff check app tests

      - name: Run tests
        env:
          AI_REALTIME_DATABASE_URL: postgresql+psycopg://airealtime:testpassword@localhost:5432/airealtime_test
          AI_REALTIME_REDIS_URL: redis://localhost:6379/0
          AI_REALTIME_QUEUE_BACKEND: stream
          AI_REALTIME_DATABASE_AUTO_CREATE: "true"
          AI_REALTIME_RATE_LIMIT_ENABLED: "false"
          AI_REALTIME_JWT_SECRET_KEY: ci-test-secret-key
          AI_REALTIME_REQUIRE_API_KEY: "false"
        run: |
          cd backend
          pytest tests -v --tb=short
```

#### Workflow déploiement — `.github/workflows/deploy.yml`

> **Important** : L'image Docker (~2-3 Go avec les modèles ML) est construite **sur le serveur**, pas dans GitHub Actions. Le workflow se contente d'ouvrir une session SSH et d'exécuter les commandes de build directement sur la machine de production. La première exécution peut prendre 20 à 40 minutes.

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]

# Un seul déploiement à la fois — annule le précédent si un nouveau push arrive
concurrency:
  group: production-deploy
  cancel-in-progress: false

jobs:
  deploy:
    name: Deploy via SSH
    runs-on: ubuntu-latest
    # Ne déployer que si le job CI a réussi sur le même commit
    needs: []   # Retirer le commentaire et ajouter "lint-and-test" si ci.yml est dans le même workflow

    steps:
      - name: Deploy to OVH VPS
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.SSH_HOST }}
          username: ${{ secrets.SSH_USER }}
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          port: ${{ secrets.SSH_PORT }}
          # Timeout étendu : le build Docker peut prendre 20-40 min la première fois
          command_timeout: 60m
          script: |
            set -euo pipefail

            DEPLOY_PATH="/srv/ai-realtime/app"
            COMPOSE_FILE="deploy/cloud/docker-compose.cloud.yml"
            ENV_FILE="deploy/cloud/.env.cloud"

            echo "==> [1/5] Git pull"
            cd "${DEPLOY_PATH}"
            git fetch origin main
            git reset --hard origin/main

            echo "==> [2/5] Build et démarrage des conteneurs"
            echo "    ATTENTION : la première exécution peut prendre 20 à 40 minutes"
            echo "    (téléchargement des modèles ML : CamemBERT, sentence-transformers, Docling)"
            docker compose \
              --env-file "${ENV_FILE}" \
              -f "${COMPOSE_FILE}" \
              up --build -d \
              --remove-orphans

            echo "==> [3/5] Migrations Alembic"
            docker compose \
              --env-file "${ENV_FILE}" \
              -f "${COMPOSE_FILE}" \
              run --rm api \
              alembic -c /app/alembic.ini upgrade head

            echo "==> [4/5] Attente du healthcheck API (max 120s)"
            attempt=0
            until curl -sf "http://localhost:8000/health" > /dev/null 2>&1 || [ $attempt -ge 24 ]; do
              attempt=$((attempt + 1))
              echo "    Tentative ${attempt}/24 — en attente..."
              sleep 5
            done

            echo "==> [5/5] Vérification finale"
            STATUS=$(curl -sf "http://localhost:8000/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unreachable")
            if [ "${STATUS}" = "ok" ]; then
              echo "    Déploiement réussi — /health répond : ok"
            else
              echo "    ERREUR : /health ne répond pas correctement (status=${STATUS})"
              docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" logs --tail=50 api
              exit 1
            fi

            echo "==> Déploiement terminé avec succès"
```

#### Enchaînement des workflows (recommandé)

Pour garantir que le déploiement n'a lieu qu'après un CI vert, vous pouvez enchaîner les workflows via `workflow_run` :

```yaml
# Remplacer la section "on:" dans deploy.yml par :
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
    branches: [main]

jobs:
  deploy:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    # ... reste du job identique
```

---

### 7.2 Option B — GitLab CI/CD

Un seul fichier `.gitlab-ci.yml` à la racine du dépôt remplace les deux workflows GitHub Actions.

#### Variables à configurer dans GitLab

`Settings > CI/CD > Variables` — cocher **Protected** et **Masked** pour chaque secret :

| Variable GitLab | Description | Exemple |
|---|---|---|
| `SSH_HOST` | IP ou FQDN du VPS OVH | `51.xxx.xxx.xxx` |
| `SSH_USER` | Utilisateur SSH sur le serveur | `ubuntu` |
| `SSH_PORT` | Port SSH (22 par défaut) | `22` |
| `SSH_PRIVATE_KEY` | Contenu complet de la clé privée (multi-ligne) | `-----BEGIN OPENSSH PRIVATE KEY-----...` |

> **Différences avec GitHub** : les secrets GitLab n'ont pas de notion d'"Environment" par défaut. Si vous voulez restreindre le déploiement à la branche `main`, utiliser des **Protected variables** + une **branche protégée** `main` dans `Settings > Repository`.

#### Fichier `.gitlab-ci.yml`

```yaml
# .gitlab-ci.yml
stages:
  - test
  - deploy

# ── Stage 1 : lint + tests ─────────────────────────────────────────────────
lint-and-test:
  stage: test
  image: python:3.11-slim
  services:
    - name: pgvector/pgvector:pg16
      alias: postgres
    - name: redis:8-alpine
      alias: redis
  variables:
    POSTGRES_DB: airealtime_test
    POSTGRES_USER: airealtime
    POSTGRES_PASSWORD: testpassword
    POSTGRES_HOST_AUTH_METHOD: trust
    AI_REALTIME_DATABASE_URL: "postgresql+psycopg://airealtime:testpassword@postgres:5432/airealtime_test"
    AI_REALTIME_REDIS_URL: "redis://redis:6379/0"
    AI_REALTIME_QUEUE_BACKEND: stream
    AI_REALTIME_DATABASE_AUTO_CREATE: "true"
    AI_REALTIME_RATE_LIMIT_ENABLED: "false"
    AI_REALTIME_JWT_SECRET_KEY: ci-test-secret-key
    AI_REALTIME_REQUIRE_API_KEY: "false"
  before_script:
    - apt-get update -qq && apt-get install -y --no-install-recommends git
    - pip install --no-cache-dir -r backend/requirements.txt -r backend/requirements-dev.txt
    - python -m spacy download fr_core_news_sm
    - python -m spacy download en_core_web_sm
  script:
    - cd backend
    - ruff check app tests
    - pytest tests -v --tb=short
  rules:
    - if: '$CI_PIPELINE_SOURCE == "push"'
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

# ── Stage 2 : déploiement via SSH ─────────────────────────────────────────
deploy-production:
  stage: deploy
  image: alpine:3.19
  # Ne déployer que sur la branche main, après un test vert
  needs:
    - lint-and-test
  rules:
    - if: '$CI_COMMIT_BRANCH == "main" && $CI_PIPELINE_SOURCE == "push"'
  before_script:
    - apk add --no-cache openssh-client
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - ssh-keyscan -H -p "$SSH_PORT" "$SSH_HOST" >> ~/.ssh/known_hosts
  script:
    # Timeout étendu : le build Docker peut prendre 20-40 min la première fois
    - |
      ssh -o ConnectTimeout=30 -p "$SSH_PORT" "$SSH_USER@$SSH_HOST" 'bash -s' <<'ENDSSH'
        set -euo pipefail

        DEPLOY_PATH="/srv/ai-realtime/app"
        COMPOSE_FILE="deploy/cloud/docker-compose.cloud.yml"
        ENV_FILE="deploy/cloud/.env.cloud"

        echo "==> [1/5] Git pull"
        cd "${DEPLOY_PATH}"
        git fetch origin main
        git reset --hard origin/main

        echo "==> [2/5] Build et démarrage des conteneurs"
        echo "    ATTENTION : la première exécution peut prendre 20 à 40 minutes"
        docker compose \
          --env-file "${ENV_FILE}" \
          -f "${COMPOSE_FILE}" \
          up --build -d \
          --remove-orphans

        echo "==> [3/5] Migrations Alembic"
        docker compose \
          --env-file "${ENV_FILE}" \
          -f "${COMPOSE_FILE}" \
          run --rm api \
          alembic -c /app/alembic.ini upgrade head

        echo "==> [4/5] Attente du healthcheck API (max 120s)"
        attempt=0
        until curl -sf "http://localhost:8000/health" > /dev/null 2>&1 || [ $attempt -ge 24 ]; do
          attempt=$((attempt + 1))
          echo "    Tentative ${attempt}/24 — en attente..."
          sleep 5
        done

        echo "==> [5/5] Vérification finale"
        STATUS=$(curl -sf "http://localhost:8000/health" \
          | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" \
          2>/dev/null || echo "unreachable")
        if [ "${STATUS}" = "ok" ]; then
          echo "    Déploiement réussi — /health répond : ok"
        else
          echo "    ERREUR : /health ne répond pas correctement (status=${STATUS})"
          exit 1
        fi

        echo "==> Déploiement terminé avec succès"
      ENDSSH
  timeout: 75 minutes
```

#### Différences clés GitHub Actions vs GitLab CI/CD

| Point | GitHub Actions | GitLab CI/CD |
|---|---|---|
| Fichiers | `.github/workflows/ci.yml` + `deploy.yml` | `.gitlab-ci.yml` unique |
| Secrets | Settings > Environments > Secrets | Settings > CI/CD > Variables |
| Services (CI) | `services:` dans le job | `services:` identique |
| Timeout | `command_timeout: 60m` (dans ssh-action) | `timeout: 75 minutes` (au niveau du job) |
| Déclencheur branche | `on: push: branches: [main]` | `rules: if: $CI_COMMIT_BRANCH == "main"` |
| Enchaîner les jobs | `needs:` ou `workflow_run:` | `needs:` identique |

> Toutes les sections suivantes (8 à 14) sont identiques quelle que soit l'option choisie.

---

## 8. Premier déploiement

### 8.1 Créer le fichier `.env.cloud` sur le serveur

Ce fichier **ne doit jamais être commité dans Git**. Il est créé manuellement sur le serveur.

```bash
# Sur le serveur
cd /srv/ai-realtime/app

cp deploy/cloud/.env.cloud.example deploy/cloud/.env.cloud
nano deploy/cloud/.env.cloud
```

Remplir avec les vraies valeurs :

```bash
AIREALTIME_DOMAIN=api.monentreprise.com
TRAEFIK_EMAIL=devops@monentreprise.com
POSTGRES_DB=airealtime
POSTGRES_USER=airealtime
POSTGRES_PASSWORD=$(openssl rand -hex 32)   # Remplacer par la valeur générée
AIREALTIME_API_KEYS=$(openssl rand -hex 32)  # Remplacer par la valeur générée
AIREALTIME_CORS_ALLOW_ORIGINS=https://api.monentreprise.com
```

Ajouter manuellement la variable JWT manquante dans l'exemple :

```bash
# Ajouter à la fin de .env.cloud :
AI_REALTIME_JWT_SECRET_KEY=$(openssl rand -hex 32)   # Remplacer par la valeur générée
```

> **Note** : Générer les secrets en avance avec `openssl rand -hex 32` et les noter dans un gestionnaire de mots de passe (Bitwarden, 1Password, etc.) avant de les insérer dans le fichier.

### 8.2 Vérifier le pointage DNS

```bash
# Depuis votre machine locale
dig +short api.monentreprise.com
# Doit retourner l'IP du VPS
```

Attendre la propagation DNS (jusqu'à 24h selon le TTL, généralement quelques minutes sur OVH).

### 8.3 Lancer le premier déploiement manuellement (recommandé)

La première fois, il est préférable de lancer le build manuellement sur le serveur pour observer la progression et détecter d'éventuels problèmes.

```bash
# Sur le serveur
cd /srv/ai-realtime/app

# Le build initial prend 20 à 40 minutes — ne pas interrompre
docker compose \
  --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml \
  up --build -d

# Suivre les logs en temps réel pendant le build
docker compose \
  --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml \
  logs -f
```

### 8.4 Migrations Alembic (obligatoire après le premier déploiement)

```bash
docker compose \
  --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml \
  run --rm api \
  alembic -c /app/alembic.ini upgrade head
```

Sortie attendue :
```
INFO  [alembic.runtime.migration] Running upgrade ...
INFO  [alembic.runtime.migration] Running upgrade ... -> ...
```

### 8.5 Déclencher le pipeline CI/CD

Une fois la configuration initiale terminée, tout push sur `main` déclenche automatiquement le pipeline :

```bash
# Sur votre machine locale
git push origin main
```

Surveiller l'exécution dans GitHub → Actions → Deploy to Production.

---

## 9. Vérification go-live

### 9.1 Checklist de mise en production

- [ ] Le DNS pointe vers l'IP du VPS (`dig +short api.monentreprise.com`)
- [ ] Le certificat TLS est valide (`curl -I https://api.monentreprise.com/health`)
- [ ] L'endpoint `/health` répond `{"status": "ok"}` en HTTPS
- [ ] PostgreSQL est joignable depuis le conteneur API (`docker exec airealtime-postgres pg_isready -U airealtime`)
- [ ] Redis est joignable depuis le conteneur API (`docker exec airealtime-redis redis-cli ping` → `PONG`)
- [ ] Les migrations Alembic ont été appliquées (vérifier les logs de la commande `upgrade head`)
- [ ] Les volumes de stockage sont montés (`docker exec airealtime-api ls /srv/ai-realtime/storage/cv`)
- [ ] La variable `AI_REALTIME_JWT_SECRET_KEY` n'est pas `change-me` dans `.env.cloud`
- [ ] La variable `POSTGRES_PASSWORD` n'est pas `change-me` dans `.env.cloud`
- [ ] La variable `AIREALTIME_API_KEYS` n'est pas `change-me` dans `.env.cloud`
- [ ] Le pipeline GitHub Actions s'est exécuté sans erreur sur le dernier commit de `main`
- [ ] Les secrets GitHub sont configurés (`SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_USER`, `SSH_PORT`)

### 9.2 Tests manuels post-déploiement

```bash
# Test basique — health check
curl -sf https://api.monentreprise.com/health
# Attendu : {"status":"ok"}

# Test avec clé API — liste des CVs
curl -sf -H "X-API-Key: <VOTRE_CLE_API>" \
  https://api.monentreprise.com/cv-documents
# Attendu : [] ou liste de documents

# Test TLS — vérifier le certificat
curl -vI https://api.monentreprise.com/health 2>&1 | grep -E "SSL|certificate|subject"
```

---

## 10. Sauvegardes et restauration

### 10.1 Sauvegarde de la base de données PostgreSQL

```bash
# Sur le serveur — dump compressé horodaté
BACKUP_DIR="/srv/ai-realtime/backups"
mkdir -p "${BACKUP_DIR}"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
docker exec airealtime-postgres \
  pg_dump -U airealtime -d airealtime --format=custom --compress=9 \
  > "${BACKUP_DIR}/airealtime_${TIMESTAMP}.dump"

echo "Sauvegarde créée : ${BACKUP_DIR}/airealtime_${TIMESTAMP}.dump"
```

### 10.2 Sauvegarde des fichiers de stockage

```bash
# Archiver les CVs et offres d'emploi
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
tar -czf "/srv/ai-realtime/backups/storage_${TIMESTAMP}.tar.gz" \
  /srv/ai-realtime/storage/

echo "Sauvegarde des fichiers créée."
```

### 10.3 Automatiser les sauvegardes (cron)

```bash
# Ajouter au crontab de l'utilisateur deploy
crontab -e

# Sauvegarde quotidienne à 2h du matin
0 2 * * * /srv/ai-realtime/app/scripts/backup.sh >> /srv/ai-realtime/logs/backup.log 2>&1
```

### 10.4 Restauration de la base de données

```bash
# ATTENTION : cette opération écrase la base de données existante
docker exec -i airealtime-postgres \
  pg_restore -U airealtime -d airealtime --clean \
  < /srv/ai-realtime/backups/airealtime_YYYYMMDD_HHMMSS.dump
```

### 10.5 Transférer les sauvegardes hors du serveur

```bash
# Depuis votre machine locale — récupérer le dump le plus récent
scp deploy@<IP_VPS>:/srv/ai-realtime/backups/airealtime_*.dump ./backups/
```

---

## 11. Surveillance et logs

### 11.1 Logs des conteneurs

```bash
# Logs de l'API en temps réel
docker logs -f airealtime-api

# Logs des 200 dernières lignes avec horodatage
docker logs --tail=200 --timestamps airealtime-api

# Logs de tous les services
docker compose \
  --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml \
  logs -f

# Logs Traefik (certificats, requêtes)
docker logs -f airealtime-traefik
```

### 11.2 État des conteneurs

```bash
# Vérifier que tous les conteneurs sont "healthy"
docker compose \
  --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml \
  ps

# Utilisation des ressources en temps réel
docker stats
```

### 11.3 Métriques de base

```bash
# Espace disque
df -h /srv/ai-realtime/

# Taille des volumes Docker
docker system df -v

# Connexions actives à PostgreSQL
docker exec airealtime-postgres \
  psql -U airealtime -d airealtime -c "SELECT count(*) FROM pg_stat_activity;"
```

### 11.4 Alertes recommandées

Pour un environnement de production, configurer des alertes sur :
- Espace disque > 80% sur `/srv/ai-realtime/`
- Conteneur `airealtime-api` en statut `unhealthy` pendant plus de 60 secondes
- Échec du pipeline GitHub Actions sur `main`

---

## 12. Procédure de rollback

### 12.1 Rollback rapide — revenir au commit précédent

```bash
# Sur le serveur — identifier le dernier commit fonctionnel
cd /srv/ai-realtime/app
git log --oneline -10

# Revenir au commit précédent
git checkout <COMMIT_SHA>

# Relancer les services (sans rebuild si le code seul a changé)
docker compose \
  --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml \
  up --build -d

# Vérifier le health check
curl -sf http://localhost:8000/health
```

### 12.2 Rollback de migration Alembic

```bash
# Revenir d'une migration en arrière
docker compose \
  --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml \
  run --rm api \
  alembic -c /app/alembic.ini downgrade -1

# Ou revenir à une révision spécifique
docker compose \
  --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml \
  run --rm api \
  alembic -c /app/alembic.ini downgrade <REVISION_ID>
```

> **Attention** : Si la migration a modifié des données (pas seulement le schéma), le downgrade peut échouer ou provoquer une perte de données. Toujours restaurer depuis un backup dans ce cas.

### 12.3 Arrêt d'urgence

```bash
# Arrêter tous les services (les données sont préservées dans les volumes)
docker compose \
  --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml \
  down

# NE PAS utiliser "down -v" sauf si vous voulez supprimer toutes les données
```

---

## 13. Erreurs courantes

### 13.1 Le pipeline déploiement échoue avec "Permission denied"

**Symptôme** : `appleboy/ssh-action` retourne `Permission denied (publickey)`.

**Causes et solutions** :
- Vérifier que `SSH_PRIVATE_KEY` dans GitHub Secrets contient la clé privée complète (avec `-----BEGIN OPENSSH PRIVATE KEY-----` et `-----END OPENSSH PRIVATE KEY-----`).
- Vérifier que la clé publique correspondante est dans `~/.ssh/authorized_keys` sur le serveur.
- Vérifier que les permissions sont correctes : `chmod 600 ~/.ssh/authorized_keys && chmod 700 ~/.ssh`.

### 13.2 Le build Docker échoue avec "No space left on device"

**Symptôme** : L'étape de build s'arrête avec une erreur d'espace disque.

**Solution** :
```bash
# Nettoyer les images et layers inutilisés
docker system prune -af --volumes

# Vérifier l'espace libéré
df -h /
```

### 13.3 Le healthcheck API échoue après le déploiement

**Symptôme** : `curl http://localhost:8000/health` retourne une erreur de connexion.

**Diagnostic** :
```bash
# Vérifier les logs de l'API
docker logs --tail=100 airealtime-api

# Vérifier que PostgreSQL est healthy
docker exec airealtime-postgres pg_isready -U airealtime -d airealtime

# Vérifier l'état des conteneurs
docker compose \
  --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml \
  ps
```

**Causes fréquentes** :
- PostgreSQL pas encore prêt (attendre quelques secondes — le healthcheck `depends_on` devrait gérer cela).
- Erreur de migration Alembic (chercher `alembic.runtime.migration` dans les logs).
- Variable d'environnement manquante ou incorrecte (vérifier `.env.cloud`).

### 13.4 Traefik ne délivre pas de certificat TLS

**Symptôme** : Le site répond en HTTP mais pas en HTTPS, ou le certificat est auto-signé.

**Diagnostic** :
```bash
docker logs airealtime-traefik 2>&1 | grep -i "certificate\|acme\|error"
```

**Causes fréquentes** :
- Le DNS ne pointe pas encore vers l'IP du VPS (propagation en cours).
- Les ports 80 et 443 ne sont pas ouverts dans le pare-feu OVH.
- `TRAEFIK_EMAIL` n'est pas une adresse valide.
- Le fichier `deploy/cloud/letsencrypt/acme.json` a des permissions incorrectes (Traefik le crée automatiquement).

### 13.5 Migrations Alembic échouent

**Symptôme** : `alembic upgrade head` retourne une erreur.

```bash
# Voir l'état actuel des migrations
docker compose \
  --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml \
  run --rm api \
  alembic -c /app/alembic.ini current

# Historique des migrations
docker compose \
  --env-file deploy/cloud/.env.cloud \
  -f deploy/cloud/docker-compose.cloud.yml \
  run --rm api \
  alembic -c /app/alembic.ini history
```

### 13.6 Première build trop longue — le pipeline timeout

**Symptôme** : GitHub Actions annule le job après 6 heures (limite par défaut).

**Solution** : Le premier build doit être effectué manuellement sur le serveur (voir section 8.3). Les builds suivants bénéficient du cache Docker et sont beaucoup plus rapides (5-15 min).

Le timeout de `deploy.yml` est fixé à 60 minutes dans `command_timeout: 60m`. Pour le premier déploiement, augmenter cette valeur si nécessaire ou effectuer le build manuellement.

---

## 14. Escalade

En cas de problème bloquant non résolu par ce guide :

1. **Collecter les logs** avant toute intervention :
   ```bash
   docker compose \
     --env-file deploy/cloud/.env.cloud \
     -f deploy/cloud/docker-compose.cloud.yml \
     logs --tail=200 > /tmp/airealtime_logs_$(date +%Y%m%d_%H%M%S).txt
   ```

2. **Capturer l'état du système** :
   ```bash
   docker compose \
     --env-file deploy/cloud/.env.cloud \
     -f deploy/cloud/docker-compose.cloud.yml \
     ps > /tmp/airealtime_ps_$(date +%Y%m%d_%H%M%S).txt
   df -h >> /tmp/airealtime_ps_$(date +%Y%m%d_%H%M%S).txt
   docker stats --no-stream >> /tmp/airealtime_ps_$(date +%Y%m%d_%H%M%S).txt
   ```

3. **Ne pas modifier `.env.cloud` ou relancer des `docker compose down -v`** sans accord explicite d'un membre senior de l'équipe.

4. **Contacts** :
   - Responsable technique du projet : via le canal Slack `#ai-realtime-ops`
   - Documentation Traefik : https://doc.traefik.io/traefik/
   - Documentation Alembic : https://alembic.sqlalchemy.org/
   - Documentation pgvector : https://github.com/pgvector/pgvector
