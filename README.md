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
