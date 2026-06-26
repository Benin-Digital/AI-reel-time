#!/usr/bin/env bash
set -euo pipefail

# Télécharge les modèles spaCy requis pour le dev local (hors Docker).
# Le Dockerfile (backend/Dockerfile) effectue déjà ces téléchargements pour la prod.
#
# Usage:
#   ./scripts/local/download_models.sh
#
# Modèles installés:
#   - fr_core_news_sm  (déjà épinglé dans backend/requirements.txt, ce script vérifie son installation)
#   - en_core_web_sm   (téléchargé via spacy download)

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[download_models] Vérification fr_core_news_sm..."
if ! "$PYTHON_BIN" -c "import fr_core_news_sm" 2>/dev/null; then
  echo "[download_models] Installation fr_core_news_sm..."
  "$PYTHON_BIN" -m spacy download fr_core_news_sm
else
  echo "[download_models] fr_core_news_sm déjà présent."
fi

echo "[download_models] Vérification en_core_web_sm..."
if ! "$PYTHON_BIN" -c "import en_core_web_sm" 2>/dev/null; then
  echo "[download_models] Installation en_core_web_sm..."
  "$PYTHON_BIN" -m spacy download en_core_web_sm
else
  echo "[download_models] en_core_web_sm déjà présent."
fi

echo "[download_models] OK"
