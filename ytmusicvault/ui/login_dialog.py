"""登录对话框 — 支持内嵌浏览器、外部浏览器、请求头和 Cookie 文件登录。

保留现有的 Cookies 导入帮助，补充 incoming branch 的连接/验证流程；
登录成功后仍发出 login_done 信号，同时兼容 submitted 信号以便主窗口统一处理。
"""

import webbrowser

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.auth import AuthManager, BROWSERS, LoginRequest, detect_browsers
from ..ui.login_browser import LoginBrowserWidget
from ..ui.styles import DARK_THEME
from .embedded_browser import EmbeddedBrowserDialog


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

    login_done = Signal()
    submitted = Signal(object)

    def __init__(self, auth: AuthManager | None = None, parent=None):
        super().__init__(parent)
        self._auth = auth
        self._result = False
        self._embedded = None
        self._busy = False
        self.setWindowTitle("登录 YouTube Music")
        self.resize(640, 560)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QLabel("先在常用浏览器登录 YouTube Music，再选择下方方式连接音乐库。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        open_button = QPushButton("打开 YouTube Music")
        open_button.clicked.connect(lambda: webbrowser.open("https://music.youtube.com"))
        layout.addWidget(open_button)

        embedded_button = QPushButton("在内置浏览器登录…")
        embedded_button.clicked.connect(self._open_embedded)
        layout.addWidget(embedded_button)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Browser login tab
        browser_tab = QWidget()
        form = QFormLayout(browser_tab)
        detected = detect_browsers()
        self.browser = QComboBox()
        for name in BROWSERS:
            self.browser.addItem(name.title() + ("（已检测到）" if name in detected else ""), name)
        if detected:
            self.browser.setCurrentIndex(self.browser.findData(detected[0]))
        form.addRow("浏览器", self.browser)

        self.profile = QLineEdit()
        self.profile.setPlaceholderText("可选：Default、Profile 1 或配置目录路径")
        form.addRow("配置文件", self.profile)

        self.account = QSpinBox()
        self.account.setRange(0, 99)
        form.addRow("Google 账号序号", self.account)

        note = QLabel(
            "序号通常为 0。多账号或品牌频道建议使用请求头登录。\n"
            "Chrome / Edge 可能因 Windows 加密保护无法读取，此时请切换到请求头登录。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.tabs.addTab(browser_tab, "浏览器登录")

        # Header login tab
        header_tab = QWidget()
        header_layout = QVBoxLayout(header_tab)
        help_text = QLabel(
            "浏览器按 F12 → 网络 → 打开音乐库 → 找到 /browse POST 请求 → 复制请求头。\n"
            "支持完整请求头文本或请求头 JSON。包含 Cookie 和 X-Goog-AuthUser；"
            "品牌频道请保留 X-Goog-PageId。"
        )
        help_text.setWordWrap(True)
        header_layout.addWidget(help_text)

        self.headers = QPlainTextEdit()
        self.headers.setPlaceholderText("在这里粘贴请求头（不要粘贴整段 fetch 代码）")
        header_layout.addWidget(self.headers)
        self.tabs.addTab(header_tab, "请求头登录")

        # Cookie file tab
        file_tab = QWidget()
        file_layout = QFormLayout(file_tab)
        self.file = QLineEdit()
        browse = QPushButton("选择文件…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.file)
        row.addWidget(browse)
        file_layout.addRow("Netscape cookies.txt", row)

        self.file_account = QSpinBox()
        self.file_account.setRange(0, 99)
        file_layout.addRow("Google 账号序号", self.file_account)
        self.tabs.addTab(file_tab, "Cookie 文件")

        # Current-branch compatibility section
        if self._auth is not None and self._auth.has_cookies:
            status = QLabel("✅ 已有 Cookies 登录凭据，可直接使用")
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status.setStyleSheet("color: #a6e3a1;")
            layout.addWidget(status)

        self._cookie_help_btn = QPushButton("📖  什么是 Cookies 文件？如何获取？")
        self._cookie_help_btn.setObjectName("secondaryBtn")
        self._cookie_help_btn.clicked.connect(self._show_cookie_help)
        layout.addWidget(self._cookie_help_btn)

        self.remember = QCheckBox("记住登录（在本机明文保存 YouTube 会话，退出登录时清除）")
        layout.addWidget(self.remember)

        self.message = QLabel("连接后会加载歌单；请用实际收藏内容确认 Cookie 有效。")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        self.submit = QPushButton("连接音乐库")
        self.submit.clicked.connect(self._submit)
        layout.addWidget(self.submit)

        self._oauth_status = QLabel("")
        self._oauth_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._oauth_status.setWordWrap(True)
        self._oauth_status.setVisible(False)
        layout.addWidget(self._oauth_status)

    # ── Embedded browser login ──────────────────────────

    def _do_login_browser(self):
        """Open embedded browser login and keep the old flow available."""
        if self._auth is None:
            self._open_embedded()
            return

        self._login_window = QWidget()
        self._login_window.setWindowTitle("YtMusicVault — 登录 YouTube Music")
        self._login_window.resize(800, 650)
        self._login_window.setMinimumSize(700, 500)

        login_layout = QVBoxLayout(self._login_window)
        login_layout.setContentsMargins(0, 0, 0, 0)
        login_layout.setSpacing(0)

        self._login_browser = LoginBrowserWidget(self._auth.cookies_path)
        self._login_browser.login_success.connect(self._on_browser_success)
        self._login_browser.login_failed.connect(self._on_browser_failed)
        login_layout.addWidget(self._login_browser)

        self._login_window.setStyleSheet(DARK_THEME)
        self._login_window.show()

        self._oauth_status.setText("⏳ 请在弹窗中登录你的 Google 账号...")
        self._oauth_status.setStyleSheet("color: #f9e2af; padding: 8px;")
        self._oauth_status.setVisible(True)

    def _on_browser_success(self):
        """Login browser succeeded — cookies saved."""
        if hasattr(self, '_login_window') and self._login_window:
            self._login_window.close()

        self._result = True
        self.login_done.emit()
        self.submitted.emit(LoginRequest("browser", "embedded", remember=self.remember.isChecked()))
        self.message.setText("✅ 登录成功！")
        self._oauth_status.setText("✅ 登录成功！")
        self._oauth_status.setStyleSheet("color: #a6e3a1; padding: 8px;")
        self._oauth_status.setVisible(True)

    def _on_browser_failed(self, error_msg: str):
        """Login browser failed."""
        if hasattr(self, '_login_window') and self._login_window:
            self._login_window.close()

        self.message.setText(f"❌ {error_msg}")
        self._oauth_status.setText(f"❌ {error_msg}")
        self._oauth_status.setStyleSheet("color: #f38ba8; padding: 8px;")
        self._oauth_status.setVisible(True)

    # ── Browser/header/file submission ──────────────────────

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Cookie 文件",
            "",
            "Cookies (*.txt);;所有文件 (*)",
        )
        if path:
            self.file.setText(path)

    def _open_embedded(self):
        if self._embedded:
            self._embedded.show()
            self._embedded.raise_()
            return
        self._embedded = EmbeddedBrowserDialog(self)
        self._embedded.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._embedded.submitted.connect(self._submit_embedded)
        self._embedded.finished.connect(lambda *_: setattr(self, "_embedded", None))
        self._embedded.show()

    def _submit_embedded(self, request):
        from dataclasses import replace

        self.submitted.emit(replace(request, remember=self.remember.isChecked()))

    def _submit(self):
        if self._busy:
            return

        index = self.tabs.currentIndex()
        if index == 0:
            request = LoginRequest(
                "browser",
                self.browser.currentData(),
                self.profile.text().strip(),
                str(self.account.value()),
                self.remember.isChecked(),
            )
        elif index == 1:
            request = LoginRequest(
                "headers",
                self.headers.toPlainText(),
                remember=self.remember.isChecked(),
            )
        else:
            path = self.file.text().strip()
            if path and self._auth is not None:
                try:
                    self._auth.import_cookies(path)
                    self._result = True
                    self.login_done.emit()
                    self.message.setText("✅ Cookies 已导入并生成认证 headers，正在验证登录。")
                    self.submitted.emit(
                        LoginRequest(
                            "file",
                            path,
                            account_index=str(self.file_account.value()),
                            remember=self.remember.isChecked(),
                        )
                    )
                    return
                except (ValueError, OSError) as e:
                    QMessageBox.critical(
                        self,
                        "导入失败",
                        f"无法复制 Cookies 文件：{str(e)}\n\n"
                        "💡 推荐使用内嵌浏览器直接登录，更方便！",
                    )
                    return
            request = LoginRequest(
                "file",
                path,
                account_index=str(self.file_account.value()),
                remember=self.remember.isChecked(),
            )

        self.submitted.emit(request)

    # ── Cookies ───────────────────────────────────────────

    def _show_cookie_help(self):
        """Show a detailed help dialog about cookies format."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Cookies 文件格式帮助")
        dialog.setMinimumWidth(620)
        dialog.setMinimumHeight(550)

        layout = QVBoxLayout(dialog)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        help_widget = QLabel(COOKIE_HELP_TEXT)
        help_widget.setWordWrap(True)
        help_widget.setTextFormat(Qt.TextFormat.RichText)
        help_widget.setOpenExternalLinks(True)
        help_widget.setStyleSheet("padding: 12px;")
        scroll.setWidget(help_widget)
        layout.addWidget(scroll)

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

    def set_busy(self, busy):
        self._busy = busy
        self.submit.setEnabled(not busy)
        self.tabs.setEnabled(not busy)
        self.remember.setEnabled(not busy)
        if busy:
            self.message.setText("正在读取会话并连接 YouTube Music…")

    def show_error(self, message):
        self.message.setText(message)

    def reject(self):
        # Closing only hides input UI; the main window still owns verification.
        self.headers.clear()
        super().reject()

    @property
    def login_successful(self) -> bool:
        return self._result

