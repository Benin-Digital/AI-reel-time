from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


@dataclass(frozen=True)
class WatchEvent:
    path: Path
    event_type: str
    observed_at: float


class DebouncedHandler(FileSystemEventHandler):
    def __init__(
        self,
        callback: Callable[[WatchEvent], None],
        debounce_seconds: float = 1.0,
    ) -> None:
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self._last_seen: dict[tuple[str, str], float] = {}

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return

        event_path = Path(event.src_path)
        key = (event.event_type, str(event_path))
        now = monotonic()
        previous = self._last_seen.get(key, 0.0)

        if now - previous < self.debounce_seconds:
            return

        self._last_seen[key] = now
        self.callback(
            WatchEvent(
                path=event_path,
                event_type=event.event_type,
                observed_at=now,
            )
        )


class LocalFolderWatcher:
    def __init__(
        self,
        folders: list[Path],
        callback: Callable[[WatchEvent], None],
        debounce_seconds: float = 1.0,
    ) -> None:
        self._observer = Observer()
        self._handler = DebouncedHandler(callback, debounce_seconds=debounce_seconds)
        self._folders = folders

    def start(self) -> None:
        for folder in self._folders:
            folder.mkdir(parents=True, exist_ok=True)
            self._observer.schedule(self._handler, str(folder), recursive=False)
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=5)
