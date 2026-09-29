import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from ytmusicvault.core.auth import AuthError, AuthManager, LoginRequest, normalize_headers
from ytmusicvault.core.ytm_client import TrackBatch, SessionExpired
from ytmusicvault.ui.library_controller import LibraryController
from ytmusicvault.ui.main_window import MainWindow
from ytmusicvault.core.database import Database
from ytmusicvault.utils.config import AppConfig
from ytmusicvault.models.playlist import Playlist
from ytmusicvault.models.song import Song

APP = QApplication.instance() or QApplication([])


def pump_until(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.005)
    APP.processEvents()
    if not predicate():
        raise AssertionError("Background result was not delivered")


def request(remember=False):
    return LoginRequest("headers", json.dumps({"cookie": "__Secure-3PAPISID=synthetic"}), remember=remember)


class FakeClient:
    _session = None
    def __init__(self):
        self.closed = False
    def close(self):
        self.closed = True
    def get_playlists(self):
        return [Playlist("PL1", "测试列表")]
    def get_tracks(self, pid):
        return TrackBatch([Song(pid, pid)])


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.auth = AuthManager(self.tmp.name)
        self.client = FakeClient()
        self.controller = LibraryController(self.auth, connect=lambda *a: (self.client, {"accountName": "Test"}))
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.controller.close)

    def login(self, remember=False):
        ready = []
        self.controller.account_changed.connect(ready.append)
        self.controller.login(request(remember))
        pump_until(lambda: bool(ready))

    def test_success_persists_only_when_requested_and_logout_clears(self):
        self.login(remember=True)
        self.assertTrue(self.auth.path.exists())
        self.controller.logout()
        self.assertFalse(self.auth.has_saved_session)
        self.assertIsNone(self.controller.client)

    def test_failed_online_verification_keeps_old_saved_credentials(self):
        self.auth.save(normalize_headers({"cookie": "__Secure-3PAPISID=previous"}))
        old = self.auth.path.read_bytes()
        self.controller._connect = Mock(side_effect=SessionExpired("请重新登录"))
        errors = []
        self.controller.error.connect(lambda *x: errors.append(x))
        self.controller.login(request(True))
        pump_until(lambda: bool(errors))
        self.assertIsNone(self.controller.client)
        self.assertEqual(self.auth.path.read_bytes(), old)

    def test_session_only_login_removes_old_remembered_account(self):
        self.auth.save(normalize_headers({"cookie": "__Secure-3PAPISID=old"}))
        self.login(remember=False)
        self.assertFalse(self.auth.has_saved_session)
        self.assertIsNotNone(self.controller.credentials)

    def test_unverified_empty_library_does_not_overwrite_saved_login(self):
        self.auth.save(normalize_headers({"cookie": "__Secure-3PAPISID=previous"}))
        original = self.auth.path.read_bytes()
        self.controller._connect = lambda *a: (self.client, {"accountName": "未验证", "verified": False})
        self.client.get_playlists = lambda: []
        ready = []
        loaded = []
        self.controller.account_changed.connect(ready.append)
        self.controller.playlists_loaded.connect(loaded.append)
        self.controller.login(request(remember=True))
        pump_until(lambda: bool(ready))
        self.assertEqual(self.auth.path.read_bytes(), original)
        self.controller.refresh()
        pump_until(lambda: len(loaded) == 1)
        self.assertEqual(self.auth.path.read_bytes(), original)
        self.client.get_playlists = lambda: [Playlist("PL1", "Personal")]
        self.controller.refresh()
        pump_until(lambda: len(loaded) == 2)
        self.assertIn("synthetic", self.auth.path.read_text(encoding="utf-8"))

    def test_slow_login_keeps_qt_responsive(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        def connect(*args):
            gate.wait(2)
            return self.client, {"accountName": "Test"}
        self.controller._connect = connect
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        self.controller.login(request())
        pump_until(lambda: bool(ticks))
        self.assertIsNone(self.controller.client)
        gate.set()
        pump_until(lambda: self.controller.client is not None)

    def test_late_tracks_cannot_replace_new_selection(self):
        self.login()
        started, gate = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        def tracks(pid):
            if pid == "first":
                started.set()
                gate.wait(2)
            return TrackBatch([Song(pid, pid)])
        self.client.get_tracks = tracks
        delivered = []
        self.controller.tracks_loaded.connect(lambda pid, batch: delivered.append(pid))
        self.controller.load_tracks("first")
        pump_until(started.is_set)
        self.controller.load_tracks("second")
        gate.set()
        pump_until(lambda: bool(delivered))
        self.assertEqual(delivered, ["second"])

    def test_logout_during_login_cannot_restore_or_save_session(self):
        started, gate = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        def connect(*args):
            started.set()
            gate.wait(2)
            return self.client, {"accountName": "Old"}
        self.controller._connect = connect
        delivered = []
        self.controller.account_changed.connect(delivered.append)
        self.controller.login(request(True))
        pump_until(started.is_set)
        self.controller.logout()
        gate.set()
        pump_until(lambda: self.client.closed)
        self.assertEqual(delivered, [])
        self.assertFalse(self.auth.has_saved_session)

    def test_expired_session_clears_view_but_retains_saved_file_for_retry(self):
        self.login(remember=True)
        self.client.get_playlists = Mock(side_effect=SessionExpired("会话过期"))
        errors = []
        self.controller.error.connect(lambda *x: errors.append(x))
        self.controller.refresh()
        pump_until(lambda: bool(errors))
        self.assertIsNone(self.controller.client)
        self.assertTrue(self.auth.has_saved_session)

    def test_empty_tracks_and_playlists_load_independently(self):
        self.login()
        self.client.get_playlists = Mock(side_effect=RuntimeError("parse error"))
        self.client.get_tracks = lambda pid: TrackBatch()
        tracks, errors = [], []
        self.controller.tracks_loaded.connect(lambda *x: tracks.append(x))
        self.controller.error.connect(lambda *x: errors.append(x))
        self.controller.refresh()
        self.controller.load_tracks("LM")
        pump_until(lambda: bool(tracks) and bool(errors))
        self.assertEqual(tracks[0][1].songs, [])
        self.assertIsNotNone(self.controller.client)

    def test_main_window_end_to_end_with_fake_service(self):
        config = AppConfig(_config_path=str(Path(self.tmp.name) / "config.json"))
        db = Database(str(Path(self.tmp.name) / "test.db"))
        window = MainWindow(config, self.auth, db, auto_restore=False)
        self.addCleanup(window.close)
        window.library._connect = lambda *a: (FakeClient(), {"accountName": "Example"})
        window.library.login(request())
        pump_until(lambda: len(window._songs) == 1)
        self.assertEqual(window._songs[0].video_id, "LM")
        self.assertIn("Example", window._login_status.text())
        window._select("PL1", "测试列表")
        pump_until(lambda: len(window._songs) == 1 and window._songs[0].video_id == "PL1")
        window._error("playlists", "列表加载失败")
        window._tracks_ready("PL1", TrackBatch())
        self.assertIn("列表加载失败", window._message.text())
        window.library.logout()
        self.assertEqual(window._songs, [])
        self.assertFalse(window._sidebar.isEnabled())

    def test_main_window_can_switch_two_saved_accounts_without_mixing_sessions(self):
        config = AppConfig(_config_path=str(Path(self.tmp.name) / "config-accounts.json"))
        db = Database(str(Path(self.tmp.name) / "accounts.db"))
        window = MainWindow(config, self.auth, db, auto_restore=False)
        self.addCleanup(window.close)
        window.library._connect = lambda credentials, *_: (
            FakeClient(), {"accountName": credentials.headers["cookie"].split("=")[-1], "verified": True})
        window._login_target = ("default", "主账号")
        window._submit_login(LoginRequest("headers", json.dumps({
            "cookie": "__Secure-3PAPISID=first"}), remember=True))
        pump_until(lambda: window._accounts.label("default") == "first")
        second_id = window._accounts.new_id()
        window._login_target = (second_id, "备用账号")
        window._submit_login(LoginRequest("headers", json.dumps({
            "cookie": "__Secure-3PAPISID=second"}), remember=True))
        pump_until(lambda: window._accounts.label(second_id) == "second")
        self.assertIn("first", window._accounts.auth_for("default").load().headers["cookie"])
        self.assertIn("second", window._accounts.auth_for(second_id).load().headers["cookie"])
        window._account_combo.setCurrentIndex(window._account_combo.findData("default"))
        pump_until(lambda: window.library.credentials is not None and
                   "first" in window.library.credentials.headers["cookie"])
        self.assertEqual(window._accounts.active_id, "default")
        self.assertEqual(window._account_combo.currentText(), "first")
        self.assertIn("first", window._login_status.text())

    def test_main_window_queues_every_loaded_playlist_track(self):
        config = AppConfig(_config_path=str(Path(self.tmp.name) / "config-playlist.json"),
                           create_playlist_folders=False)
        db = Database(str(Path(self.tmp.name) / "playlist.db"))
        window = MainWindow(config, self.auth, db, auto_restore=False)
        self.addCleanup(window.close)
        window.library.credentials = normalize_headers({"cookie": "__Secure-3PAPISID=synthetic"})
        window._songs = [Song("one", "First"), Song("two", "Second"), Song("three", "Third")]
        window._song_list.set_songs(window._songs)
        window.downloads.total = 0
        with patch.object(window.downloads, "start") as start:
            window._download_playlist()
        queued, config_snapshot = start.call_args.args[:2]
        self.assertEqual([song.video_id for song in queued], ["one", "two", "three"])
        self.assertEqual(config_snapshot.download_mode, "video")


if __name__ == "__main__":
    unittest.main()
