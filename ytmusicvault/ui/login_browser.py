"""Login browser — embedded web view for manual YouTube Music login.
User logs in on music.youtube.com, then we extract cookies as Netscape format.
No OAuth / Google API calls needed. Works behind firewalls.
"""

import hashlib
import json
import time
import os
from datetime import datetime, timezone

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar,
)
from PySide6.QtCore import Qt, QUrl, Signal, QTimer, QDateTime
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtNetwork import QNetworkCookie


class LoginBrowserWidget(QWidget):
    """Embedded browser that lets user log into YouTube Music manually,
    then extracts cookies for use with ytmusicapi and yt-dlp."""

    login_success = Signal()      # cookies saved successfully
    login_failed = Signal(str)    # error message

    YT_MUSIC_URL = "https://music.youtube.com"

    def __init__(self, cookies_path: str, parent=None):
        super().__init__(parent)
        self._cookies_path = cookies_path
        # headers.json for ytmusicapi (in same dir as cookies.txt)
        self._headers_path = os.path.join(
            os.path.dirname(cookies_path), "headers.json"
        )
        self._saw_google = False
        self._logged_in = False
        self._cookies: dict[tuple[str, str], QNetworkCookie] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Top bar ──────────────────────────────────
        bar = QWidget()
        bar.setStyleSheet("background-color: #181825; padding: 10px 12px;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 8, 12, 8)
        bar_layout.setSpacing(12)

        self._status_label = QLabel(
            "请在下方浏览器中登录你的 Google 账号，\n"
            "登录成功后点击右侧「✅ 完成登录」按钮。"
        )
        self._status_label.setStyleSheet("color: #a600c8; font-size: 12px;")
        self._status_label.setWordWrap(True)
        bar_layout.addWidget(self._status_label, 1)

        self._done_btn = QPushButton("✅ 完成登录")
        self._done_btn.setMinimumHeight(32)
        self._done_btn.clicked.connect(self._on_done)
        self._done_btn.setEnabled(False)
        bar_layout.addWidget(self._done_btn)

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setObjectName("dangerBtn")
        self._cancel_btn.setMinimumHeight(32)
        self._cancel_btn.clicked.connect(lambda: self.login_failed.emit("用户取消"))
        bar_layout.addWidget(self._cancel_btn)

        layout.addWidget(bar)

        # ── Progress ─────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setMaximumHeight(3)
        self._progress.setTextVisible(False)
        self._progress.setMaximum(0)  # indeterminate
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # ── Web view + cookie capture ────────────────
        profile = QWebEngineProfile.defaultProfile()
        # Use in-memory cookies for this session
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )

        # ★ KEY FIX: connect cookieAdded BEFORE any navigation
        #    so we capture every cookie as it's set during login
        cookie_store = profile.cookieStore()
        cookie_store.deleteAllCookies()
        cookie_store.cookieAdded.connect(self._on_cookie_added)

        self._webview = QWebEngineView()
        self._webview.urlChanged.connect(self._on_url_changed)
        self._webview.loadFinished.connect(self._on_load_finished)
        layout.addWidget(self._webview, 1)

        # Navigate to YT Music
        self._webview.load(QUrl(self.YT_MUSIC_URL))

    # ═══════════════════════════════════════════════════════
    #  Cookie capture (connected BEFORE navigation!)
    # ═══════════════════════════════════════════════════════

    # Only these cookies indicate actual Google login — NOT consent/analytics cookies
    _AUTH_COOKIE_NAMES = frozenset({
        "LOGIN_INFO",           # YouTube auth token
        "SID", "HSID", "SSID",  # Google session IDs
        "APISID", "SAPISID",    # Google API session
        "__Secure-3PSID", "__Secure-3PAPISID",  # Google account
    })

    def _on_cookie_added(self, cookie: QNetworkCookie):
        """Capture every cookie as it's set during browsing."""
        key = (cookie.domain(), bytes(cookie.name()).decode("utf-8", errors="replace"))
        self._cookies[key] = QNetworkCookie(cookie)  # store a copy

        # Only enable "done" button if we see REAL auth cookies
        # (not NID, _gcl_au, CONSENT, VISITOR_INFO1_LIVE etc. which appear just by visiting)
        name_str = bytes(cookie.name()).decode("utf-8", errors="replace")
        if (
            not self._logged_in
            and name_str in self._AUTH_COOKIE_NAMES
        ):
            self._logged_in = True
            self._done_btn.setEnabled(True)
            self._status_label.setText("✅ 检测到已有登录状态，请等待")
            self._status_label.setStyleSheet("color: #a6e3a1; font-size: 12px;")

    # ═══════════════════════════════════════════════════════
    #  Events
    # ═══════════════════════════════════════════════════════

    def _on_url_changed(self, url: QUrl):
        url_str = url.toString()
        if "accounts.google.com" in url_str:
            self._saw_google = True
            self._status_label.setText("⏳ 正在跳转 Google 登录...请完成验证")
            self._status_label.setStyleSheet("color: #f9e2af; font-size: 12px;")
        elif (
            self._saw_google                              # ← MUST have visited Google first
            and "music.youtube.com" in url_str
            and self._webview.url().host() == "music.youtube.com"
            and "accounts.google.com" not in url_str
        ):
            self._logged_in = True
            self._done_btn.setEnabled(True)
            self._status_label.setText("✅ 登录成功！请点击右侧「完成登录」按钮")
            self._status_label.setStyleSheet("color: #a6e3a1; font-size: 12px;")

    def _on_load_finished(self, ok: bool):
        if not ok:
            self._status_label.setText("⚠️ 页面加载失败，请检查网络连接")
            self._status_label.setStyleSheet("color: #f38ba8; font-size: 12px;")

    # ═══════════════════════════════════════════════════════
    #  Save
    # ═══════════════════════════════════════════════════════

    def _on_done(self):
        """User clicked done — save collected cookies directly."""
        self._done_btn.setEnabled(False)
        self._done_btn.setText("⏳ 保存中...")
        self._progress.setVisible(True)
        self._status_label.setText("正在保存 Cookies...")
        self._status_label.setStyleSheet("color: #f9e2af; font-size: 12px;")

        # Cookies were collected in real-time via cookieAdded signal.
        # Small delay to let any in-flight cookies settle, then save.
        QTimer.singleShot(500, self._do_save)

    def _do_save(self):
        """Write cookies as Netscape (for yt-dlp) AND headers.json (for ytmusicapi)."""
        cookies = list(self._cookies.values())

        if not cookies:
            self.login_failed.emit(
                "未能提取到任何 Cookie。\n\n"
                "请确认已在浏览器中成功登录 Google 账号。"
            )
            return

        # Verify we have at least one AUTH cookie
        auth_found = [
            bytes(c.name()).decode("utf-8", errors="replace")
            for c in cookies
            if bytes(c.name()).decode("utf-8", errors="replace") in self._AUTH_COOKIE_NAMES
        ]
        if not auth_found:
            self.login_failed.emit(
                "未检测到 Google 登录凭据。\n\n"
                f"收集到 {len(cookies)} 个 Cookie，"
                "但没有认证相关的 Cookie。\n"
                "请在下方浏览器中完成 Google 账号登录后重试。"
            )
            return

        try:
            # 1. Save Netscape cookies.txt (for yt-dlp)
            os.makedirs(os.path.dirname(self._cookies_path), exist_ok=True)
            with open(self._cookies_path, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write("# Generated by YtMusicVault\n")
                f.write("#\n")
                for cookie in cookies:
                    line = _cookie_to_netscape(cookie)
                    if line:
                        f.write(line + "\n")

            # 2. Build Cookie header string
            cookie_pairs = []
            for cookie in cookies:
                name = bytes(cookie.name()).decode("utf-8", errors="replace")
                value = bytes(cookie.value()).decode("utf-8", errors="replace")
                cookie_pairs.append(f"{name}={value}")
            cookie_header = "; ".join(cookie_pairs)

            # 3. Extract __Secure-3PAPISID for SAPISIDHASH
            sapisid = ""
            for cookie in cookies:
                name = bytes(cookie.name()).decode("utf-8", errors="replace")
                if name == "__Secure-3PAPISID":
                    sapisid = bytes(cookie.value()).decode("utf-8", errors="replace")
                    break

            # 4. Generate SAPISIDHASH authorization header
            if sapisid:
                ts = str(int(time.time()))
                sapisidhash = hashlib.sha1(
                    (ts + " " + sapisid).encode("utf-8")
                ).hexdigest()
                authorization = f"SAPISIDHASH {ts}_{sapisidhash}"
            else:
                authorization = "SAPISIDHASH 0_placeholder"

            # 5. Save headers.json (for ytmusicapi)
            headers = {
                "cookie": cookie_header,
                "authorization": authorization,
                "x-goog-authuser": "0",
                "x-origin": "https://music.youtube.com",
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "accept": "*/*",
                "content-type": "application/json",
            }
            with open(self._headers_path, "w", encoding="utf-8") as f:
                json.dump(headers, f, indent=2)

            self._status_label.setText(
                f"✅ 已保存 {len(cookies)} 个 Cookie！\n"
                f"yt-dlp 用 cookies.txt / ytmusicapi 用 headers.json"
            )
            self._status_label.setStyleSheet("color: #a6e3a1; font-size: 12px;")
            self._progress.setVisible(False)
            self.login_success.emit()

        except Exception as e:
            self.login_failed.emit(f"保存失败：{str(e)}")


def _cookie_to_netscape(cookie: QNetworkCookie) -> str:
    """Convert a QNetworkCookie to Netscape cookies.txt format line.
    
    Netscape format (TAB-separated):
        domain  flag  path  secure  expires  name  value
    """
    try:
        domain = cookie.domain()
        path = cookie.path()
        if not path:
            path = "/"
        name = bytes(cookie.name()).decode("utf-8", errors="replace")
        value = bytes(cookie.value()).decode("utf-8", errors="replace")

        # Flag: TRUE if domain starts with dot
        flag = "TRUE" if domain.startswith(".") else "FALSE"

        # Secure
        secure = "TRUE" if cookie.isSecure() else "FALSE"

        # Expiration: Unix timestamp
        expiry = cookie.expirationDate()
        if expiry.isValid() and expiry > QDateTime.currentDateTime():
            # Qt QDateTime → Python datetime → Unix timestamp
            py_dt = expiry.toPython()
            # Ensure timezone-aware
            if py_dt.tzinfo is None:
                py_dt = py_dt.replace(tzinfo=timezone.utc)
            expires = str(int(py_dt.timestamp()))
        else:
            # Session cookie or expired → use far future
            expires = "2147483647"

        return f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}"
    except Exception:
        return ""

