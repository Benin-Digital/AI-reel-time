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

# --- Layer 3: sentence-transformer encoders for ESCO + general embeddings ---
RUN python -c "from sentence_transformers import SentenceTransformer; \
        SentenceTransformer('intfloat/multilingual-e5-base'); \
        print('multilingual-e5-base OK')" && \
    python -c "from sentence_transformers import SentenceTransformer; \
        SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); \
        print('all-MiniLM-L6-v2 OK')"

# --- Layer 1: Docling layout models (~250 MB) ---
RUN python -c "from docling.utils.model_downloader import download_models; download_models()" \
    || python -c "from docling.document_converter import DocumentConverter; DocumentConverter()"

# --- Layer 3 data: ESCO v1.2.0 FR + EN dumps (graceful if URLs change) ---
# If the download fails (URL pattern changes between ESCO releases), the layer
# silently moves on — the user can drop the CSV(s) on the mounted /srv/ai-realtime/esco
# volume at runtime to enable it.
ARG ESCO_VERSION=1.2.0
ARG ESCO_BASE_URL=https://esco.ec.europa.eu/sites/default/files
RUN mkdir -p /srv/ai-realtime/esco \
    && cd /srv/ai-realtime/esco \
    && (curl -fL --retry 2 -o esco_fr.zip \
          "${ESCO_BASE_URL}/ESCO%20dataset%20-%20v${ESCO_VERSION}%20-%20classification%20-%20fr%20-%20csv.zip" \
        && unzip -o -j esco_fr.zip 'skills_fr.csv' -d . \
        && rm -f esco_fr.zip) \
       || echo "[warn] ESCO FR auto-download failed — drop skills_fr.csv into the esco volume to enable" \
    && (curl -fL --retry 2 -o esco_en.zip \
          "${ESCO_BASE_URL}/ESCO%20dataset%20-%20v${ESCO_VERSION}%20-%20classification%20-%20en%20-%20csv.zip" \
        && unzip -o -j esco_en.zip 'skills_en.csv' -d . \
        && rm -f esco_en.zip) \
       || echo "[warn] ESCO EN auto-download failed — drop skills_en.csv into the esco volume to enable"

# scoring_v2 model dir (writable volume mount at runtime)
RUN mkdir -p /srv/ai-realtime/models

COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY app ./app

RUN chown -R appuser:appgroup /app /srv/ai-realtime

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
