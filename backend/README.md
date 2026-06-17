Architecture v2 (non-LLM, ML-only)
==================================

Quatre couches sont activées par défaut. Chaque couche dégrade gracieusement
si son artefact est manquant, donc l'API démarre toujours.

| Couche | Rôle | Modèle par défaut | Fallback |
|--------|------|-------------------|----------|
| 1 — Conversion | Découpage PDF en sections | Docling (IBM) | PyMuPDF brut |
| 2 — NER | Extraction entités (PER/ORG/LOC) | `Jean-Baptiste/camembert-ner` | spaCy `fr_core_news_sm` |
| 3 — Taxonomie | Mapping compétences ↔ ESCO | `intfloat/multilingual-e5-base` + FAISS | noop |
| 4 — Scoring | Agrégation des 6 signaux | `GradientBoostingClassifier` calibré | score lexical existant |

Tous les modèles sont pré-téléchargés dans l'image Docker (`backend/Dockerfile`)
et les CSV ESCO v1.2.0 (FR + EN) sont également embarqués au build. Aucun
téléchargement runtime n'est requis tant que l'image est à jour.

Variables d'environnement
-------------------------

```bash
# Couche 1 — Docling
AI_REALTIME_CONVERSION_USE_DOCLING=true

# Couche 2 — CamemBERT (override pour charger un checkpoint fine-tuné)
AI_REALTIME_NER_BACKEND=camembert
AI_REALTIME_CAMEMBERT_NER_MODEL=Jean-Baptiste/camembert-ner
# Optionnel: pointer sur un dossier local après fine-tuning
# AI_REALTIME_CAMEMBERT_NER_MODEL=/srv/ai-realtime/models/camembert-ner-airealtime

# Couche 3 — ESCO
AI_REALTIME_ESCO_DIR=/srv/ai-realtime/esco
AI_REALTIME_ESCO_MODEL_NAME=intfloat/multilingual-e5-base
AI_REALTIME_ESCO_ENRICH_SKILLS=true
AI_REALTIME_ESCO_ENRICH_MAX_URIS=30

# Couche 4 — scoring_v2
AI_REALTIME_SCORING_V2_MODEL_PATH=/srv/ai-realtime/models/scoring_v2_gbm.pkl
```

Volumes persistants
-------------------

Deux volumes Docker sont déclarés dans `deploy/local/docker-compose.local.yml`
et `deploy/cloud/docker-compose.cloud.yml`:

- `airealtime_esco` → `/srv/ai-realtime/esco` (CSV ESCO, hérités de l'image)
- `airealtime_models` → `/srv/ai-realtime/models` (artefacts entraînés:
  `scoring_v2_gbm.pkl`, fine-tunes CamemBERT)

Endpoints v2
------------

- `POST /scoring-v2/train` — entraîne le GBM à partir du feedback DB
- `POST /scoring-v2/score` — score un couple CV/Job avec les 6 signaux
- `GET /scoring-v2/status` — disponibilité du modèle entraîné
- `POST /esco/lookup` — recherche sémantique dans ESCO

Fine-tuning CamemBERT
---------------------

1. Exporter les annotations: `python backend/scripts/export_ner_annotations.py`
2. Annoter dans Label Studio (config XML incluse dans le script)
3. Lancer le notebook `backend/notebooks/finetune_camembert_ner.ipynb`
4. Pointer la variable `AI_REALTIME_CAMEMBERT_NER_MODEL` sur le dossier
   `/srv/ai-realtime/models/camembert-ner-airealtime/`

Désactivation par couche
------------------------

Pour repasser à l'ancienne pipeline (debug uniquement):

```bash
AI_REALTIME_CONVERSION_USE_DOCLING=false   # → PyMuPDF
AI_REALTIME_NER_BACKEND=spacy              # → fr_core_news_sm
AI_REALTIME_ESCO_ENRICH_SKILLS=false       # → pas d'URI ESCO
# scoring_v2 est désactivé automatiquement si le pkl est absent
```
