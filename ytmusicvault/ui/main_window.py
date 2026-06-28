"""Main application window — orchestrates all UI and core logic."""

import os
import threading
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QStatusBar, QMenuBar, QMenu,
    QMessageBox, QLabel, QProgressBar, QWidget, QHBoxLayout,
    QVBoxLayout, QFileDialog, QApplication,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtNetwork import QNetworkProxy

from .sidebar import Sidebar
from .song_list import SongListWidget
from .styles import DARK_THEME

from ..models.song import Song, DownloadStatus
from ..models.playlist import Playlist
from ..core.auth import AuthManager
from ..core.ytm_client import YtmClient
from ..core.downloader import Downloader
from ..core.metadata import MetadataWriter
from ..core.queue_manager import QueueManager
from ..core.database import Database
from ..utils.config import AppConfig


class MainWindow(QMainWindow):
    """YtMusicVault main window."""

    # Signals for cross-thread communication
    status_updated = Signal(Song)  # single song status change
    progress_updated = Signal(str, float, str, str)  # video_id, percent, speed, eta

    def __init__(self):
        super().__init__()

        # ── Core components ────────────────────────────
        self._config = AppConfig.load()
        self._db = Database()
        self._auth = AuthManager()
        self._ytm: Optional[YtmClient] = None
        self._downloader: Optional[Downloader] = None
        self._metadata = MetadataWriter()
        self._queue: Optional[QueueManager] = None

        # ── State ──────────────────────────────────────
        self._current_playlist_id: Optional[str] = None
        self._songs: list[Song] = []
        self._playlists: list[Playlist] = []
        self._downloading = False
        self._login_window = None

        # ── UI setup ───────────────────────────────────
        self._setup_ui()
        self._connect_signals()
        self._apply_theme()

        # Restore window size
        self.resize(self._config.window_width, self._config.window_height)

        # Auto-login attempt
        QTimer.singleShot(100, self._auto_login)

    # ═══════════════════════════════════════════════════════
    #  UI Setup
    # ═══════════════════════════════════════════════════════

    def _setup_ui(self):
        """Build the main window layout."""
        self.setWindowTitle("YtMusicVault — YouTube Music 下载器")
        self.setMinimumSize(900, 600)

        # ── Menu bar ───────────────────────────────────
        menubar = self.menuBar()

        # Account menu
        account_menu = menubar.addMenu("账号(&A)")
        account_menu.addAction("🔐 登录 YouTube Music", self._login_with_browser)
        account_menu.addAction("🔄 刷新音乐库 (F5)", self._refresh_library, "F5")
        account_menu.addSeparator()
        account_menu.addAction("📂 导入 Cookies 文件", self._import_cookies)
        account_menu.addAction("📤 导出 Cookies 文件", self._export_cookies)
        account_menu.addSeparator()
        account_menu.addAction("登出", self._logout)

        # Settings menu
        settings_menu = menubar.addMenu("设置(&S)")
        settings_menu.addAction("偏好设置...", self._open_settings)

        # Help menu
        help_menu = menubar.addMenu("帮助(&H)")
        help_menu.addAction("使用指南", self._open_guide)
        help_menu.addSeparator()
        help_menu.addAction("关于", self._show_about)

        # ── Central widget ─────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Splitter: sidebar | content
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # Sidebar
        self._sidebar = Sidebar()
        self._splitter.addWidget(self._sidebar)

        # Right side: song list
        self._song_list = SongListWidget()
        self._splitter.addWidget(self._song_list)

        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([220, 780])
        main_layout.addWidget(self._splitter)

        # ── Status bar ─────────────────────────────────
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        # Status bar widgets
        self._login_status = QLabel("🔒 未登录")
        self._status_bar.addWidget(self._login_status)

        self._status_bar.addWidget(QLabel("  "), 1)

        # Overall progress bar
        self._overall_progress = QProgressBar()
        self._overall_progress.setMaximumWidth(250)
        self._overall_progress.setMaximumHeight(14)
        self._overall_progress.setVisible(False)
        self._status_bar.addPermanentWidget(self._overall_progress)

        self._speed_label = QLabel("")
        self._status_bar.addPermanentWidget(self._speed_label)

        self._count_label = QLabel("")
        self._status_bar.addPermanentWidget(self._count_label)

    def _connect_signals(self):
        """Wire up signals and slots."""
        # Sidebar playlist selection
        self._sidebar.liked_selected.connect(self._on_liked_selected)
        self._sidebar.playlist_selected.connect(self._on_playlist_selected)

        # Download button
        self._song_list.download_clicked.connect(self._on_download_clicked)

        # Cross-thread status updates
        self.status_updated.connect(self._on_status_updated)
        self.progress_updated.connect(self._on_progress_updated)

    def _apply_theme(self):
        """Apply dark theme stylesheet."""
        self.setStyleSheet(DARK_THEME)

    # ═══════════════════════════════════════════════════════
    #  Proxy
    # ═══════════════════════════════════════════════════════

    def _apply_webengine_proxy(self):
        """Apply proxy settings to QtWebEngine (for login browser)."""
        if not self._config.proxy_enabled:
            return
        proxy_url = self._config.proxy_url
        if not proxy_url:
            return

        # QWebEngine reads proxy from command-line or environment
        # We set via QNetworkProxy for the application
        from PySide6.QtNetwork import QNetworkProxy
        proxy = QNetworkProxy()
        if self._config.proxy_type == "socks5":
            proxy.setType(QNetworkProxy.ProxyType.Socks5Proxy)
        else:
            proxy.setType(QNetworkProxy.ProxyType.HttpProxy)
        proxy.setHostName(self._config.proxy_host)
        proxy.setPort(self._config.proxy_port)
        if self._config.proxy_username:
            proxy.setUser(self._config.proxy_username)
            proxy.setPassword(self._config.proxy_password)
        QNetworkProxy.setApplicationProxy(proxy)

    # ═══════════════════════════════════════════════════════
    #  Auth
    # ═══════════════════════════════════════════════════════

    def _auto_login(self):
        """Try to auto-login from saved credentials."""
        # Apply proxy before any network access
        self._apply_webengine_proxy()

        ytm = self._auth.login(proxy_url=self._config.proxy_url)
        if ytm:
            self._ytm = YtmClient(ytm)
            self._login_status.setText("✅ 已登录（Cookies 已加载）")
            self._login_status.setStyleSheet("color: #a6e3a1;")
            self._load_library()
        else:
            self._login_status.setText("🔒 未登录 — 请登录账号")
            self._login_status.setStyleSheet("color: #f38ba8;")

    def _login_with_browser(self):
        """Open embedded browser to music.youtube.com, let user log in,
        extract cookies automatically. Works entirely in-app, no OAuth needed."""
        from .login_browser import LoginBrowserWidget

        # Set proxy for QWebEngine before opening browser
        self._apply_webengine_proxy()

        # Close previous login window if still open
        if self._login_window is not None:
            try:
                self._login_window.close()
            except RuntimeError:
                pass
            self._login_window = None
            self._login_browser = None

        self._login_window = QWidget(None, Qt.WindowType.Window)
        self._login_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._login_window.setWindowTitle("YtMusicVault — 登录 YouTube Music")
        self._login_window.resize(800, 650)
        self._login_window.setMinimumSize(700, 500)

        # Clean up references when user closes via X
        self._login_window.destroyed.connect(self._on_login_window_closed)

        layout = QVBoxLayout(self._login_window)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._login_browser = LoginBrowserWidget(self._auth.cookies_path)
        self._login_browser.login_success.connect(self._on_login_browser_success)
        self._login_browser.login_failed.connect(self._on_login_browser_failed)

        layout.addWidget(self._login_browser)
        self._login_window.setStyleSheet(DARK_THEME)
        self._login_window.show()

    def _on_login_window_closed(self):
        """User closed the login window manually (via X button)."""
        self._login_window = None
        self._login_browser = None

    def _on_login_browser_success(self):
        """Cookies extracted successfully."""
        if self._login_window:
            self._login_window.close()
            self._login_window = None
            self._login_browser = None

        self._login_status.setText("✅ Cookies 已保存（下次启动自动登录），正在加载音乐库...")
        self._login_status.setStyleSheet("color: #f9e2af;")
        self._auto_login()

    def _on_login_browser_failed(self, error_msg: str):
        """Login browser failed."""
        if self._login_window:
            self._login_window.close()
            self._login_window = None
            self._login_browser = None

        QMessageBox.critical(self, "登录失败", error_msg)
        self._login_status.setText("🔒 未登录 — 请登录账号")
        self._login_status.setStyleSheet("color: #f38ba8;")

    def _import_cookies(self):
        """Import cookies from a file (Netscape format)."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Cookies 文件（Netscape 格式 .txt）",
            "",
            "Cookies 文件 (*.txt);;所有文件 (*)",
        )
        if not path:
            return

        # Simple import: copy file to standard location
        try:
            import shutil
            shutil.copy2(path, self._auth.cookies_path)
            QMessageBox.information(self, "导入成功", "Cookies 文件已导入！")
            self._login_status.setText("⏳ 正在验证登录...")
            self._login_status.setStyleSheet("color: #f9e2af;")
            self._auto_login()
        except Exception as e:
            QMessageBox.critical(
                self,
                "导入失败",
                f"无法复制 Cookies 文件：{str(e)}\n\n"
                "💡 推荐使用内嵌浏览器直接登录，或\n"
                "使用浏览器扩展 'Get cookies.txt LOCALLY' 导出。"
            )

    def _logout(self):
        """Clear credentials and reset state."""
        reply = QMessageBox.question(
            self,
            "确认登出",
            "确定要登出吗？将清除本地保存的登录凭据。",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Clear cookies
        self._auth.clear()
        self._ytm = None
        self._songs.clear()
        self._playlists.clear()
        self._song_list.set_songs([])
        self._sidebar.set_playlists([])
        self._login_status.setText("🔒 未登录")
        self._login_status.setStyleSheet("color: #f38ba8;")

    def _export_cookies(self):
        """Export cookies file to user-chosen location (backup)."""
        if not self._auth.has_cookies:
            QMessageBox.information(self, "提示", "尚未登录，没有可导出的 Cookies。")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Cookies 文件",
            "cookies.txt",
            "Cookies 文件 (*.txt);;所有文件 (*)",
        )
        if not path:
            return

        try:
            import shutil
            shutil.copy2(self._auth.cookies_path, path)
            QMessageBox.information(self, "导出成功", f"Cookies 已导出到：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _refresh_library(self):
        """Manually refresh the music library (playlists + liked songs)."""
        if not self._ytm:
            QMessageBox.information(self, "提示", "请先登录 YouTube Music 账号。")
            return
        self._load_library(is_refresh=True)

    # ═══════════════════════════════════════════════════════
    #  Library Loading
    # ═══════════════════════════════════════════════════════

    def _load_library(self, is_refresh: bool = False):
        """Load user's playlists and liked songs."""
        if not self._ytm:
            return

        try:
            prefix = "🔄 刷新中" if is_refresh else "⏳ 加载中"
            self._login_status.setText(f"{prefix}...")
            self._login_status.setStyleSheet("color: #f9e2af;")
            QApplication.processEvents()

            # Load playlists list
            self._playlists = self._ytm.get_playlists()
            self._sidebar.set_playlists(self._playlists)

            # Load liked songs by default (or keep current playlist)
            songs = self._ytm.get_liked_songs()
            self._songs = songs
            self._sidebar.set_liked_count(len(songs))
            self._mark_downloaded_status()
            self._song_list.set_songs(self._songs)
            self._current_playlist_id = None

            self._login_status.setText(
                f"✅ 已登录 — {len(self._playlists)} 个播放列表，{len(songs)} 首喜欢的歌"
            )
            self._login_status.setStyleSheet("color: #a6e3a1;")

        except Exception as e:
            QMessageBox.warning(self, "加载失败", f"无法加载音乐库：\n{str(e)}")
            self._login_status.setText("⚠ 加载失败")
            self._login_status.setStyleSheet("color: #f38ba8;")

    def _mark_downloaded_status(self):
        """Mark songs that have been downloaded before."""
        downloaded_ids = set(self._db.get_downloaded_ids())
        for song in self._songs:
            if song.video_id in downloaded_ids:
                song.status = DownloadStatus.COMPLETED

    # ═══════════════════════════════════════════════════════
    #  Playlist selection
    # ═══════════════════════════════════════════════════════

    @Slot()
    def _on_liked_selected(self):
        """Liked songs selected in sidebar."""
        if not self._ytm:
            return
        self._current_playlist_id = None
        try:
            songs = self._ytm.get_liked_songs()
            self._songs = songs
            self._mark_downloaded_status()
            self._song_list.set_songs(self._songs)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法加载喜欢列表：{str(e)}")

    @Slot(str, str)
    def _on_playlist_selected(self, playlist_id: str, title: str):
        """A playlist was selected in sidebar."""
        if not self._ytm:
            return
        self._current_playlist_id = playlist_id
        try:
            songs = self._ytm.get_playlist_songs(playlist_id)
            self._songs = songs
            self._mark_downloaded_status()
            self._song_list.set_songs(self._songs)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法加载播放列表：{str(e)}")

    # ═══════════════════════════════════════════════════════
    #  Download orchestration
    # ═══════════════════════════════════════════════════════

    @Slot(list)
    def _on_download_clicked(self, songs: list[Song]):
        """Start downloading selected songs."""
        if self._downloading:
            QMessageBox.information(self, "提示", "已有下载任务在进行中。")
            return

        # Ensure output directory exists
        download_dir = self._config.download_dir
        if self._config.create_playlist_folders and self._current_playlist_id:
            # Find playlist name
            for pl in self._playlists:
                if pl.playlist_id == self._current_playlist_id:
                    download_dir = os.path.join(download_dir, _safe_name(pl.title))
                    break

        os.makedirs(download_dir, exist_ok=True)

        # Filter already downloaded
        to_download = []
        for song in songs:
            if song.status != DownloadStatus.COMPLETED:
                song.status = DownloadStatus.PENDING
                to_download.append(song)

        if not to_download:
            QMessageBox.information(self, "提示", "所选歌曲均已下载完成。")
            return

        self._downloading = True
        self._overall_progress.setVisible(True)
        self._overall_progress.setMaximum(len(to_download))
        self._overall_progress.setValue(0)
        self._song_list.set_songs(self._songs)  # refresh display

        # Create downloader (with cookies + proxy for authenticated downloads)
        self._downloader = Downloader(
            download_dir=download_dir,
            audio_quality=self._config.audio_quality,
            filename_template=self._config.filename_template,
            cookies_path=self._auth.cookies_path if self._auth.has_cookies else "",
            proxy_url=self._config.proxy_url,
        )

        # Create queue manager
        self._queue = QueueManager(
            max_workers=self._config.concurrent_downloads,
            max_retries=self._config.max_retries,
            retry_delay=self._config.retry_delay,
        )

        # Run in background thread
        thread = threading.Thread(
            target=self._run_download_queue,
            args=(to_download,),
            daemon=True,
        )
        thread.start()

    def _run_download_queue(self, songs: list[Song]):
        """Background download runner."""
        def download_fn(song: Song) -> bool:
            """Wrapped download with progress callbacks."""
            def on_progress(percent, speed, eta):
                song.progress = percent
                song.speed = speed
                self.progress_updated.emit(song.video_id, percent, speed, eta)

            def on_status(status: DownloadStatus):
                song.status = status
                self.status_updated.emit(song)

            success = self._downloader.download(
                song,
                progress_callback=on_progress,
                status_callback=on_status,
            )
            return success

        def on_complete(song: Song, success: bool):
            """Called when a song finishes."""
            if success:
                # Write metadata
                self._metadata.write(song)
                # Record in database
                self._db.mark_downloaded(
                    video_id=song.video_id,
                    title=song.title,
                    artist=song.artist,
                    album=song.album,
                    duration=song.duration,
                    file_path=song.file_path,
                )
            self.status_updated.emit(song)

        def on_status(song: Song, status: DownloadStatus):
            self.status_updated.emit(song)

        self._queue.start(
            songs,
            download_fn=download_fn,
            on_status=on_status,
            on_complete=on_complete,
        )

        # Completion signal
        self.status_updated.emit(Song(video_id="__done__", title=""))

    # ═══════════════════════════════════════════════════════
    #  Status update slots (called from any thread)
    # ═══════════════════════════════════════════════════════

    @Slot(Song)
    def _on_status_updated(self, song: Song):
        """Handle status update for a single song."""
        if song.video_id == "__done__":
            # Download queue complete
            self._downloading = False
            self._overall_progress.setVisible(False)
            self._speed_label.setText("")
            self._count_label.setText("✅ 下载完成")
            self._song_list.set_songs(self._songs)
            return

        # Update song in list
        for s in self._songs:
            if s.video_id == song.video_id:
                s.status = song.status
                s.error_msg = song.error_msg
                s.file_path = song.file_path
                break

        self._song_list.update_song_status(song)

        # Update overall progress
        completed = sum(
            1 for s in self._songs
            if s.status in (DownloadStatus.COMPLETED, DownloadStatus.SKIPPED)
        )
        total = sum(
            1 for s in self._songs
            if s.status != DownloadStatus.PENDING
        )
        downloading = sum(
            1 for s in self._songs
            if s.status == DownloadStatus.DOWNLOADING
        )

        # actual_total = 所有参与下载的歌曲总数（含已完成、下载中、待下载、失败、暂停）
        actual_total = sum(
            1 for s in self._songs
            if s.status in (DownloadStatus.COMPLETED, DownloadStatus.SKIPPED,
                           DownloadStatus.DOWNLOADING, DownloadStatus.PENDING,
                           DownloadStatus.FAILED, DownloadStatus.PAUSED)
        )
        if actual_total > 0:
            self._overall_progress.setMaximum(actual_total)
            self._overall_progress.setValue(completed)
        self._count_label.setText(f"{completed}/{actual_total}")

    @Slot(str, float, str, str)
    def _on_progress_updated(self, video_id: str, percent: float, speed: str, eta: str):
        """Handle download progress update."""
        self._speed_label.setText(f"⬇ {speed}" if speed else "")
        if eta:
            self._speed_label.setText(f"⬇ {speed}  剩余 {eta}" if speed else f"剩余 {eta}")

    # ═══════════════════════════════════════════════════════
    #  Menu actions
    # ═══════════════════════════════════════════════════════

    def _open_settings(self):
        """Open settings dialog."""
        from .settings_dialog import SettingsDialog
        dialog = SettingsDialog(self._config, self)
        if dialog.exec():
            # Config already updated in-place by dialog
            self._config.save()

    def _open_guide(self):
        """Open the usage guide."""
        import webbrowser
        guide_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "GUIDE.md"
        )
        if os.path.exists(guide_path):
            webbrowser.open(f"file:///{guide_path.replace(os.sep, '/')}")
        else:
            QMessageBox.information(
                self,
                "使用指南",
                "GUIDE.md 文件未找到。\n\n"
                "请参考 README.md 或项目文档获取使用帮助。"
            )

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "关于 YtMusicVault",
            "<h3>YtMusicVault</h3>"
            "<p>YouTube Music 批量下载器</p>"
            "<p>版本 1.0.0</p>"
            "<p>下载您的 YouTube Music 收藏到本地，自动写入封面和元数据。</p>"
            "<hr>"
            "<p>技术栈：PySide6 + yt-dlp + ytmusicapi + mutagen</p>",
        )

    # ═══════════════════════════════════════════════════════
    #  Close event
    # ═══════════════════════════════════════════════════════

    def closeEvent(self, event):
        """Save config on close."""
        self._config.window_width = self.width()
        self._config.window_height = self.height()
        self._config.save()
        self._db.close()
        event.accept()


def _safe_name(name: str) -> str:
    """Make a playlist name safe for folder use."""
    unsafe = '<>:"/\\|?*'
    for ch in unsafe:
        name = name.replace(ch, "_")
    return name.strip()[:100]
