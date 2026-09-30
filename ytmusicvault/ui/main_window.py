"""Application shell. All network work belongs to background controllers."""
from dataclasses import replace
from pathlib import Path
import os
from urllib.parse import quote
from PySide6.QtCore import QTimer, Qt, QUrl, QSignalBlocker
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSplitter, QProgressBar, QMessageBox, QInputDialog, QComboBox, QTabWidget)
from .styles import DARK_THEME
from .sidebar import Sidebar
from .song_list import SongListWidget
from .login_dialog import LoginDialog
from .settings_dialog import SettingsDialog
from .library_controller import LibraryController
from .download_controller import DownloadController
from .download_page import DownloadPage
from ..core.auth import AuthManager
from ..core.accounts import AccountStore
from ..core.database import Database, media_type_for_download
from ..core.ytm_client import parse_playlist_id, ServiceError
from ..models.playlist import Playlist
from ..models.song import DownloadStatus
from ..utils.config import AppConfig
from ..utils.helpers import safe_filename
from ..utils.proxy import proxy_description


class MainWindow(QMainWindow):
    def __init__(self, config=None, auth=None, db=None, auto_restore=True):
        super().__init__()
        self._config = config or AppConfig.load()
        self._auth = auth or AuthManager()
        self._accounts = AccountStore(self._auth.directory)
        self._active_account_id = self._accounts.active_id or "default"
        if self._active_account_id != "default":
            self._auth = self._accounts.auth_for(self._active_account_id)
        self._db = db or Database()
        self.library = LibraryController(self._auth, self)
        self._download_log_path = self._accounts.root / "logs" / "download.log"
        self.downloads = DownloadController(self._db, self, log_path=self._download_log_path)
        self._songs, self._playlists = [], []
        self._current_playlist_id, self._current_title = "LM", "我喜欢"
        self._login_dialog = None
        self._login_target = None
        self._pending_account_label = ""
        self._closing = False
        self._account_name = ""
        self._account_verified = False
        self._account_identity_available = False
        self._errors = {}
        self._summary = "请登录以获取个人音乐库。"
        self._batch_done = set()
        self._setup_ui()
        self.library.signed_out.connect(self._signed_out)
        self.library.account_changed.connect(self._account_ready)
        self.library.playlists_loaded.connect(self._playlists_ready)
        self.library.tracks_loaded.connect(self._tracks_ready)
        self.library.error.connect(self._error)
        self.library.busy_changed.connect(self._busy)
        self.downloads.updated.connect(self._download_updated)
        self.downloads.finished.connect(self._download_finished)
        self.downloads.log_entry.connect(self._download_page.append_log)
        self._download_page.load_log_file()
        self._download_page.set_history(self._db.get_all_records())
        self._signed_out()
        if auto_restore:
            QTimer.singleShot(0, lambda: self.library.restore(self._config.proxy_url))

    def _setup_ui(self):
        self.setWindowTitle("YtMusicVault — YouTube Music 音乐库")
        self.resize(self._config.window_width, self._config.window_height)
        self.setMinimumSize(960, 650)
        self.setStyleSheet(DARK_THEME)
        central = QWidget()
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("账号"))
        self._account_combo = QComboBox()
        self._account_combo.setMinimumWidth(140)
        self._refresh_account_choices()
        self._account_combo.currentIndexChanged.connect(self._switch_account)
        toolbar.addWidget(self._account_combo)
        self._login_button = QPushButton("添加账号")
        self._login_button.clicked.connect(lambda: self._login(new=True))
        self._relogin_button = QPushButton("重新登录")
        self._relogin_button.clicked.connect(lambda: self._login(new=False))
        self._refresh_button = QPushButton("刷新音乐库")
        self._refresh_button.clicked.connect(self._refresh_library)
        self._open_button = QPushButton("打开歌单链接")
        self._open_button.clicked.connect(self._open_playlist)
        settings = QPushButton("设置")
        settings.clicked.connect(self._settings)
        self._logout_button = QPushButton("退出登录")
        self._logout_button.clicked.connect(self._logout)
        for button in (self._login_button, self._relogin_button, self._refresh_button,
                       self._open_button, settings, self._logout_button):
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self._login_status = QLabel("未登录")
        layout.addWidget(self._login_status)
        media_row = QHBoxLayout()
        media_row.addWidget(QLabel("下载模式"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("MV · 最高画质（MKV，无损合并）", "video")
        self._mode_combo.addItem("单独音频 · FLAC", "audio_flac")
        self._mode_combo.addItem("单独音频 · MP3", "audio_mp3")
        selected_mode = ("video" if self._config.download_mode == "video" else
                         f"audio_{self._config.audio_format}" if self._config.audio_format in ("flac", "mp3") else "audio_mp3")
        self._mode_combo.setCurrentIndex(max(0, self._mode_combo.findData(selected_mode)))
        self._mode_combo.currentIndexChanged.connect(self._mode_changed)
        media_row.addWidget(self._mode_combo)
        self._proxy_label = QLabel(proxy_description(self._config.proxy_url))
        self._proxy_label.setWordWrap(True)
        media_row.addWidget(self._proxy_label, 1)
        layout.addLayout(media_row)
        notice = QHBoxLayout()
        self._message = QLabel("请登录以获取个人音乐库。")
        self._message.setWordWrap(True)
        notice.addWidget(self._message, 1)
        self._retry_button = QPushButton("重试加载")
        self._retry_button.clicked.connect(self._refresh_library)
        notice.addWidget(self._retry_button)
        layout.addLayout(notice)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._sidebar = Sidebar()
        self._song_list = SongListWidget()
        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._song_list)
        splitter.setSizes([260, 800])
        self._download_page = DownloadPage(log_path=self._download_log_path)
        self._pages = QTabWidget()
        self._pages.addTab(splitter, "音乐库")
        self._pages.addTab(self._download_page, "下载")
        layout.addWidget(self._pages, 1)
        self._sidebar.liked_selected.connect(lambda: self._select("LM", "我喜欢"))
        self._sidebar.playlist_selected.connect(self._select)
        self._song_list.download_clicked.connect(self._download)
        self._song_list.playlist_download_clicked.connect(self._download_playlist)
        self._song_list.open_local_requested.connect(self._open_local_file)
        self._song_list.open_source_requested.connect(self._open_source_page)
        self._download_page.cancel_requested.connect(self.downloads.cancel)
        self._download_page.retry_requested.connect(self._retry_download)
        self._download_page.refresh_requested.connect(
            lambda: self._download_page.set_history(self._db.get_all_records()))
        self._download_page.open_local_requested.connect(self._open_local_file)
        self._download_page.open_source_requested.connect(self._open_source_page)
        self._download_page.open_log_requested.connect(self._open_log_file)
        bottom = QHBoxLayout()
        self._download_label = QLabel("")
        bottom.addWidget(self._download_label, 1)
        self._progress = QProgressBar()
        self._progress.hide()
        bottom.addWidget(self._progress)
        cancel = QPushButton("取消下载")
        cancel.clicked.connect(self.downloads.cancel)
        bottom.addWidget(cancel)
        layout.addLayout(bottom)

    def _refresh_account_choices(self):
        with QSignalBlocker(self._account_combo):
            self._account_combo.clear()
            self._account_combo.addItem("选择已保存账号", "")
            for account_id, label in self._accounts.items():
                self._account_combo.addItem(label, account_id)
            self._account_combo.setCurrentIndex(max(0, self._account_combo.findData(self._active_account_id)))

    def _switch_account(self, *_):
        account_id = self._account_combo.currentData()
        if not account_id:
            self._refresh_account_choices()
            return
        if account_id == self._active_account_id:
            return
        if self.downloads.running:
            QMessageBox.information(self, "下载进行中", "请等待当前下载完成或取消后切换账号。")
            self._refresh_account_choices()
            return
        self._active_account_id = account_id
        self._pending_account_label = ""
        self.library.auth = self._accounts.auth_for(account_id)
        try:
            self._accounts.activate(account_id)
        except OSError:
            self._error("storage", "无法保存当前账号选择；本次仍会尝试切换。")
        self.library.restore(self._config.proxy_url)

    def _login(self, new=False):
        if self.downloads.running:
            QMessageBox.information(self, "下载进行中", "请等待当前下载完成或取消下载后切换账号。")
            return
        if self._login_dialog:
            self._login_dialog.show()
            self._login_dialog.raise_()
            return
        if new:
            default_name = f"账号 {len(self._accounts.items()) + 1}"
            label, accepted = QInputDialog.getText(self, "添加账号", "为账号取一个便于识别的名称：",
                                                    text=default_name)
            if not accepted or not label.strip():
                return
            account_id = ("default" if not self._accounts.items() and
                          not self._accounts.auth_for("default").has_saved_session
                          else self._accounts.new_id())
            self._login_target = (account_id, label.strip())
        else:
            account_id = self._active_account_id or "default"
            label = self._accounts.label(account_id) or self._pending_account_label or "当前账号"
            self._login_target = (account_id, label)
        self._login_dialog = LoginDialog(parent=self, proxy_url=self._config.proxy_url)
        self._login_dialog.remember.setChecked(new)
        self._login_dialog.submitted.connect(self._submit_login)
        self._login_dialog.finished.connect(self._login_dialog_closed)
        self._login_dialog.show()

    def _submit_login(self, request):
        account_id, label = self._login_target
        self._active_account_id = account_id
        self._pending_account_label = label
        self.library.auth = self._accounts.auth_for(account_id)
        self.library.login(request, self._config.proxy_url)

    def _login_dialog_closed(self, *_):
        self._login_dialog = None
        self._login_target = None

    def _sync_saved_account(self):
        account_id = self._active_account_id
        if not self.library.client or not account_id:
            return
        if self.library.auth.has_saved_session:
            label = (self._account_name if self._account_identity_available and self._account_name and
                     self._account_name != "账号未验证" else
                     self._pending_account_label or self._accounts.label(account_id) or "当前账号")
            try:
                self._accounts.register(account_id, label)
            except OSError:
                self._error("storage", "音乐库已连接，但无法保存账号列表。")
                return
            self._pending_account_label = ""
        elif self._accounts.label(account_id):
            try:
                self._accounts.forget(account_id)
            except OSError:
                self._error("storage", "无法更新账号列表。")
        self._refresh_account_choices()

    def _account_ready(self, account):
        self._account_name = account["accountName"]
        self._account_verified = account.get("verified", True)
        self._account_identity_available = account.get(
            "identityAvailable", self._account_verified and self._account_name != "账号未验证")
        handle = account.get("channelHandle") or ""
        alias = self._pending_account_label or self._accounts.label(self._active_account_id)
        identity_text = f"Google 账号：{self._account_name} {handle}" if self._account_identity_available else "账号身份未验证"
        self._login_status.setText(f"{alias} · {identity_text}" if alias else identity_text)
        if self._login_dialog:
            self._login_dialog.headers.clear()
            self._login_dialog.accept()
        for button in (self._refresh_button, self._open_button, self._logout_button):
            button.setEnabled(True)
        self._sidebar.setEnabled(True)
        self._refresh_library()
        if self._account_verified:
            QTimer.singleShot(0, self._sync_saved_account)

    def _signed_out(self):
        self._errors.clear()
        self._summary = "请登录以获取个人音乐库。"
        self._account_name = ""
        self._account_verified = False
        self._account_identity_available = False
        self._login_status.setText("未登录")
        self._songs, self._playlists = [], []
        self._current_playlist_id, self._current_title = "LM", "我喜欢"
        self._sidebar.set_playlists([])
        self._sidebar.setEnabled(False)
        self._song_list.set_songs([])
        self._song_list.setEnabled(False)
        self._retry_button.hide()
        self._message.setText("请登录以获取个人音乐库。")
        for button in (self._refresh_button, self._open_button, self._logout_button):
            button.setEnabled(False)

    def _logout(self):
        if self.downloads.running:
            QMessageBox.information(self, "下载进行中", "请先完成或取消下载。")
            return
        try:
            previous_id = self._active_account_id
            self.library.logout()
            if self._accounts.label(previous_id):
                self._accounts.forget(previous_id)
            self._active_account_id = ""
            self._pending_account_label = ""
            self._refresh_account_choices()
        except OSError:
            self._signed_out()
            self._error("storage", "已断开会话，但无法清除本地会话文件。")

    def _busy(self, kind, busy):
        if busy:
            self._errors.pop(kind, None)
        if kind == "login":
            if self._login_dialog:
                self._login_dialog.set_busy(busy)
            self._account_combo.setEnabled(not busy)
            self._login_button.setEnabled(not busy)
            self._relogin_button.setEnabled(not busy)
            if busy:
                self._login_status.setText("正在验证登录…")
            elif not self.library.client:
                self._login_status.setText("未登录")
        if kind == "tracks":
            self._song_list.setEnabled(not busy and bool(self.library.client))
            if busy:
                self._summary = f"正在加载：{self._current_title}…"
        self._render_message()

    def _error(self, kind, message):
        if kind == "login" and self._login_dialog:
            self._login_dialog.show_error(message)
        self._errors[kind] = message
        if kind == "tracks":
            self._summary = f"{self._current_title} · 加载失败"
        self._render_message()

    def _render_message(self):
        self._message.setText("\n".join([self._summary, *self._errors.values()]))
        self._retry_button.setVisible(bool(self._errors) and bool(self.library.client))

    def _refresh_library(self):
        if self.library.client:
            self.library.refresh()
            self._select(self._current_playlist_id, self._current_title)

    def _playlists_ready(self, playlists):
        # Keep a manually opened or recently removed playlist selected, so that
        # the navigation and currently displayed tracks cannot disagree.
        if self._current_playlist_id != "LM" and not any(p.playlist_id == self._current_playlist_id for p in playlists):
            playlists = playlists + [Playlist(self._current_playlist_id, self._current_title)]
        self._playlists = playlists
        self._sidebar.set_playlists(playlists)
        self._sidebar.select(self._current_playlist_id)
        alias = self._pending_account_label or self._accounts.label(self._active_account_id)
        prefix = (f"Google 账号：{self._account_name}" if self._account_identity_available else
                  "音乐库已连接（账号身份未验证）")
        if alias:
            prefix = f"{alias} · {prefix}"
        self._login_status.setText(f"{prefix} · {len(playlists)} 个播放列表")
        if playlists:
            QTimer.singleShot(0, self._sync_saved_account)

    def _select(self, playlist_id, title):
        if not self.library.client:
            return
        self._current_playlist_id, self._current_title = playlist_id, title
        self._sidebar.select(playlist_id)
        self._song_list.set_songs([])
        self._songs = []
        self.library.load_tracks(playlist_id)

    def _tracks_ready(self, playlist_id, batch):
        if playlist_id != self._current_playlist_id:
            return
        self._songs = batch.songs
        # A record is reusable only while its downloaded file still exists.
        self._restore_download_status()
        self._song_list.set_songs(self._songs)
        self._song_list.setEnabled(True)
        if playlist_id == "LM":
            self._sidebar.set_liked_count(len(batch.songs))
        text = f"{self._current_title} · {len(batch.songs)} 首可用歌曲"
        if batch.skipped:
            text += f" · {batch.skipped} 项不可用或无视频 ID"
        if not batch.songs:
            text += "（空列表）"
            if not self._account_verified and not self._account_identity_available and not self._playlists:
                text += "。若预期有收藏，请重新导出完整的 YouTube Music 登录 Cookie。"
        self._summary = text
        self._render_message()
        if playlist_id == "LM" and batch.songs:
            QTimer.singleShot(0, self._sync_saved_account)

    def _restore_download_status(self):
        media_type = media_type_for_download(self._config.download_mode, self._config.audio_format)
        records = {r[0]: r[5] for r in self._db.get_all_records(media_type)
                   if r[8] == "completed" and r[5] and os.path.isfile(r[5])}
        for song in self._songs:
            song.download_mode = self._config.download_mode
            song.audio_format = self._config.audio_format
            song.status, song.file_path, song.error_msg = DownloadStatus.PENDING, "", ""
            if song.video_id in records:
                song.status = DownloadStatus.COMPLETED
                song.file_path = records[song.video_id]

    def _mode_changed(self, *_):
        self._apply_selected_download_type()
        self._config.save()
        self._restore_download_status()
        self._song_list.set_songs(self._songs)

    def _apply_selected_download_type(self):
        selected = self._mode_combo.currentData()
        if selected == "video":
            self._config.download_mode = "video"
        else:
            self._config.download_mode = "audio"
            self._config.audio_format = "flac" if selected == "audio_flac" else "mp3"

    def _open_playlist(self):
        value, ok = QInputDialog.getText(self, "打开播放列表", "粘贴 YouTube Music / YouTube 歌单链接或 ID：")
        if not ok:
            return
        try:
            pid = parse_playlist_id(value)
        except ServiceError as exc:
            self._error("tracks", str(exc))
            return
        title = next((p.title for p in self._playlists if p.playlist_id == pid), pid)
        if not any(p.playlist_id == pid for p in self._playlists) and pid != "LM":
            self._playlists.append(Playlist(pid, title))
            self._sidebar.set_playlists(self._playlists)
        self._select(pid, title)

    def _settings(self):
        previous_proxy = self._config.proxy_url
        dialog = SettingsDialog(self._config, self)
        if dialog.exec():
            self._config.save()
            self._proxy_label.setText(proxy_description(self._config.proxy_url))
            if previous_proxy != self._config.proxy_url and self.library.client:
                self._message.setText("代理设置已更新。已连接的音乐库需重新登录，已打开的内置浏览器需关闭后重新打开。")

    def _download_playlist(self):
        if self._songs:
            self._download(list(self._songs))

    def _download(self, songs, mode=None, audio_format=None):
        if self.downloads.running or not self.library.credentials:
            return
        config = replace(self._config)
        if mode in ("audio_flac", "audio_mp3"):
            config.download_mode = "audio"
            config.audio_format = "flac" if mode == "audio_flac" else "mp3"
        elif mode:
            config.download_mode = mode
        if audio_format in ("flac", "mp3", "m4a"):
            config.audio_format = audio_format
        media_type = media_type_for_download(config.download_mode, config.audio_format)
        existing = {record[0] for record in self._db.get_all_records(media_type)
                    if record[8] == "completed" and record[5] and os.path.isfile(record[5])}
        songs = [replace(song, download_mode=config.download_mode, audio_format=config.audio_format,
                         file_path="", error_msg="", progress=0, speed="", stage="")
                 for song in songs if song.video_id not in existing]
        if not songs:
            self._download_label.setText("这些歌曲已按所选类型下载。")
            return
        if config.create_playlist_folders:
            config.download_dir = str(Path(config.download_dir) / (safe_filename(self._current_title) or "Playlist"))
        self._batch_done = set()
        self.downloads.start(songs, config, self.library.credentials)
        self._download_page.set_batch(songs)
        self._pages.setCurrentIndex(1)
        self._mode_combo.setEnabled(False)
        self._progress.setRange(0, self.downloads.total)
        self._progress.setValue(0)
        self._progress.show()

    def _download_updated(self, song):
        if (song.download_mode == self._config.download_mode and
                (song.download_mode == "video" or song.audio_format == self._config.audio_format)):
            for index, current in enumerate(self._songs):
                if current.video_id == song.video_id:
                    self._songs[index] = song
            self._song_list.update_song_status(song)
        self._download_page.update_task(song)
        if song.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.PAUSED):
            self._batch_done.add(song.video_id)
        self._progress.setValue(len(self._batch_done))
        stage = f" · {song.stage}" if song.stage else ""
        self._download_label.setText(f"{song.title}{stage} · {song.progress:.0f}% {song.speed} {song.error_msg}")

    def _download_finished(self, songs):
        self._mode_combo.setEnabled(True)
        self._download_page.finish_batch(songs)
        self._download_page.set_history(self._db.get_all_records())
        self._restore_download_status()
        self._song_list.set_songs(self._songs)
        completed = sum(s.status == DownloadStatus.COMPLETED for s in songs)
        self._download_label.setText(f"本批结束：成功 {completed} / {len(songs)}，失败或取消 {len(songs) - completed}")
        self._progress.hide()
        if self._closing:
            self.close()

    def _retry_download(self, song):
        if not self.library.credentials:
            QMessageBox.information(self, "尚未登录", "请先选择或登录账号，再重试下载。")
            return
        self._download([song], mode=song.download_mode, audio_format=song.audio_format)

    def _open_log_file(self, path):
        if path and Path(path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))

    def _open_local_file(self, path):
        if not path or not Path(path).is_file():
            QMessageBox.warning(self, "文件不存在", "本地文件已移动或删除，请在下载页面刷新记录。")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve()))):
            QMessageBox.warning(self, "无法打开", "系统未能打开该文件，请检查默认播放器。")

    def _open_source_page(self, video_id):
        if not video_id:
            return
        url = QUrl("https://music.youtube.com/watch?v=" + quote(video_id, safe=""))
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(self, "无法打开", "系统未能打开源页面，请检查浏览器设置。")

    def closeEvent(self, event):
        if self.downloads.running:
            self._closing = True
            self.downloads.cancel()
            self._message.setText("正在停止下载，完成清理后关闭…")
            event.ignore()
            return
        self.library.close()
        self._config.window_width, self._config.window_height = self.width(), self.height()
        self._config.save()
        self._db.close()
        event.accept()
