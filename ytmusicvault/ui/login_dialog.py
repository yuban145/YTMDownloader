"""Login dialog — provides embedded browser login and cookies import."""

import webbrowser

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFileDialog, QMessageBox, QTextEdit, QScrollArea,
    QWidget,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from ..core.auth import AuthManager
from ..ui.login_browser import LoginBrowserWidget
from ..ui.styles import DARK_THEME


# ── Cookie format help text ──────────────────────────────────
COOKIE_HELP_TEXT = """<h3>📋 Cookies 文件格式说明</h3>

<p>支持 <b>Netscape HTTP Cookies</b> 格式（TAB 分隔），文件内容示例：</p>

<pre style="background:#181825;color:#cdd6f4;padding:10px;border-radius:6px;font-size:12px;">
# Netscape HTTP Cookie File
# https://curl.se/docs/http-cookies.html
.youtube.com	TRUE	/	TRUE	1798765432	CONSENT	YES+
.youtube.com	TRUE	/	FALSE	1798765432	VISITOR_INFO1_LIVE	abc123
.youtube.com	TRUE	/	FALSE	1798765432	LOGIN_INFO	xxxxxxxx
.youtube.com	TRUE	/	FALSE	1798765432	SID	xxxxxxxx
.google.com	TRUE	/	TRUE	1798765432	__Secure-3PSID	xxxxxxxx
</pre>

<p><b>每行 7 个字段</b>（TAB 分隔）：</p>
<ol>
  <li><b>domain</b> — 域名（如 .youtube.com）</li>
  <li><b>flag</b> — TRUE/FALSE（是否所有主机匹配）</li>
  <li><b>path</b> — 路径（通常是 /）</li>
  <li><b>secure</b> — TRUE/FALSE（是否仅 HTTPS）</li>
  <li><b>expiration</b> — 过期时间（UNIX 时间戳）</li>
  <li><b>name</b> — Cookie 名称</li>
  <li><b>value</b> — Cookie 值</li>
</ol>

<hr>

<h3>🔧 如何获取 Cookies 文件？</h3>

<p><b>方法 A：浏览器扩展（推荐 ⭐）</b></p>
<ol>
  <li>Chrome / Edge：安装扩展 <b>"Get cookies.txt LOCALLY"</b></li>
  <li>Firefox：安装扩展 <b>"cookies.txt"</b></li>
  <li>打开 <a href="https://music.youtube.com">music.youtube.com</a> 并登录</li>
  <li>点击扩展图标 → <b>Export</b>（导出为 cookies.txt）</li>
  <li>导入此文件即可</li>
</ol>

<p><b>方法 B：开发者工具手动导出</b></p>
<ol>
  <li>打开 music.youtube.com 并登录</li>
  <li>按 <b>F12</b> → <b>Application</b>（应用程序）→ <b>Cookies</b></li>
  <li>选择 <b>https://music.youtube.com</b></li>
  <li>将以下关键 Cookie 的值记录下来：<br>
  <code>CONSENT</code>, <code>VISITOR_INFO1_LIVE</code>, <code>LOGIN_INFO</code>, <code>SID</code>, <code>HSID</code>, <code>SSID</code>, <code>APISID</code>, <code>SAPISID</code>, <code>__Secure-3PAPISID</code>, <code>__Secure-3PSID</code></li>
  <li>按上面的 Netscape 格式写入 txt 文件</li>
</ol>

<p style="color:#f9e2af;"><b>⚠ 注意：</b>Cookies 包含敏感信息，请勿分享给他人！</p>"""


# ═══════════════════════════════════════════════════════════════
#  Login Dialog
# ═══════════════════════════════════════════════════════════════

class LoginDialog(QDialog):
    """Dialog for logging into YouTube Music."""

    login_done = Signal()  # emitted when login succeeds

    def __init__(self, auth: AuthManager, parent=None):
        super().__init__(parent)
        self._auth = auth
        self._result = False
        self.setWindowTitle("登录 YouTube Music")
        self.setMinimumWidth(560)
        self.setMinimumHeight(420)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # Title
        title = QLabel("🔐  登录 YouTube Music")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "下载个人音乐库需要登录 YouTube Music 账号。\n"
            "应用不会保存您的密码，仅存储登录凭据。"
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #a6adc8;")
        layout.addWidget(subtitle)

        # ── OAuth section ─────────────────────────────
        oauth_group = QGroupBox("方法 1：内嵌浏览器登录（推荐 ⭐）")
        oauth_layout = QVBoxLayout(oauth_group)
        oauth_desc = QLabel(
            "在应用内直接打开 YouTube Music 网页，\n"
            "登录你的 Google 账号后自动提取 Cookies。\n"
            "无需外部浏览器，无需手动操作 Cookies。"
        )
        oauth_desc.setStyleSheet("color: #a6adc8;")
        oauth_desc.setWordWrap(True)
        oauth_layout.addWidget(oauth_desc)

        oauth_btn_layout = QHBoxLayout()
        self._oauth_btn = QPushButton("🔐  内嵌浏览器登录")
        self._oauth_btn.setMinimumHeight(36)
        self._oauth_btn.clicked.connect(self._do_login_browser)
        oauth_btn_layout.addWidget(self._oauth_btn)
        oauth_layout.addLayout(oauth_btn_layout)

        self._oauth_status = QLabel("")
        self._oauth_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._oauth_status.setWordWrap(True)
        oauth_layout.addWidget(self._oauth_status)

        layout.addWidget(oauth_group)

        # ── Cookies section ───────────────────────────
        cookie_group = QGroupBox("方法 2：导入 Cookies 文件")
        cookie_layout = QVBoxLayout(cookie_group)

        cookie_desc = QLabel(
            "如果你已有从浏览器导出的 Cookies 文件，可直接导入。\n"
            "支持 Netscape 格式（如 Get cookies.txt 扩展导出）。"
        )
        cookie_desc.setStyleSheet("color: #a6adc8;")
        cookie_desc.setWordWrap(True)
        cookie_layout.addWidget(cookie_desc)

        # Help button
        self._cookie_help_btn = QPushButton("📖  什么是 Cookies 文件？如何获取？")
        self._cookie_help_btn.setObjectName("secondaryBtn")
        self._cookie_help_btn.clicked.connect(self._show_cookie_help)
        cookie_layout.addWidget(self._cookie_help_btn)

        # Import button
        self._cookie_btn = QPushButton("📂  选择并导入 Cookies 文件")
        self._cookie_btn.setObjectName("secondaryBtn")
        self._cookie_btn.setMinimumHeight(36)
        self._cookie_btn.clicked.connect(self._do_import_cookies)
        cookie_layout.addWidget(self._cookie_btn)

        layout.addWidget(cookie_group)

        # ── Status ────────────────────────────────────
        if self._auth.has_cookies:
            status = QLabel("✅ 已有 Cookies 登录凭据，可直接使用")
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status.setStyleSheet("color: #a6e3a1;")
            layout.addWidget(status)

        # ── Close button ──────────────────────────────
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondaryBtn")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    # ── Embedded browser login ──────────────────────────

    def _do_login_browser(self):
        """Open embedded browser for manual login on music.youtube.com."""
        self._oauth_btn.setEnabled(False)
        self._oauth_status.setText("⏳ 正在打开 YouTube Music...")
        self._oauth_status.setStyleSheet("color: #f9e2af; padding: 8px;")

        self._login_window = QWidget()
        self._login_window.setWindowTitle("YtMusicVault — 登录 YouTube Music")
        self._login_window.resize(800, 650)
        self._login_window.setMinimumSize(700, 500)

        layout = QVBoxLayout(self._login_window)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._login_browser = LoginBrowserWidget(self._auth.cookies_path)
        self._login_browser.login_success.connect(self._on_browser_success)
        self._login_browser.login_failed.connect(self._on_browser_failed)

        layout.addWidget(self._login_browser)
        self._login_window.setStyleSheet(DARK_THEME)
        self._login_window.show()

        self._oauth_status.setText("⏳ 请在弹窗中登录你的 Google 账号...")
        self._oauth_status.setStyleSheet("color: #f9e2af; padding: 8px;")

    def _on_browser_success(self):
        """Login browser succeeded — cookies saved."""
        if hasattr(self, '_login_window') and self._login_window:
            self._login_window.close()

        self._oauth_status.setText("✅ 登录成功！")
        self._oauth_status.setStyleSheet("color: #a6e3a1; padding: 8px;")
        self._result = True
        self._oauth_btn.setEnabled(True)
        self.login_done.emit()

    def _on_browser_failed(self, error_msg: str):
        """Login browser failed."""
        if hasattr(self, '_login_window') and self._login_window:
            self._login_window.close()

        self._oauth_status.setText(f"❌ {error_msg}")
        self._oauth_status.setStyleSheet("color: #f38ba8; padding: 8px;")
        self._oauth_btn.setEnabled(True)

    # ── Cookies ───────────────────────────────────────────

    def _do_import_cookies(self):
        """Import cookies from file — simple copy to standard location."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Cookies 文件（Netscape 格式 .txt）",
            "",
            "Cookies 文件 (*.txt);;所有文件 (*.*)",
        )
        if not path:
            return

        try:
            import shutil
            shutil.copy2(path, self._auth.cookies_path)
            QMessageBox.information(self, "导入成功", "Cookies 文件已导入！")
            self._result = True
            self.login_done.emit()
        except Exception as e:
            QMessageBox.critical(
                self,
                "导入失败",
                f"无法复制 Cookies 文件：{str(e)}\n\n"
                "💡 推荐使用内嵌浏览器直接登录，更方便！"
            )

    def _show_cookie_help(self):
        """Show a detailed help dialog about cookies format."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Cookies 文件格式帮助")
        dialog.setMinimumWidth(620)
        dialog.setMinimumHeight(550)

        layout = QVBoxLayout(dialog)

        # Scrollable help text
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        help_widget = QLabel(COOKIE_HELP_TEXT)
        help_widget.setWordWrap(True)
        help_widget.setTextFormat(Qt.TextFormat.RichText)
        help_widget.setOpenExternalLinks(True)
        help_widget.setStyleSheet("padding: 12px;")
        scroll.setWidget(help_widget)
        layout.addWidget(scroll)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        ext_btn = QPushButton("🔗 打开扩展商店页面")
        ext_btn.setObjectName("secondaryBtn")
        ext_btn.clicked.connect(
            lambda: webbrowser.open(
                "https://chromewebstore.google.com/detail/"
                "get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"
            )
        )
        btn_layout.addWidget(ext_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        dialog.exec()

    @property
    def login_successful(self) -> bool:
        return self._result
