"""Download and network preferences; localhost:7890 is the first-run default."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QWidget,
    QScrollArea, QLabel, QLineEdit, QSpinBox, QComboBox, QPushButton, QFileDialog,
    QCheckBox, QDialogButtonBox, QMessageBox)
from ..utils.proxy import proxy_description


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("下载与代理设置")
        self.resize(620, 660)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        scroll.setWidget(body)
        layout.addWidget(scroll)

        self._dir_input = QLineEdit(config.download_dir)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse_dir)
        row = QHBoxLayout()
        row.addWidget(self._dir_input)
        row.addWidget(browse)
        form.addRow("下载目录", row)
        info = QLabel("主窗口可选择最高画质 MV，或单独下载 FLAC / MP3 音频。\n"
                      "MV 使用 MKV 无损合并；FLAC 只是无损封装，不能恢复 YouTube 源音频中已损失的音质。")
        info.setWordWrap(True)
        form.addRow(info)
        self._quality_combo = QComboBox()
        for label, value in (("最佳可用音质", "best"), ("MP3 转码 256 kbps", "256"), ("MP3 转码 128 kbps", "128")):
            self._quality_combo.addItem(label, value)
        self._quality_combo.setCurrentIndex(max(0, self._quality_combo.findData(config.audio_quality)))
        form.addRow("MP3 音质", self._quality_combo)
        note = QLabel("FLAC 使用最佳可用源音频；MP3 可在主窗口选择此处的码率。转码不能提升源音质。")
        note.setWordWrap(True)
        form.addRow(note)
        self._concurrency_spin = QSpinBox()
        self._concurrency_spin.setRange(1, 8)
        self._concurrency_spin.setValue(config.concurrent_downloads)
        form.addRow("并发下载数", self._concurrency_spin)
        self._retry_spin = QSpinBox()
        self._retry_spin.setRange(0, 10)
        self._retry_spin.setValue(config.max_retries)
        form.addRow("失败重试次数", self._retry_spin)
        self._delay_spin = QSpinBox()
        self._delay_spin.setRange(1, 60)
        self._delay_spin.setValue(config.retry_delay)
        form.addRow("重试间隔（秒）", self._delay_spin)

        self._proxy_mode = QComboBox()
        for label, value in (("跟随系统代理", "system"),
                             ("手动代理（默认 127.0.0.1:7890）", "manual"), ("直连", "direct"), ("PAC 自动代理", "pac")):
            self._proxy_mode.addItem(label, value)
        form.addRow("网络连接", self._proxy_mode)
        self._proxy_status = QLabel()
        self._proxy_status.setWordWrap(True)
        form.addRow(self._proxy_status)
        self._proxy_type = QComboBox()
        self._proxy_type.addItems(["http", "socks5", "socks5h"])
        self._proxy_type.setCurrentText(config.proxy_type)
        form.addRow("手动代理协议", self._proxy_type)
        self._host = QLineEdit(config.proxy_host)
        form.addRow("主机", self._host)
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(config.proxy_port)
        form.addRow("端口", self._port)
        self._user = QLineEdit(config.proxy_username)
        form.addRow("用户名（可选）", self._user)
        self._password = QLineEdit(config.proxy_password)
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("密码（可选）", self._password)
        self._pac = QLineEdit(config.proxy_pac_url)
        self._pac.setPlaceholderText("http://127.0.0.1:7890/proxy.pac 或本地 .pac 文件")
        self._pac_browse = QPushButton("选择 PAC 文件…")
        self._pac_browse.clicked.connect(self._browse_pac)
        pac_row = QHBoxLayout()
        pac_row.addWidget(self._pac)
        pac_row.addWidget(self._pac_browse)
        form.addRow("PAC 地址 / 文件", pac_row)
        self._manual_fields = [self._proxy_type, self._host, self._port, self._user, self._password]
        self._proxy_mode.currentIndexChanged.connect(self._proxy_changed)
        self._proxy_mode.setCurrentIndex(max(0, self._proxy_mode.findData(config.proxy_mode)))
        self._proxy_changed()
        self._template = QLineEdit(config.filename_template)
        form.addRow("文件名模板", self._template)
        template_note = QLabel("支持 {artist}、{title}、{album}、{track}、{ext}。\n"
                              "自动追加视频 ID，并分开保存到 MV / Audio 文件夹，避免同名覆盖。")
        template_note.setWordWrap(True)
        form.addRow(template_note)
        self._folder = QCheckBox("按歌单建立子目录")
        self._folder.setChecked(config.create_playlist_folders)
        form.addRow(self._folder)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _proxy_changed(self, *_):
        mode = self._proxy_mode.currentData()
        for widget in self._manual_fields:
            widget.setEnabled(mode == "manual")
        self._pac.setEnabled(mode == "pac")
        self._pac_browse.setEnabled(mode == "pac")
        if mode == "pac":
            self._proxy_status.setText("按 PAC 规则连接。支持 HTTP/HTTPS 地址或本地文件；每 5 分钟重新加载。失败时仅按 PAC 中列出的后备路线重试。")
            return
        self._proxy_status.setText(proxy_description(None) if mode == "system" else
                                   ("新建音乐库会话、内置浏览器、MV 查询、媒体下载和封面请求都会使用下面的手动代理。" if mode == "manual" else
                                    "新的音乐库、MV 查询、媒体下载和封面请求将直连。已登录会话需重新登录，内置浏览器需重新打开后应用。"))

    def _on_save(self):
        if not self._dir_input.text().strip():
            QMessageBox.warning(self, "设置无效", "请选择下载目录。")
            return
        if self._proxy_mode.currentData() == "manual" and not self._host.text().strip():
            QMessageBox.warning(self, "设置无效", "请输入代理主机。")
            return
        if self._proxy_mode.currentData() == "pac" and not self._pac.text().strip():
            QMessageBox.warning(self, "设置无效", "请输入 PAC 地址或选择本地文件。")
            return
        c = self._config
        c.download_dir = self._dir_input.text().strip()
        c.audio_quality = self._quality_combo.currentData()
        c.concurrent_downloads = self._concurrency_spin.value()
        c.max_retries, c.retry_delay = self._retry_spin.value(), self._delay_spin.value()
        c.proxy_pac_url = self._pac.text().strip()
        c.proxy_mode = self._proxy_mode.currentData()
        c.proxy_enabled = c.proxy_mode == "manual"  # legacy compatibility
        c.proxy_type, c.proxy_host, c.proxy_port = self._proxy_type.currentText(), self._host.text().strip(), self._port.value()
        c.proxy_username, c.proxy_password = self._user.text(), self._password.text()
        c.filename_template = self._template.text().strip() or "{artist} - {title}.{ext}"
        c.create_playlist_folders = self._folder.isChecked()
        self.accept()

    def _browse_pac(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 PAC 文件", "", "PAC 文件 (*.pac *.dat);;所有文件 (*)")
        if path:
            self._pac.setText(path)

    def _browse_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择下载目录", self._dir_input.text())
        if directory:
            self._dir_input.setText(directory)
