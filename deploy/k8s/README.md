# Deploiement Kubernetes (Helm)

Chart Helm **SKELETON** pour deployer AI Real-Time sur Kubernetes.

> Statut : pour scaling futur. La prod actuelle tourne sur Docker Compose (`deploy/cloud/`).

## Prerequis

- Cluster Kubernetes >= 1.25
- Helm 3.x
- StorageClass `ReadWriteMany` pour les CV/JOB partages entre replicas (NFS, EFS, CephFS, Longhorn...)
- Postgres avec extension `pgvector` (CloudSQL, RDS, Crunchy Postgres Operator, ou Bitnami chart)
- Redis (ElastiCache, MemoryStore, Bitnami chart, ou redis-operator)
- Ingress controller (nginx, traefik) + cert-manager pour TLS

## Installation rapide

```bash
# 1. Creer le secret avec toutes les variables sensibles
kubectl create namespace airealtime
kubectl -n airealtime create secret generic airealtime-secrets \
  --from-literal=AI_REALTIME_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/airealtime' \
  --from-literal=AI_REALTIME_REDIS_URL='redis://HOST:6379/0' \
  --from-literal=AI_REALTIME_JWT_SECRET_KEY='<32+ chars random>' \
  --from-literal=AI_REALTIME_API_KEYS='client1=KEY1,client2=KEY2' \
  --from-literal=AI_REALTIME_BOOTSTRAP_SUPERADMIN_PASSWORD='<change-me>'

# 2. Editer values.yaml pour:
#    - image.repository / image.tag
#    - storage.cvJob.storageClass (votre StorageClass RWX)
#    - ingress.enabled + ingress.hosts

# 3. Deployer
helm install airealtime ./helm/airealtime -n airealtime -f values.yaml

# 4. Migrations Alembic (one-shot job manuel pour la premiere fois)
kubectl -n airealtime exec deploy/airealtime-api -- \
  alembic -c /app/alembic.ini upgrade head
```

## Notes

- Le chart ne deploie PAS Postgres ni Redis : a brancher en externe via le secret.
- Le watcher de fichiers (`LocalFolderWatcher`) est demarre dans chaque pod API : si vous
  scalez > 1 replica, prevoyez un volume RWX OU desactivez le watcher et utilisez
  uniquement `POST /ingest` via le sync agent.
- Les CV/JOB peuvent etre stockes sur un object storage (S3, GCS) : il faudra adapter
  le watcher (hors scope de ce chart).
- HPA disponible (CPU-based). Pour autoscaler sur la profondeur de la queue Redis,
  utiliser KEDA avec `scaledobject.keda.sh/v1alpha1`.

## Limitations connues

- Pas de Service mesh ni de NetworkPolicy par defaut.
- Pas de PodDisruptionBudget : a ajouter si plus de 2 replicas.
- Pas de monitoring : connecter Prometheus sur `/metrics` (deja expose par l'API).
