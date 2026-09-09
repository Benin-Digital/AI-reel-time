FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# All ML model caches live under /app/.cache so they're baked into the image
# layer and remain reachable at runtime even with read_only filesystems.
ENV HF_HOME=/app/.cache/huggingface
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence-transformers
ENV DOCLING_ARTIFACTS_PATH=/app/.cache/docling
ENV TOKENIZERS_PARALLELISM=false

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr libreoffice \
       curl unzip ca-certificates \
       libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

COPY requirements.txt .

# Install CPU-only torch first so sentence-transformers/docling don't pull
# the ~1 GB NVIDIA CUDA stack (cudnn/cublas/etc.) we don't need on this server.
RUN pip install --no-cache-dir --default-timeout=600 \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.5.1 torchvision==0.20.1

RUN pip install --no-cache-dir --default-timeout=600 -r requirements.txt

# --- spaCy fallback models (used if CamemBERT pipeline ever fails to load) ---
RUN python -m spacy download fr_core_news_sm \
    && (python -m spacy download en_core_web_sm || true)

# --- Layer 2: CamemBERT NER baseline (~440 MB) ---
RUN python -c "import sentencepiece; print('sentencepiece', sentencepiece.__version__)" && \
    python -c "from transformers import CamembertTokenizer; \
        t = CamembertTokenizer.from_pretrained('Jean-Baptiste/camembert-ner'); \
        print('tokenizer OK:', type(t).__name__)" && \
    python -c "from transformers import AutoModelForTokenClassification; \
        m = AutoModelForTokenClassification.from_pretrained('Jean-Baptiste/camembert-ner'); \
        print('model OK:', type(m).__name__)"

# --- Layer 3: sentence-transformer encoder shared by ESCO + general embeddings ---
RUN python -c "from sentence_transformers import SentenceTransformer; \
        SentenceTransformer('intfloat/multilingual-e5-base'); \
        print('multilingual-e5-base OK')"

# Skill-to-skill semantic credit (matcher.py's _semantic_skill_credit) uses a
# separate, smaller model: multilingual-e5-base does not discriminate
# between short technical skill names (see settings.py's
# skill_embedding_model_name comment) -- all-MiniLM-L6-v2 does.
RUN python -c "from sentence_transformers import SentenceTransformer; \
        SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); \
        print('all-MiniLM-L6-v2 OK')"

# --- Cross-encoder reranker (matcher.py semantic scoring) ---
RUN python -c "from sentence_transformers import CrossEncoder; \
        CrossEncoder('antoinelouis/crossencoder-camembert-large-mmarcoFR'); \
        print('crossencoder-camembert-large-mmarcoFR OK')"

# --- Layer 1: Docling layout models (~250 MB) ---
RUN python -c "from docling.utils.model_downloader import download_models; download_models()" \
    || python -c "from docling.document_converter import DocumentConverter; DocumentConverter()"

# --- Layer 3 data: ESCO CSVs — NOT auto-downloaded, provision manually ---
#
# This used to curl a static zip URL at build time. As of the ESCO v1.2.1
# release, the download page (https://esco.ec.europa.eu/en/use-esco/download)
# replaced that with a gated request form: email address, organisation type,
# intended use, a privacy-statement acceptance, AND a CAPTCHA, with the file
# delivered by email afterwards — there is no stable URL left to curl, so a
# version bump alone can never fix this again. Retrying it here would only
# burn build time on a download that is now permanently impossible to
# automate (and completing a CAPTCHA programmatically is out of bounds).
#
# Provisioning is manual and one-time: request the dataset yourself at the
# URL above (Content: Classification, File type: csv, Language: fr/en),
# then drop the resulting skills_fr.csv / skills_en.csv onto the
# /srv/ai-realtime/esco volume mounted at runtime. esco_taxonomy.py already
# degrades gracefully (empty lookups, no crash) when these files are absent
# — but see main.py's startup check for a loud warning when that happens,
# so a missing file reads as "ESCO not configured", not as a scoring bug.
#
# Ownership pitfall hit in production: `docker cp host_file container:/path`
# preserves the HOST file's numeric uid/gid, not the container's appuser
# (created above by `adduser --system`, uid 100 / gid 101 on this image —
# confirm with `docker exec <container> id appuser`, system UID allocation
# isn't guaranteed identical on every rebuild). A file copied in from a
# typical Ubuntu host lands owned by uid/gid 1000, mode 600 — unreadable by
# appuser, and esco_taxonomy.py's broad except swallows the resulting
# PermissionError exactly like a missing file, so it fails the same silent
# way this whole comment exists to prevent. Fix on the HOST (this
# container drops ALL capabilities, so even `docker exec -u root ... chown`
# fails with "Operation not permitted" from inside it):
#   docker volume inspect <esco_volume_name> --format '{{.Mountpoint}}'
#   chown 100:101 <mountpoint>/skills_fr.csv && chmod 644 <mountpoint>/skills_fr.csv
# Then verify as the real runtime user, not root:
#   docker exec -u appuser <container> head -c 100 /srv/ai-realtime/esco/skills_fr.csv
RUN mkdir -p /srv/ai-realtime/esco

# scoring_v2 model dir (writable volume mount at runtime)
RUN mkdir -p /srv/ai-realtime/models

COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY app ./app

RUN chown -R appuser:appgroup /app /srv/ai-realtime

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
