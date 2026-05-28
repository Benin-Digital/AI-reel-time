NER (Named Entity Recognition)
===============================

The backend supports optional local NER extraction using spaCy models. This feature is disabled by default.

Enable NER
----------
Set the environment variable or `Settings` value `AI_REALTIME_NER_ENABLED=true` to enable NER.

Install spaCy and models
------------------------
Install the Python package and language model(s) in your runtime environment (VM or container):

```bash
pip install -r requirements.txt
# For French (example):
python -m spacy download fr_core_news_sm
# For English (if in ner_model_map):
python -m spacy download en_core_web_sm
```

Configure models
----------------
By default `ner_model_name` controls the fallback spaCy model. You can also configure per-language models with `ner_model_map` in `AI_REALTIME_NER_MODEL_MAP`, e.g.:

```
AI_REALTIME_NER_MODEL_MAP="fr:fr_core_news_sm,en:en_core_web_sm"
```

Notes
-----
- If spaCy or the specific model is not available, the system gracefully falls back and NER will be a no-op.
- Keep `AI_REALTIME_NER_ENABLED` disabled in environments where you don't want to install language models.
