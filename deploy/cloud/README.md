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

## Provisionner ESCO (optionnel, manuel)

Le CSV ESCO n'est plus auto-telecharge (le site ESCO exige desormais une
demande manuelle email + CAPTCHA, voir le commentaire dans `backend/Dockerfile`).
Sans ce fichier, ESCO se degrade gracieusement (aucun crash) mais reste
desactive silencieusement — voir le WARNING au demarrage plus bas.

1. Demander le dataset sur https://esco.ec.europa.eu/en/use-esco/download
   (Content: Classification, File type: csv, Language: fr et/ou en).
2. Copier `skills_fr.csv` sur le serveur puis dans le volume :

```bash
scp skills_fr.csv <user>@<serveur>:/tmp/
ssh <user>@<serveur> "sudo docker cp /tmp/skills_fr.csv airealtime-api:/srv/ai-realtime/esco/skills_fr.csv"
```

3. **Piege permissions** : `docker cp` copie le fichier avec l'UID/GID de la
   machine hote (souvent 1000:1000 sur un serveur Ubuntu), pas celui de
   `appuser` dans le conteneur (verifier avec `docker exec airealtime-api id appuser`).
   Le conteneur a `cap_drop: ALL`, donc `chown` est impossible depuis
   l'interieur meme en root — corriger depuis l'hote :

```bash
docker volume inspect cloud_airealtime_esco --format '{{.Mountpoint}}'
sudo chown 100:101 <mountpoint>/skills_fr.csv
sudo chmod 644 <mountpoint>/skills_fr.csv
```

4. Verifier la lecture avec le vrai utilisateur du process, pas root :

```bash
docker exec -u appuser airealtime-api head -c 100 /srv/ai-realtime/esco/skills_fr.csv
```

## Verification rapide

```bash
curl -sS https://$AIREALTIME_DOMAIN/health
```

Verifier aussi les logs de demarrage du conteneur `api` juste apres un
`up -d --build` — un WARNING au demarrage (ex: ESCO manquant, backend de
queue non-persistant) signale un outil/fichier absent en silence plutot
qu'un bug de code, et ne se reverra plus une fois noye dans les logs
applicatifs suivants :

```bash
docker compose --env-file deploy/cloud/.env.cloud -f deploy/cloud/docker-compose.cloud.yml \
	logs api --since 5m | grep -i warning
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
