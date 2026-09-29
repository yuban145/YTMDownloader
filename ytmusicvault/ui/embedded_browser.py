"""Optional in-app Chromium session for collecting fresh YouTube cookies.

The browser does not solve yt-dlp's player-script challenge; the extracted
cookies are passed to the existing yt-dlp/EJS download path.
"""
from PySide6.QtCore import QUrl, Signal
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout

from ..core.auth import LoginRequest


def youtube_cookie_line(cookie):
    """Convert a Qt cookie to a Netscape line without logging its value."""
    domain = cookie.domain().strip()
    host = domain.lstrip(".").lower()
    if host != "youtube.com" and not host.endswith(".youtube.com"):
        return None
    name = bytes(cookie.name()).decode("utf-8", errors="replace")
    value = bytes(cookie.value()).decode("utf-8", errors="replace")
    if not name or not value or any(c in name + value for c in "\r\n\t\x00"):
        return None
    subdomains = domain.startswith(".")
    expiration = 0 if cookie.isSessionCookie() else cookie.expirationDate().toSecsSinceEpoch()
    prefix = "#HttpOnly_" if cookie.isHttpOnly() else ""
    return "\t".join((prefix + domain, "TRUE" if subdomains else "FALSE",
                      cookie.path() or "/", "TRUE" if cookie.isSecure() else "FALSE",
                      str(expiration), name, value))


class _BrowserView(QWebEngineView):
    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self._popups = []

    def createWindow(self, kind):
        # Google sign-in and YouTube may use a popup. Keep it in the same
        # off-the-record profile so its cookies are visible to this session.
        dialog = QDialog(self)
        dialog.setWindowTitle("浏览器登录")
        dialog.resize(700, 650)
        layout = QVBoxLayout(dialog)
        view = _BrowserView(self.page().profile(), dialog)
        layout.addWidget(view)
        dialog.finished.connect(lambda *_: self._popups.remove(dialog) if dialog in self._popups else None)
        self._popups.append(dialog)
        dialog.show()
        return view


class EmbeddedBrowserDialog(QDialog):
    submitted = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("内置浏览器 · YouTube Music")
        self.resize(1050, 800)
        # Unnamed profile keeps web content and cookies in memory only.
        self._profile = QWebEngineProfile(self)
        self._cookies = {}
        store = self._profile.cookieStore()
        store.cookieAdded.connect(self._cookie_added)
        store.cookieRemoved.connect(self._cookie_removed)
        layout = QVBoxLayout(self)
        note = QLabel("在下方浏览器登录后，点击“使用当前 Cookie”。浏览器会话仅保存在内存中；"
                      "yt-dlp 仍会自行处理 YouTube 播放器脚本。若 Google 拒绝内嵌登录，请使用 Cookie 文件或外部浏览器。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self._view = _BrowserView(self._profile, self)
        layout.addWidget(self._view, 1)
        row = QHBoxLayout()
        refresh = QPushButton("刷新页面")
        refresh.clicked.connect(self._view.reload)
        row.addWidget(refresh)
        row.addWidget(QLabel("账号序号"))
        self._account = QSpinBox()
        self._account.setRange(0, 99)
        row.addWidget(self._account)
        row.addStretch()
        submit = QPushButton("使用当前 Cookie")
        submit.clicked.connect(self._submit)
        row.addWidget(submit)
        layout.addLayout(row)
        self._message = QLabel("")
        layout.addWidget(self._message)
        store.loadAllCookies()
        self._view.setUrl(QUrl("https://music.youtube.com"))

    @staticmethod
    def _key(cookie):
        return cookie.domain(), cookie.path(), bytes(cookie.name())

    def _cookie_added(self, cookie):
        if youtube_cookie_line(cookie):
            self._cookies[self._key(cookie)] = QNetworkCookie(cookie)

    def _cookie_removed(self, cookie):
        self._cookies.pop(self._key(cookie), None)

    def _submit(self):
        lines = [youtube_cookie_line(cookie) for cookie in self._cookies.values()]
        lines = [line for line in lines if line]
        if not any(line.split("\t")[-2] == "__Secure-3PAPISID" for line in lines):
            self._message.setText("尚未获取到 YouTube 登录 Cookie。请完成登录，或改用 Cookie 文件。")
            return
        self.submitted.emit(LoginRequest("embedded", "# Netscape HTTP Cookie File\n" +
                                         "\n".join(lines) + "\n",
                                         account_index=str(self._account.value())))
        self.accept()
