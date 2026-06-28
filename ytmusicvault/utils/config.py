"""应用配置管理 — JSON 持久化的用户偏好设置。

使用 dataclass 定义配置字段，save()/load() 实现 JSON 序列化/反序列化。
配置存储位置：%APPDATA%/YtMusicVault/config.json（Windows）

设计要点：
  - load() 使用 hasattr + setattr 动态加载 JSON 键值，兼容新增/删除字段
  - 配置损坏（JSONDecodeError）时静默回退到默认值，不阻塞启动
  - proxy_url 属性动态拼接完整代理 URL
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class AppConfig:
    """持久化应用配置。

    所有字段都有默认值，确保首次启动（无 config.json）也能正常运行。
    _config_path 不参与序列化（repr=False），仅用于 save()/load() 定位文件。
    """

    # ── 认证 ────────────────────────────────────────────
    oauth_token: str = ""              # （保留字段，当前使用 Cookies 认证）
    cookies_path: str = ""             # 自定义 cookies.txt 路径

    # ── 下载设置 ────────────────────────────────────────
    download_dir: str = str(Path.home() / "Music" / "YtMusicVault")  # 默认下载目录
    audio_quality: str = "256"         # 音质：128, 256, best
    concurrent_downloads: int = 4      # 最大同时下载数
    max_retries: int = 3               # 失败重试次数
    retry_delay: int = 5               # 重试间隔（秒）

    # ── 代理设置（防火墙后用户） ────────────────────────
    proxy_enabled: bool = False        # 是否启用代理
    proxy_type: str = "http"           # 代理类型：http, socks5
    proxy_host: str = "127.0.0.1"      # 代理主机
    proxy_port: int = 1080             # 代理端口
    proxy_username: str = ""           # 代理用户名（可选）
    proxy_password: str = ""           # 代理密码（可选）

    # ── 文件命名 ────────────────────────────────────────
    filename_template: str = "{artist} - {title}.{ext}"  # yt-dlp 输出模板
    create_playlist_folders: bool = True  # 按播放列表创建子文件夹

    # ── UI 设置 ─────────────────────────────────────────
    window_width: int = 1200           # 窗口宽度
    window_height: int = 800           # 窗口高度

    # 配置文件路径（不持久化到 JSON）
    _config_path: str = field(default="", repr=False)

    @property
    def proxy_url(self) -> str:
        """构建完整的代理 URL（供 yt-dlp --proxy 和 requests proxies 使用）。

        格式：{type}://[username:password@]host:port
        未启用代理时返回空字符串。
        """
        if not self.proxy_enabled:
            return ""
        auth = ""
        if self.proxy_username:
            auth = f"{self.proxy_username}:{self.proxy_password}@"
        return f"{self.proxy_type}://{auth}{self.proxy_host}:{self.proxy_port}"

    def save(self) -> None:
        """将当前配置序列化为 JSON 并保存到磁盘。

        首次调用时自动确定默认路径。目录不存在时自动创建。
        """
        if not self._config_path:
            self._config_path = _default_config_path()
        # 手动构建字典（不使用 dataclasses.asdict 以排除 _config_path）
        data = {
            "oauth_token": self.oauth_token,
            "cookies_path": self.cookies_path,
            "download_dir": self.download_dir,
            "audio_quality": self.audio_quality,
            "concurrent_downloads": self.concurrent_downloads,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "proxy_enabled": self.proxy_enabled,
            "proxy_type": self.proxy_type,
            "proxy_host": self.proxy_host,
            "proxy_port": self.proxy_port,
            "proxy_username": self.proxy_username,
            "proxy_password": self.proxy_password,
            "filename_template": self.filename_template,
            "create_playlist_folders": self.create_playlist_folders,
            "window_width": self.window_width,
            "window_height": self.window_height,
        }
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "AppConfig":
        """从磁盘加载配置，文件不存在或损坏时返回默认配置。

        使用 hasattr + setattr 动态赋值，确保新增字段不会因旧 JSON 缺失而报错，
        旧 JSON 中的废弃字段也会被忽略。

        Args:
            path: 配置文件路径。为 None 时使用默认路径。

        Returns:
            AppConfig 实例（配置已加载）
        """
        if path is None:
            path = _default_config_path()
        config = cls()
        config._config_path = path
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 动态赋值：只设置 dataclass 中存在的字段
                for key, value in data.items():
                    if hasattr(config, key):
                        setattr(config, key, value)
            except (json.JSONDecodeError, OSError):
                # 配置文件损坏 → 静默使用默认配置，不阻塞启动
                pass
        return config


def _default_config_path() -> str:
    """获取默认配置文件路径。

    Windows: %APPDATA%/YtMusicVault/config.json
    其他平台: ~/YtMusicVault/config.json
    """
    base = os.environ.get("APPDATA", str(Path.home()))
    return os.path.join(base, "YtMusicVault", "config.json")
