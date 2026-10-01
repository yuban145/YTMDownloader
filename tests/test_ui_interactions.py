import os
import unittest
from dataclasses import replace
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog

from ytmusicvault.core.auth import LoginRequest
from ytmusicvault.models.song import DownloadStatus, Song
from ytmusicvault.ui.login_dialog import LoginDialog
from ytmusicvault.ui.song_list import SongListWidget


APP = QApplication.instance() or QApplication([])


class SongSelectionTests(unittest.TestCase):
    def setUp(self):
        self.widget = SongListWidget()
        self.addCleanup(self.widget.close)
        self.songs = [Song("one", "First"), Song("two", "Second")]
        self.widget.set_songs(self.songs)

    def test_select_all_works_on_first_click_and_can_clear(self):
        self.widget._select_all_cb.click()
        self.assertEqual(self.widget.get_selected_songs(), self.songs)
        self.assertEqual(self.widget._select_all_cb.checkState(), Qt.CheckState.Checked)
        self.widget._select_all_cb.click()
        self.assertEqual(self.widget.get_selected_songs(), [])

    def test_individual_selection_updates_aggregate_checkbox(self):
        self.widget._checkboxes[0].setChecked(True)
        self.assertEqual(self.widget._select_all_cb.checkState(), Qt.CheckState.PartiallyChecked)
        self.widget._select_all_cb.click()
        self.assertEqual(self.widget.get_selected_songs(), self.songs)
        self.widget._checkboxes[0].setChecked(False)
        self.assertEqual(self.widget._select_all_cb.checkState(), Qt.CheckState.PartiallyChecked)
        self.widget._checkboxes[1].setChecked(False)
        self.assertEqual(self.widget._select_all_cb.checkState(), Qt.CheckState.Unchecked)

    def test_status_update_survives_search_rebuild(self):
        updated = replace(self.songs[0], status=DownloadStatus.COMPLETED, file_path="test.mkv")
        self.widget.update_song_status(updated)
        self.widget._search_input.setText("First")
        self.assertEqual(self.widget._filtered_songs[0].status, DownloadStatus.COMPLETED)
        self.assertEqual(self.widget._filtered_songs[0].file_path, "test.mkv")


class FakeEmbeddedDialog(QDialog):
    submitted = Signal(object)

    def __init__(self, parent=None, proxy_url=None):
        super().__init__(parent)


class LoginInteractionTests(unittest.TestCase):
    def setUp(self):
        self.dialog = LoginDialog()
        self.addCleanup(self.dialog.close)

    def test_busy_login_does_not_allow_embedded_resubmission(self):
        submitted = []
        self.dialog.submitted.connect(submitted.append)
        self.dialog.set_busy(True)
        self.dialog._submit_embedded(LoginRequest("embedded", "synthetic"))
        self.assertEqual(submitted, [])
        with patch("ytmusicvault.ui.login_dialog.EmbeddedBrowserDialog") as browser:
            self.dialog._open_embedded()
        browser.assert_not_called()

    def test_closing_login_closes_embedded_dialog(self):
        with patch("ytmusicvault.ui.login_dialog.EmbeddedBrowserDialog", FakeEmbeddedDialog):
            self.dialog.show()
            self.dialog._open_embedded()
        embedded = self.dialog._embedded
        finished = []
        embedded.finished.connect(finished.append)
        self.dialog.reject()
        self.assertEqual(finished, [QDialog.DialogCode.Rejected])
        self.assertIsNone(self.dialog._embedded)


if __name__ == "__main__":
    unittest.main()
