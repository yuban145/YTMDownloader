"""Thread-safe history separated by media kind; legacy audio history is retained."""
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
 video_id TEXT PRIMARY KEY, title TEXT, artist TEXT, album TEXT, duration INTEGER,
 file_path TEXT, file_size INTEGER, downloaded_at TEXT, status TEXT DEFAULT 'completed'
);
"""
MEDIA_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_downloads (
 video_id TEXT, title TEXT, artist TEXT, album TEXT, duration INTEGER,
 file_path TEXT, file_size INTEGER, downloaded_at TEXT, status TEXT DEFAULT 'completed',
 media_type TEXT NOT NULL DEFAULT 'audio', source_video_id TEXT,
 PRIMARY KEY (video_id, media_type)
);
"""


def media_type_for_download(download_mode, audio_format="m4a"):
    if download_mode == "video":
        return "video"
    return f"audio_{audio_format}" if audio_format in ("flac", "mp3") else "audio"


class Database:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = str(Path(os.environ.get("APPDATA", str(Path.home()))) / "YtMusicVault/downloads.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(LEGACY_SCHEMA + MEDIA_SCHEMA)
        # One-time migration; do not reimport records removed by the user.
        self._conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
        if not self._conn.execute("SELECT 1 FROM schema_migrations WHERE name='media-history'").fetchone():
            self._conn.execute("""INSERT OR IGNORE INTO media_downloads
                SELECT video_id,title,artist,album,duration,file_path,file_size,downloaded_at,status,
                       'audio',video_id FROM downloads""")
            self._conn.execute("INSERT INTO schema_migrations VALUES ('media-history')")
        self._conn.commit()

    def is_downloaded(self, video_id, media_type="audio"):
        with self._lock:
            row = self._conn.execute(
                "SELECT file_path FROM media_downloads WHERE video_id=? AND media_type=? AND status='completed'",
                (video_id, media_type)).fetchone()
        return bool(row and row[0] and Path(row[0]).is_file())

    def mark_downloaded(self, video_id, title="", artist="", album="", duration=0,
                        file_path="", file_size=0, media_type="audio", source_video_id=""):
        with self._lock:
            self._conn.execute("""INSERT OR REPLACE INTO media_downloads
                VALUES (?,?,?,?,?,?,?,?,'completed',?,?)""",
                (video_id, title, artist, album, duration, file_path, file_size,
                 datetime.now().isoformat(), media_type, source_video_id or video_id))
            self._conn.commit()

    def mark_failed(self, video_id, media_type="audio"):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO media_downloads(video_id,media_type,status) VALUES (?,?,'failed')",
                (video_id, media_type))
            self._conn.commit()

    def get_all_records(self, media_type=None):
        with self._lock:
            if media_type is None:
                return self._conn.execute("SELECT * FROM media_downloads ORDER BY downloaded_at DESC").fetchall()
            return self._conn.execute(
                "SELECT * FROM media_downloads WHERE media_type=? ORDER BY downloaded_at DESC",
                (media_type,)).fetchall()

    def get_downloaded_ids(self, media_type="audio"):
        return [r[0] for r in self.get_all_records(media_type) if r[8] == "completed" and r[5] and Path(r[5]).is_file()]

    def remove_record(self, video_id, media_type=None):
        with self._lock:
            if media_type is None:
                self._conn.execute("DELETE FROM media_downloads WHERE video_id=?", (video_id,))
            else:
                self._conn.execute("DELETE FROM media_downloads WHERE video_id=? AND media_type=?", (video_id, media_type))
            self._conn.commit()

    def clear_all(self):
        with self._lock:
            self._conn.execute("DELETE FROM media_downloads")
            self._conn.execute("DELETE FROM downloads")
            self._conn.commit()

    def close(self):
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
