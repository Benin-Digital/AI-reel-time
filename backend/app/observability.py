from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST

HTTP_REQUESTS = Counter(
    "airealtime_http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "airealtime_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
)
QUEUE_REDIS_AVAILABLE = Gauge(
    "airealtime_queue_redis_available",
    "Redis availability",
)
QUEUE_REDIS_LENGTH = Gauge(
    "airealtime_queue_redis_length",
    "Redis queue length",
)
QUEUE_MEMORY_LENGTH = Gauge(
    "airealtime_queue_memory_length",
    "In-memory queue length",
)
WORKER_ALIVE = Gauge(
    "airealtime_worker_alive",
    "Worker alive",
)
EMBEDDINGS_ENABLED = Gauge(
    "airealtime_embeddings_enabled",
    "Embeddings enabled",
)
EVENT_COUNT = Gauge(
    "airealtime_event_count",
    "Event count",
)
EXTRACTION_COUNT = Gauge(
    "airealtime_extraction_count",
    "Extraction count",
)
SCORE_COUNT = Gauge(
    "airealtime_score_count",
    "Score count",
)
MATCH_COUNT = Gauge(
    "airealtime_match_count",
    "Match count",
)
CV_DOCUMENT_COUNT = Gauge(
    "airealtime_cv_document_count",
    "CV document count",
)
JOB_DOCUMENT_COUNT = Gauge(
    "airealtime_job_document_count",
    "Job document count",
)
CV_EMBEDDING_COUNT = Gauge(
    "airealtime_cv_embedding_count",
    "CV embedding count",
)
JOB_EMBEDDING_COUNT = Gauge(
    "airealtime_job_embedding_count",
    "Job embedding count",
)
ESCO_ENRICH_TERMS_TOTAL = Counter(
    "airealtime_esco_enrich_terms_total",
    "Skill terms processed by ESCO enrichment, by outcome",
    ["outcome"],  # "mapped" | "unmapped" | "error"
)


def record_request(method: str, path: str, status: int, duration_seconds: float) -> None:
    HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
    HTTP_LATENCY.labels(method=method, path=path).observe(duration_seconds)


def update_runtime_metrics(
    queue_status: dict[str, int | bool],
    worker_alive: bool,
    counts: dict[str, int],
    embeddings_enabled: bool,
) -> None:
    QUEUE_REDIS_AVAILABLE.set(1 if queue_status.get("redis_available") else 0)
    QUEUE_REDIS_LENGTH.set(int(queue_status.get("redis_queue_length") or 0))
    QUEUE_MEMORY_LENGTH.set(int(queue_status.get("memory_queue_length") or 0))
    WORKER_ALIVE.set(1 if worker_alive else 0)
    EMBEDDINGS_ENABLED.set(1 if embeddings_enabled else 0)

    EVENT_COUNT.set(int(counts.get("events", 0)))
    EXTRACTION_COUNT.set(int(counts.get("extractions", 0)))
    SCORE_COUNT.set(int(counts.get("scores", 0)))
    MATCH_COUNT.set(int(counts.get("matches", 0)))
    CV_DOCUMENT_COUNT.set(int(counts.get("cv_documents", 0)))
    JOB_DOCUMENT_COUNT.set(int(counts.get("job_documents", 0)))
    CV_EMBEDDING_COUNT.set(int(counts.get("cv_embeddings", 0)))
    JOB_EMBEDDING_COUNT.set(int(counts.get("job_embeddings", 0)))


def render_metrics() -> bytes:
    return generate_latest()
