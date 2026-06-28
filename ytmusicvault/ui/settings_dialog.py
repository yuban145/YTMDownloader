"""设置对话框 — 配置下载选项、文件命名、代理等偏好。

用户可配置项：
  - 下载目录（带浏览按钮）
  - 音质（best/256kbps/128kbps）
  - 并发下载数（1-8）
  - 失败重试次数（0-10）
  - 重试间隔（1-60 秒）
  - 文件名模板（{artist}, {title}, {album}, {track}, {ext}）
  - 按播放列表创建子文件夹

数据流：
  MainWindow._open_settings() → SettingsDialog(config) → 修改 config → config.save()
  对话框关闭时 config 已直接修改（非临时副本），调用方只需 save()。
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QSpinBox, QComboBox, QPushButton,
    QFileDialog, QCheckBox, QDialogButtonBox, QMessageBox,
)
from PySide6.QtCore import Qt

from ..utils.config import AppConfig


class SettingsDialog(QDialog):
    """Application settings dialog."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("偏好设置")
        self.setMinimumWidth(520)
        self._setup_ui()
        self._load_config()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Download settings ──────────────────────────
        dl_group = QGroupBox("下载设置")
        dl_form = QFormLayout(dl_group)

        # Download directory
        dir_layout = QHBoxLayout()
        self._dir_input = QLineEdit()
        self._dir_input.setPlaceholderText("~/Music/YtMusicVault/")
        dir_layout.addWidget(self._dir_input)
        browse_btn = QPushButton("浏览...")
        browse_btn.setObjectName("secondaryBtn")
        browse_btn.clicked.connect(self._browse_dir)
        dir_layout.addWidget(browse_btn)
        dl_form.addRow("下载目录：", dir_layout)

        # Audio quality
        self._quality_combo = QComboBox()
        self._quality_combo.addItems([
            "最佳质量 (best)",
            "256 kbps",
            "128 kbps",
        ])
        dl_form.addRow("音质：", self._quality_combo)

        # Concurrent downloads
        self._concurrency_spin = QSpinBox()
        self._concurrency_spin.setRange(1, 8)
        self._concurrency_spin.setValue(4)
        self._concurrency_spin.setSuffix(" 个同时下载")
        dl_form.addRow("并发数：", self._concurrency_spin)

        # Max retries
        self._retry_spin = QSpinBox()
        self._retry_spin.setRange(0, 10)
        self._retry_spin.setValue(3)
        self._retry_spin.setSuffix(" 次")
        dl_form.addRow("失败重试：", self._retry_spin)

        # Retry delay
        self._delay_spin = QSpinBox()
        self._delay_spin.setRange(1, 60)
        self._delay_spin.setValue(5)
        self._delay_spin.setSuffix(" 秒")
        dl_form.addRow("重试间隔：", self._delay_spin)

        layout.addWidget(dl_group)

        # ── Proxy settings ────────────────────────────
        proxy_group = QGroupBox("代理设置（中国大陆用户必看）")
        proxy_form = QFormLayout(proxy_group)

        self._proxy_enabled_cb = QCheckBox("启用代理")
        proxy_form.addRow("", self._proxy_enabled_cb)

        self._proxy_type_combo = QComboBox()
        self._proxy_type_combo.addItems(["http", "socks5"])
        proxy_form.addRow("代理类型：", self._proxy_type_combo)

        self._proxy_host_input = QLineEdit()
        self._proxy_host_input.setPlaceholderText("127.0.0.1")
        proxy_form.addRow("主机地址：", self._proxy_host_input)

        self._proxy_port_spin = QSpinBox()
        self._proxy_port_spin.setRange(1, 65535)
        self._proxy_port_spin.setValue(1080)
        proxy_form.addRow("端口：", self._proxy_port_spin)

        self._proxy_user_input = QLineEdit()
        self._proxy_user_input.setPlaceholderText("（选填）")
        proxy_form.addRow("用户名：", self._proxy_user_input)

        self._proxy_pass_input = QLineEdit()
        self._proxy_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._proxy_pass_input.setPlaceholderText("（选填）")
        proxy_form.addRow("密码：", self._proxy_pass_input)

        proxy_form.addRow(
            "",
            QLabel(
                "💡 代理用于访问被屏蔽的 YouTube 服务。\n"
                "常用代理：Clash (127.0.0.1:7890) / V2Ray (127.0.0.1:1080)"
            ),
        )

        layout.addWidget(proxy_group)

        # ── File naming ────────────────────────────────
        file_group = QGroupBox("文件命名")
        file_form = QFormLayout(file_group)

        self._template_input = QLineEdit()
        self._template_input.setPlaceholderText("{artist} - {title}.{ext}")
        file_form.addRow("文件名模板：", self._template_input)
        file_form.addRow(
            "",
            QLabel(
                "可用变量：{artist}, {title}, {album}, {track}, {ext}\n"
                "示例：{artist} - {title}.{ext}  →  周杰伦 - 七里香.m4a"
            ),
        )

        self._folder_cb = QCheckBox("按播放列表自动创建子文件夹")
        file_form.addRow("", self._folder_cb)

        layout.addWidget(file_group)

        # ── Buttons ────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_config(self):
        """Populate fields from current config."""
        self._dir_input.setText(self._config.download_dir)

        quality_map = {"best": 0, "256": 1, "128": 2}
        self._quality_combo.setCurrentIndex(
            quality_map.get(self._config.audio_quality, 0)
        )

        self._concurrency_spin.setValue(self._config.concurrent_downloads)
        self._retry_spin.setValue(self._config.max_retries)
        self._delay_spin.setValue(self._config.retry_delay)
        self._template_input.setText(self._config.filename_template)
        self._folder_cb.setChecked(self._config.create_playlist_folders)

        # Proxy
        self._proxy_enabled_cb.setChecked(self._config.proxy_enabled)
        self._proxy_type_combo.setCurrentText(self._config.proxy_type)
        self._proxy_host_input.setText(self._config.proxy_host)
        self._proxy_port_spin.setValue(self._config.proxy_port)
        self._proxy_user_input.setText(self._config.proxy_username)
        self._proxy_pass_input.setText(self._config.proxy_password)

    def _on_save(self):
        """Save settings to config."""
        self._config.download_dir = self._dir_input.text()

        quality_map = {0: "best", 1: "256", 2: "128"}
        self._config.audio_quality = quality_map.get(
            self._quality_combo.currentIndex(), "best"
        )

        self._config.concurrent_downloads = self._concurrency_spin.value()
        self._config.max_retries = self._retry_spin.value()
        self._config.retry_delay = self._delay_spin.value()
        self._config.filename_template = self._template_input.text()
        self._config.create_playlist_folders = self._folder_cb.isChecked()

        # Proxy
        self._config.proxy_enabled = self._proxy_enabled_cb.isChecked()
        self._config.proxy_type = self._proxy_type_combo.currentText()
        self._config.proxy_host = self._proxy_host_input.text()
        self._config.proxy_port = self._proxy_port_spin.value()
        self._config.proxy_username = self._proxy_user_input.text()
        self._config.proxy_password = self._proxy_pass_input.text()

        self.accept()

    def _browse_dir(self):
        """Browse for download directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择下载目录",
            self._dir_input.text(),
        )
        if directory:
            self._dir_input.setText(directory)
