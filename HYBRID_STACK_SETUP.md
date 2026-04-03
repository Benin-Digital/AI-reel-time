# Setup Hybride (macOS + VM Ubuntu)

Date: 3 avril 2026

Ce guide te donne une base concrete pour developper sur macOS et executer la stack comme en serveur Linux dans une VM VirtualBox.

## 1. Cible de l'approche hybride

- Developpement quotidien: macOS (VS Code, Git, edition de code).
- Execution serveur: VM Ubuntu (Docker Compose, PostgreSQL, Redis, API, worker, front).
- Objectif: minimiser les surprises au deploiement final sur serveur Linux.

## 2. Parametres VM recommandes

- OS: Ubuntu Server 24.04 LTS
- vCPU: 4
- RAM: 6 Go
- Disque: 80 Go (dynamique)
- Reseau: NAT + redirection de ports (minimum), ou Bridged si besoin LAN

Ports a exposer:

- `22` SSH
- `8000` API
- `5173` Frontend dev (si necessaire)
- `5432` PostgreSQL (optionnel, plutot interne)
- `6379` Redis (optionnel, plutot interne)

## 3. Principe critique pour le watcher CV/JOB

Le watcher de fichiers doit lire des dossiers situes dans le systeme de fichiers Linux de la VM (ext4), pas un dossier partage VirtualBox.

Pourquoi:

- Les dossiers partages VirtualBox peuvent produire des evenements incomplets.
- Les mecanismes de debounce/idempotence deviennent moins fiables.

Recommande:

- Dossiers sources dans la VM: `/srv/ai-realtime/storage/cv` et `/srv/ai-realtime/storage/job`
- Synchronisation de contenu depuis macOS vers la VM (rsync/sftp) si besoin.

## 4. Outils a installer dans la VM

Noyau projet:

- Docker Engine + Docker Compose plugin
- Git, curl, build-essential
- Python 3.11 + venv + pip
- Node.js 22 LTS + npm
- Tesseract OCR
- LibreOffice (conversion DOC/DOCX robuste)

Data/services:

- PostgreSQL (souvent via container)
- Redis (souvent via container)

## 5. Installation rapide dans la VM

Copie puis execute:

```bash
chmod +x scripts/vm/bootstrap_ubuntu.sh
sudo ./scripts/vm/bootstrap_ubuntu.sh
```

Ensuite, ouvre une nouvelle session SSH et lance:

```bash
scripts/vm/verify_stack.sh
```

## 6. Flux de travail recommande

1. Ecrire le code depuis macOS.
2. Push vers repo local/branche de travail.
3. Pull dans la VM.
4. Lancer stack via Docker Compose dans la VM.
5. Tester le flux complet: depot CV/JOB -> extraction -> score -> API -> UI.

## 7. Definition of done (MVP local hybride)

- Un CV depose dans `/srv/ai-realtime/storage/cv` est detecte automatiquement.
- Texte extrait (ou OCR fallback) et stocke.
- Score calcule et ecrit en base.
- Endpoint API renvoie resultat actualise.
- UI affiche le nouveau score sans retraitement manuel.

## 8. Etape suivante conseillee

Une fois ce setup valide, creer un `docker-compose.yml` unique pour standardiser les environnements preprod/prod avec le minimum d'ecart possible.
