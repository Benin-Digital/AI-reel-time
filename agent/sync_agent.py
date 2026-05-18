#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any

import requests
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt"}

logger = logging.getLogger("ai_realtime_sync")


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {"files": {}, "queue": []}

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("failed to read state file: %s", exc)
            return
        if not isinstance(raw, dict):
            return
        with self._lock:
            self._data["files"] = raw.get("files", {}) if isinstance(raw.get("files"), dict) else {}
            self._data["queue"] = raw.get("queue", []) if isinstance(raw.get("queue"), list) else []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        with self._lock:
            payload = json.dumps(self._data, indent=2, ensure_ascii=True)
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(self.path)

    def get_hash(self, path: Path) -> str | None:
        with self._lock:
            entry = self._data["files"].get(str(path), {})
            return entry.get("hash")

    def set_hash(self, path: Path, hash_value: str) -> None:
        with self._lock:
            self._data["files"][str(path)] = {
                "hash": hash_value,
                "updated_at": int(time.time()),
            }

    def remove_hash(self, path: Path) -> None:
        with self._lock:
            self._data["files"].pop(str(path), None)

    def list_queue(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._data["queue"])

    def set_queue(self, items: list[dict[str, Any]]) -> None:
        with self._lock:
            self._data["queue"] = items

    def upsert_queue_item(self, path: Path, role: str, action: str, error: str) -> None:
        with self._lock:
            queue = self._data["queue"]
            for item in queue:
                if (
                    item.get("path") == str(path)
                    and item.get("role") == role
                    and item.get("action", "upload") == action
                ):
                    item["last_error"] = error
                    item["attempts"] = int(item.get("attempts", 0)) + 1
                    item["updated_at"] = int(time.time())
                    return
            queue.append(
                {
                    "path": str(path),
                    "role": role,
                    "action": action,
                    "attempts": 0,
                    "queued_at": int(time.time()),
                    "last_error": error,
                }
            )


class SyncHandler(FileSystemEventHandler):
    def __init__(self, agent: "SyncAgent", role: str) -> None:
        self.agent = agent
        self.role = role

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if event.event_type == "deleted":
            self.agent.queue_delete(Path(event.src_path), self.role)
            return

        if event.event_type == "moved":
            self.agent.queue_delete(Path(event.src_path), self.role)
            if hasattr(event, "dest_path") and event.dest_path:
                self.agent.queue_path(Path(event.dest_path), self.role)
            return

        path = Path(event.src_path)
        self.agent.queue_path(path, self.role)


class SyncAgent:
    def __init__(
        self,
        cv_dir: Path,
        job_dir: Path,
        api_base: str,
        api_key: str | None,
        state: StateStore,
        debounce_seconds: float,
        retry_interval: float,
    ) -> None:
        self.cv_dir = cv_dir
        self.job_dir = job_dir
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.state = state
        self.debounce_seconds = debounce_seconds
        self.retry_interval = retry_interval
        self._observer = Observer()
        self._pending: dict[tuple[str, str, str], threading.Timer] = {}
        self._pending_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._retry_thread = threading.Thread(target=self._retry_loop, daemon=True)

    def start(self) -> None:
        self.state.load()
        self.cv_dir.mkdir(parents=True, exist_ok=True)
        self.job_dir.mkdir(parents=True, exist_ok=True)

        self._observer.schedule(SyncHandler(self, "cv"), str(self.cv_dir), recursive=False)
        self._observer.schedule(SyncHandler(self, "job"), str(self.job_dir), recursive=False)
        self._observer.start()
        self._retry_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._observer.stop()
        self._observer.join(timeout=5)

    def queue_path(self, path: Path, role: str) -> None:
        self._schedule(path, role, "upload")

    def queue_delete(self, path: Path, role: str) -> None:
        self._schedule(path, role, "delete")

    def _schedule(self, path: Path, role: str, action: str) -> None:
        key = (role, str(path), action)
        with self._pending_lock:
            existing = self._pending.get(key)
            if existing:
                existing.cancel()
            timer = threading.Timer(
                self.debounce_seconds,
                self._process_action,
                args=(path, role, action),
            )
            self._pending[key] = timer
            timer.start()

    def _process_action(self, path: Path, role: str, action: str) -> None:
        key = (role, str(path), action)
        with self._pending_lock:
            self._pending.pop(key, None)

        if action == "delete":
            self._process_delete(path, role)
            return

        self._process_upload(path, role)

    def _process_upload(self, path: Path, role: str) -> None:
        if not path.exists() or not path.is_file():
            return
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            return

        try:
            content_hash = file_sha256(path)
        except Exception as exc:
            logger.warning("hash failed for %s: %s", path, exc)
            return

        if self.state.get_hash(path) == content_hash:
            return

        if self._upload_file(path, role):
            self.state.set_hash(path, content_hash)
            self.state.save()
            return

        self.state.upsert_queue_item(path, role, "upload", "upload failed")
        self.state.save()

    def _process_delete(self, path: Path, role: str) -> None:
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            return

        if self._delete_remote(path, role):
            self.state.remove_hash(path)
            self.state.save()
            return

        self.state.upsert_queue_item(path, role, "delete", "delete failed")
        self.state.save()

    def _upload_file(self, path: Path, role: str) -> bool:
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        files = {"upload": (path.name, path.open("rb"))}
        data = {"folder": role, "filename": path.name}
        try:
            response = requests.post(
                f"{self.api_base}/ingest",
                files=files,
                data=data,
                headers=headers,
                timeout=30,
            )
            if response.status_code >= 400:
                logger.warning("upload failed (%s): %s", response.status_code, response.text)
                return False
            return True
        except Exception as exc:
            logger.warning("upload error: %s", exc)
            return False
        finally:
            try:
                files["upload"][1].close()
            except Exception:
                pass

    def _delete_remote(self, path: Path, role: str) -> bool:
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        payload = {"folder": role, "filename": path.name}
        try:
            response = requests.post(
                f"{self.api_base}/ingest/delete",
                json=payload,
                headers=headers,
                timeout=15,
            )
            if response.status_code >= 400:
                logger.warning("delete failed (%s): %s", response.status_code, response.text)
                return False
            return True
        except Exception as exc:
            logger.warning("delete error: %s", exc)
            return False

    def _retry_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self.retry_interval)
            if self._stop_event.is_set():
                return
            self._retry_pending()

    def _retry_pending(self) -> None:
        queue = self.state.list_queue()
        if not queue:
            return

        remaining: list[dict[str, Any]] = []
        for item in queue:
            path = Path(item.get("path", ""))
            role = item.get("role", "")
            if role not in {"cv", "job"}:
                continue
            action = item.get("action", "upload")
            if action == "delete":
                if self._delete_remote(path, role):
                    self.state.remove_hash(path)
                    continue
                item["attempts"] = int(item.get("attempts", 0)) + 1
                item["updated_at"] = int(time.time())
                remaining.append(item)
                continue
            if action != "upload":
                continue
            if not path.exists() or not path.is_file():
                continue

            if self._upload_file(path, role):
                try:
                    content_hash = file_sha256(path)
                    self.state.set_hash(path, content_hash)
                except Exception:
                    pass
                continue

            item["attempts"] = int(item.get("attempts", 0)) + 1
            item["updated_at"] = int(time.time())
            remaining.append(item)

        self.state.set_queue(remaining)
        self.state.save()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Real-Time RH sync agent")
    parser.add_argument("--cv-dir", required=True, help="Local CV directory")
    parser.add_argument("--job-dir", required=True, help="Local JOB directory")
    parser.add_argument("--api-base", required=True, help="VPS API base URL")
    parser.add_argument("--api-key", default=None, help="API key for VPS")
    parser.add_argument("--state-file", default="~/.ai-realtime-sync/state.json")
    parser.add_argument("--debounce-seconds", type=float, default=1.0)
    parser.add_argument("--retry-interval", type=float, default=30.0)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    api_key = args.api_key or os.getenv("AI_REALTIME_API_KEY")
    state_path = Path(os.path.expanduser(args.state_file))
    state = StateStore(state_path)

    agent = SyncAgent(
        cv_dir=Path(args.cv_dir),
        job_dir=Path(args.job_dir),
        api_base=args.api_base,
        api_key=api_key,
        state=state,
        debounce_seconds=args.debounce_seconds,
        retry_interval=args.retry_interval,
    )

    agent.start()
    logger.info("sync agent started")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("stopping sync agent")
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
