# Deploiement Cloud (Option B)

## Pre-requis VPS

- Ubuntu 24.04 LTS
- Docker + Docker Compose
- Ports ouverts: 80, 443, 22

## Dossiers a creer sur le VPS

```bash
sudo mkdir -p /srv/ai-realtime/storage/{cv,job,archive}
```

## Deploiement

1. Copier le repo sur le VPS (rsync ou scp).
2. Dupliquer le fichier d'environnement:

```bash
cp deploy/cloud/.env.cloud.example deploy/cloud/.env.cloud
```

3. Renseigner le domaine et l'email TLS dans `deploy/cloud/.env.cloud`.
4. Lancer la stack:

```bash
docker compose --env-file deploy/cloud/.env.cloud -f deploy/cloud/docker-compose.cloud.yml up -d --build
```

## Verification rapide

```bash
curl -sS https://$AIREALTIME_DOMAIN/health
```

## Migrations DB

```bash
docker compose --env-file deploy/cloud/.env.cloud -f deploy/cloud/docker-compose.cloud.yml run --rm api \
	alembic -c /app/alembic.ini upgrade head
```

## Retention (nettoyage)

```bash
curl -X POST -H "X-API-Key: <key>" https://$AIREALTIME_DOMAIN/maintenance/cleanup
```

## Mise a jour

```bash
docker compose --env-file deploy/cloud/.env.cloud -f deploy/cloud/docker-compose.cloud.yml pull
docker compose --env-file deploy/cloud/.env.cloud -f deploy/cloud/docker-compose.cloud.yml up -d --build
```
