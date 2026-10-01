"""Offline regression coverage for process cleanup and literal output paths."""
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import psutil
from yt_dlp import YoutubeDL

from ytmusicvault.core.downloader import Downloader
from ytmusicvault.models.song import DownloadStatus, Song


class DownloaderLifecycleTests(unittest.TestCase):
    def test_cancel_event_stops_worker_while_stdout_is_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / "ready"
            code = ("from pathlib import Path; import time; "
                    f"Path({str(ready)!r}).touch(); time.sleep(30)")
            cancel = threading.Event()
            downloader = Downloader(directory)
            statuses, results = [], []
            with patch("ytmusicvault.core.downloader.ytdlp_command",
                       return_value=[sys.executable, "-c", code]), \
                 patch("ytmusicvault.core.downloader.shutil.which", return_value=sys.executable):
                worker = threading.Thread(target=lambda: results.append(downloader.download(
                    Song("silent", "Silent"), status_callback=statuses.append, cancel_event=cancel)))
                worker.start()
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(ready.exists(), "Synthetic worker did not start")
                    cancel.set()
                    worker.join(timeout=3)
                    self.assertFalse(worker.is_alive(), "Cancellation must not depend on stdout activity")
                    self.assertEqual(results, [False])
                    self.assertEqual(statuses[-1], DownloadStatus.PAUSED)
                finally:
                    downloader.cancel()
                    worker.join(timeout=5)

    def test_callback_failure_also_stops_nested_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "child.pid"
            code = ("import subprocess,sys,time; from pathlib import Path; "
                    "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); "
                    f"Path({str(pid_file)!r}).write_text(str(child.pid)); "
                    "print('[download] 1.0% of 1MiB at 1MiB/s ETA 00:01',flush=True); time.sleep(30)")

            def fail_callback(*args):
                raise RuntimeError("Synthetic callback failure")

            with patch("ytmusicvault.core.downloader.ytdlp_command",
                       return_value=[sys.executable, "-c", code]), \
                 patch("ytmusicvault.core.downloader.shutil.which", return_value=sys.executable):
                try:
                    self.assertFalse(Downloader(directory).download(
                        Song("nested", "Nested"), progress_callback=fail_callback))
                    self.assertTrue(pid_file.exists())
                    child_pid = int(pid_file.read_text())
                    self.assertTrue(not psutil.pid_exists(child_pid) or
                                    psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE,
                                    "Failed downloads must not leave nested FFmpeg/yt-dlp workers")
                finally:
                    if pid_file.exists():
                        try:
                            child = psutil.Process(int(pid_file.read_text()))
                            child.kill()
                            child.wait(timeout=5)
                        except psutil.NoSuchProcess:
                            pass

    def test_output_directory_with_template_syntax_is_literal(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "%(title)s Playlist"
            template = Downloader(directory)._build_output_template(str(folder))
            with YoutubeDL({"quiet": True, "outtmpl": template}) as downloader:
                filename = downloader.prepare_filename({
                    "id": "test", "title": "Track", "artist": "Artist", "ext": "m4a"})
            self.assertEqual(Path(filename).parent, folder)
            self.assertEqual(Path(filename).name, "Artist - Track [test].m4a")


if __name__ == "__main__":
    unittest.main()
