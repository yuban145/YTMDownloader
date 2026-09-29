import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from ytmusicvault.core.auth import normalize_headers
from ytmusicvault.models.song import DownloadStatus, Song
from ytmusicvault.ui.download_controller import DownloadController
from ytmusicvault.utils.config import AppConfig

APP = QApplication.instance() or QApplication([])


def wait_for_result(results):
    deadline = time.monotonic() + 5
    while not results and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.005)
    APP.processEvents()
    if not results:
        raise AssertionError("Download batch did not finish")
    return results[0]


class DownloadControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = AppConfig(download_dir=self.tmp.name, concurrent_downloads=2, max_retries=0, download_mode="audio")
        self.credentials = normalize_headers({"cookie": "__Secure-3PAPISID=test-account"})
        self.db = Mock()
        self.log_path = Path(self.tmp.name) / "logs" / "download.log"
        self.controller = DownloadController(self.db, log_path=self.log_path)
        self.results = []
        self.controller.finished.connect(self.results.append)

    def test_workers_use_distinct_temporary_jars_from_verified_session(self):
        barrier = threading.Barrier(2)
        observed = []
        root = Path(self.tmp.name)

        class FakeDownloader:
            def __init__(self, *args, **kwargs):
                self.path = Path(kwargs["cookies_path"])
                observed.append((self.path, self.path.read_text(), kwargs["browser_cookie_source"]))

            def download(self, song, **kwargs):
                barrier.wait(timeout=3)
                output = root / (song.video_id + ".m4a")
                output.write_bytes(b"synthetic-audio")
                song.file_path = str(output)
                return True

        with patch("ytmusicvault.ui.download_controller.Downloader", FakeDownloader), \
             patch("ytmusicvault.ui.download_controller.MetadataWriter") as writer:
            writer.return_value.write.return_value = True
            self.controller.start([Song("one", "One"), Song("two", "Two")], self.config, self.credentials)
            songs = wait_for_result(self.results)
        self.assertEqual([s.status for s in songs], [DownloadStatus.COMPLETED] * 2)
        self.assertEqual(self.db.mark_downloaded.call_count, 2)
        self.assertEqual(len({path for path, _, _ in observed}), 2)
        for path, text, browser in observed:
            self.assertIn("test-account", text)
            self.assertEqual(browser, "none")
            self.assertFalse(path.exists(), "Temporary credentials must be cleaned up")
        logged = self.log_path.read_text(encoding="utf-8")
        self.assertIn("下载完成", logged)
        self.assertNotIn("test-account", logged)

    def test_progress_emits_snapshot_for_download_page(self):
        updates = []
        self.controller.updated.connect(updates.append)
        song = Song("one", "One", download_mode="video")
        self.controller._progress(song, 42.5, "1MiB/s")
        APP.processEvents()
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].progress, 42.5)
        self.assertEqual(updates[0].speed, "1MiB/s")
        self.assertIn("42.5%", updates[0].stage)

    def test_metadata_failure_is_not_recorded_as_success(self):
        output = Path(self.tmp.name) / "failed.m4a"
        output.write_bytes(b"synthetic-audio")

        def download(song, **kwargs):
            song.file_path = str(output)
            return True

        with patch("ytmusicvault.ui.download_controller.Downloader") as downloader, \
             patch("ytmusicvault.ui.download_controller.MetadataWriter") as writer:
            downloader.return_value.download.side_effect = download
            writer.return_value.write.return_value = False
            self.controller.start([Song("one", "One")], self.config, self.credentials)
            songs = wait_for_result(self.results)
            self.assertEqual(downloader.return_value.download.call_count, 1)
        self.assertEqual(songs[0].status, DownloadStatus.FAILED)
        self.db.mark_downloaded.assert_not_called()

    def test_mv_download_resolves_service_counterpart_and_records_both_ids(self):
        self.config.download_mode = "video"
        output = Path(self.tmp.name) / "test.mkv"
        output.write_bytes(b"synthetic-video")

        def download(song, **kwargs):
            self.assertEqual(song.video_id, "album-track")
            self.assertEqual(song.download_video_id, "official-mv")
            song.file_path = str(output)
            return True

        with patch("ytmusicvault.ui.download_controller.resolve_mv", return_value="official-mv") as lookup, \
             patch("ytmusicvault.ui.download_controller.Downloader") as downloader, \
             patch("ytmusicvault.ui.download_controller.MetadataWriter") as writer:
            downloader.return_value.download.side_effect = download
            writer.return_value.write.return_value = True
            self.controller.start([Song("album-track", "Title")], self.config, self.credentials)
            songs = wait_for_result(self.results)
        self.assertEqual(songs[0].status, DownloadStatus.COMPLETED)
        self.assertEqual(self.db.mark_downloaded.call_args.kwargs["media_type"], "video")
        self.assertEqual(self.db.mark_downloaded.call_args.kwargs["source_video_id"], "official-mv")
        lookup.assert_called_once()

    def test_missing_mv_does_not_download_cover_video(self):
        from ytmusicvault.core.ytm_client import ServiceError
        self.config.download_mode = "video"
        with patch("ytmusicvault.ui.download_controller.resolve_mv", side_effect=ServiceError("没有对应 MV")), \
             patch("ytmusicvault.ui.download_controller.Downloader") as downloader:
            self.controller.start([Song("album-track", "Title")], self.config, self.credentials)
            songs = wait_for_result(self.results)
            downloader.assert_not_called()
        self.assertEqual(songs[0].status, DownloadStatus.FAILED)
        self.assertIn("MV", songs[0].error_msg)
        self.db.mark_downloaded.assert_not_called()

    def test_cancel_before_download_skips_queued_jobs_and_database_writes(self):
        entered = threading.Event()

        def download(song, **kwargs):
            entered.set()
            kwargs["cancel_event"].wait(3)
            return False

        self.config.concurrent_downloads = 1
        with patch("ytmusicvault.ui.download_controller.Downloader") as downloader:
            downloader.return_value.download.side_effect = download
            self.controller.start([Song("one", "One"), Song("two", "Two")], self.config, self.credentials)
            self.assertTrue(entered.wait(2))
            self.controller.cancel()
            songs = wait_for_result(self.results)
            self.assertEqual(downloader.return_value.download.call_count, 1)
        self.assertEqual([s.status for s in songs], [DownloadStatus.PAUSED] * 2)
        self.db.mark_downloaded.assert_not_called()


if __name__ == "__main__":
    unittest.main()
