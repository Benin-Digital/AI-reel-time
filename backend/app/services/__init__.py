from .extraction import extract_text
from .event_queue import dequeue_event, enqueue_event
from .fingerprint import file_sha256
from .embeddings import embed_text, embed_texts
from .matcher import score_texts
from .scoring import serialize_keywords, deserialize_keywords
from .watcher import LocalFolderWatcher, WatchEvent
from .worker import EventWorker
from .event_queue import get_queue_status, warn_if_unsafe_backend
from .esco_taxonomy import warn_if_esco_missing

__all__ = [
    "extract_text",
    "embed_text",
    "embed_texts",
    "dequeue_event",
    "enqueue_event",
    "file_sha256",
    "LocalFolderWatcher",
    "WatchEvent",
    "EventWorker",
    "score_texts",
    "serialize_keywords",
    "deserialize_keywords",
    "get_queue_status",
    "warn_if_unsafe_backend",
    "warn_if_esco_missing",
]
