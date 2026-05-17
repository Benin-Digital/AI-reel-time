# AI Real-Time

Ce dossier contient une proposition d'architecture complete pour un nouveau projet de matching CV/JOB en temps reel, sans dependance a WordPress.

## Contenu

- `ARCHITECTURE_COMPLETE_AI_REAL_TIME.md` : document professionnel detaille pour decision DG, avec plusieurs architectures possibles et schemas Mermaid.
- `HYBRID_STACK_SETUP.md` : guide d'installation et d'execution en mode hybride (dev macOS + stack Linux en VM).

## Objectif du projet

- Surveiller en continu des dossiers `CV` et `JOB`.
- Recalculer automatiquement les scores de matching a chaque changement de fichier.
- Proposer une interface visuelle simple et efficace pour les equipes RH.

## Demarrage recommande (stack hybride)

1. Lire `HYBRID_STACK_SETUP.md`.
2. Dans la VM Ubuntu, lancer `scripts/vm/bootstrap_ubuntu.sh` (sudo).
3. Verifier l'environnement avec `scripts/vm/verify_stack.sh`.

## Deploiement (Option B - Cloud)

- Compose local: deploy/local/docker-compose.local.yml
- Compose cloud: deploy/cloud/docker-compose.cloud.yml
- Guide cloud: deploy/cloud/README.md

## Tests (backend)

```bash
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
pytest backend/tests
```

## UI (MVP)

Le dossier `frontend/` contient une UI statique pour lire les documents et les scores.

Lancer un serveur local simple:

```bash
cd frontend
python -m http.server 5173
```

Ouvrir http://localhost:5173 puis renseigner l'API base (ex: http://localhost:8000).

## Migrations (backend)

```bash
alembic -c backend/alembic.ini upgrade head
```
