"""Persistent, secret-safe download event log."""
import json
import threading
from datetime import datetime
from pathlib import Path


class DownloadLog:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()

    def append(self, song, event, detail=""):
        entry = {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "video_id": str(song.video_id),
            "title": str(song.title),
            "event": str(event),
            "detail": str(detail),
        }
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                encoded = json.dumps(entry, ensure_ascii=False)
                with self._lock:
                    if self.path.exists() and self.path.stat().st_size > 5 * 1024 * 1024:
                        backup = self.path.with_suffix(self.path.suffix + ".1")
                        if backup.exists():
                            backup.unlink()
                        self.path.replace(backup)
                    with self.path.open("a", encoding="utf-8") as stream:
                        stream.write(encoded + "\n")
            except OSError:
                # Logging must never prevent a download from proceeding.
                pass
        return entry
