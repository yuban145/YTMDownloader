import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from ytmusicvault.core.database import Database
from ytmusicvault.models.song import DownloadStatus, Song
from ytmusicvault.ui.download_page import DownloadPage
from ytmusicvault.ui.song_list import SongListWidget

APP = QApplication.instance() or QApplication([])


class DownloadPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.page = DownloadPage()
        self.addCleanup(self.page.close)

    def test_live_tasks_retry_and_durable_history(self):
        failed = Song("one", "First", artist="Artist", download_mode="video")
        completed = Song("two", "Second", download_mode="audio")
        self.page.set_batch([failed, completed])
        self.assertEqual(self.page.tasks.rowCount(), 2)
        self.assertTrue(self.page.cancel_button.isEnabled())
        failed.status, failed.progress, failed.error_msg = DownloadStatus.FAILED, 35, "test failure"
        completed.status = DownloadStatus.COMPLETED
        self.page.finish_batch([failed, completed])
        self.assertEqual(self.page.tasks.item(0, 4).text(), "失败")
        self.page.tasks.selectRow(0)
        self.assertTrue(self.page.retry_button.isEnabled())
        retried = []
        self.page.retry_requested.connect(retried.append)
        self.page._retry_selected()
        self.assertEqual(retried[0].video_id, "one")
        self.assertEqual(retried[0].download_mode, "video")
        db = Database(str(Path(self.tmp.name) / "history.db"))
        self.addCleanup(db.close)
        output = Path(self.tmp.name) / "saved.mkv"
        output.write_bytes(b"media")
        db.mark_downloaded("video", "Saved", "Artist", file_path=str(output), media_type="video")
        self.page.set_history(db.get_all_records())
        self.assertEqual(self.page.history.rowCount(), 1)
        self.assertEqual(self.page.history.item(0, 4).text(), "已保存")
        opened, sourced = [], []
        self.page.open_local_requested.connect(opened.append)
        self.page.open_source_requested.connect(sourced.append)
        with patch("ytmusicvault.ui.download_page.QMenu") as menu_type:
            local, source = Mock(), Mock()
            menu_type.return_value.addAction.side_effect = [local, source]
            menu_type.return_value.exec.return_value = local
            self.page._context_menu(self.page.history, QPoint(10, 10))
        self.assertEqual(opened, [str(output)])
        self.page._open_row_file(self.page.history, 0)
        self.assertEqual(opened[-1], str(output))
        with patch("ytmusicvault.ui.download_page.QMenu") as menu_type:
            local, source = Mock(), Mock()
            menu_type.return_value.addAction.side_effect = [local, source]
            menu_type.return_value.exec.return_value = source
            self.page._context_menu(self.page.history, QPoint(10, 10))
        self.assertEqual(sourced, ["video"])
        self.page.search.setText("unrelated")
        self.assertTrue(self.page.history.isRowHidden(0))
        self.page.search.setText("Saved")
        self.assertFalse(self.page.history.isRowHidden(0))

    def test_song_list_context_actions_target_clicked_row(self):
        widget = SongListWidget()
        self.addCleanup(widget.close)
        path = Path(self.tmp.name) / "song.mkv"
        path.write_bytes(b"media")
        first = Song("first", "First", file_path=str(path), status=DownloadStatus.COMPLETED)
        second = Song("second", "Second")
        widget.set_songs([first, second])
        opened, sourced = [], []
        widget.open_local_requested.connect(opened.append)
        widget.open_source_requested.connect(sourced.append)
        with patch("ytmusicvault.ui.song_list.QMenu") as menu_type:
            local, source = Mock(), Mock()
            menu_type.return_value.addAction.side_effect = [local, source]
            menu_type.return_value.exec.return_value = local
            widget._context_menu(QPoint(10, 10))
        self.assertEqual(opened, [str(path)])
        with patch("ytmusicvault.ui.song_list.QMenu") as menu_type:
            local, source = Mock(), Mock()
            menu_type.return_value.addAction.side_effect = [local, source]
            menu_type.return_value.exec.return_value = source
            widget._context_menu(QPoint(10, 10))
        self.assertEqual(sourced, ["first"])

    def test_playlist_bulk_action_emits_for_all_loaded_tracks(self):
        widget = SongListWidget()
        self.addCleanup(widget.close)
        widget.set_songs([Song("one", "First"), Song("two", "Second")])
        emitted = []
        widget.playlist_download_clicked.connect(lambda: emitted.append(True))
        self.assertTrue(widget._download_playlist_btn.isEnabled())
        self.assertIn("2", widget._download_playlist_btn.text())
        widget._on_download_playlist_clicked()
        self.assertEqual(emitted, [True])
