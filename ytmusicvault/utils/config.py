"""应用配置管理 — JSON 持久化的用户偏好设置。

使用 dataclass 定义配置字段，save()/load() 实现 JSON 序列化/反序列化。
配置存储位置：%APPDATA%/YtMusicVault/config.json（Windows）

设计要点：
  - load() 验证 JSON 字段类型和范围，兼容新增/删除字段
  - 配置损坏（JSONDecodeError）时静默回退到默认值，不阻塞启动
  - proxy_url 属性动态拼接完整代理 URL
"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import quote


@dataclass
class AppConfig:
    """持久化应用配置。

    所有字段都有默认值，确保首次启动（无 config.json）也能正常运行。
    _config_path 不参与序列化（repr=False），仅用于 save()/load() 定位文件。
    """

    # ── 认证 ────────────────────────────────────────────
    oauth_token: str = ""              # （保留字段，当前使用 Cookies 认证）
    cookies_path: str = ""             # 自定义 cookies.txt 路径
    browser_cookie_source: str = "none" # auto/edge/chrome/firefox/brave/vivaldi/opera/none

    # ── 下载设置 ────────────────────────────────────────
    download_dir: str = str(Path.home() / "Music" / "YtMusicVault")  # 默认下载目录
    audio_quality: str = "best"        # MP3 转码码率设置；best 为最佳可用质量
    download_mode: str = "video"       # video: 最高画质 MV / audio: 单独音频
    audio_format: str = "mp3"          # flac / mp3；旧配置仍可使用 m4a
    concurrent_downloads: int = 4      # 最大同时下载数
    max_retries: int = 3               # 失败重试次数
    retry_delay: int = 5               # 重试间隔（秒）

    # ── 代理设置（防火墙后用户） ────────────────────────
    proxy_enabled: bool = True        # 是否启用代理
    proxy_mode: str = "manual"         # system / manual / direct / pac
    proxy_type: str = "http"           # 代理类型：http, socks5
    proxy_host: str = "127.0.0.1"      # 代理主机
    proxy_port: int = 7890             # 代理端口
    proxy_pac_url: str = ""            # PAC URL or local file path
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
    def proxy_url(self) -> Optional[str]:
        """构建完整的代理 URL（供 yt-dlp 和 requests 使用）。

        格式：{type}://[username:password@]host:port
        system 返回 None，direct 返回空字符串。
        """
        if self.proxy_mode == "system":
            return None  # requests / yt-dlp inherit environment + Windows proxy settings
        if self.proxy_mode == "direct":
            return ""
        if self.proxy_mode == "pac":
            return "pac:" + self.proxy_pac_url.strip()
        auth = ""
        if self.proxy_username:
            auth = f"{quote(self.proxy_username, safe='')}:{quote(self.proxy_password, safe='')}@"
        host = self.proxy_host.strip()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{self.proxy_type}://{auth}{host}:{self.proxy_port}"

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
            "browser_cookie_source": self.browser_cookie_source,
            "download_dir": self.download_dir,
            "audio_quality": self.audio_quality,
            "download_mode": self.download_mode,
            "audio_format": self.audio_format,
            "concurrent_downloads": self.concurrent_downloads,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "proxy_enabled": self.proxy_enabled,
            "proxy_mode": self.proxy_mode,
            "proxy_pac_url": self.proxy_pac_url,
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
        path = Path(self._config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=path.name + ".", suffix=".tmp", delete=False) as f:
                temporary = Path(f.name)
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "AppConfig":
        """从磁盘加载配置，文件不存在或损坏时返回默认配置。

        验证字段类型后赋值，确保新增字段不会因旧 JSON 缺失而报错，
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
                if not isinstance(data, dict):
                    return config
                ranges = {"concurrent_downloads": (1, 8), "max_retries": (0, 10),
                          "retry_delay": (0, 60), "proxy_port": (1, 65535),
                          "window_width": (320, 16384), "window_height": (240, 16384)}
                choices = {"proxy_mode": ("system", "manual", "direct", "pac"),
                           "proxy_type": ("http", "https", "socks5", "socks5h"),
                           "download_mode": ("video", "audio"),
                           "audio_format": ("flac", "mp3", "m4a")}
                for key, value in data.items():
                    if key not in cls.__dataclass_fields__ or key.startswith("_"):
                        continue
                    if type(value) is not type(getattr(config, key)):
                        continue
                    if key in ranges and not ranges[key][0] <= value <= ranges[key][1]:
                        continue
                    if key in choices and value not in choices[key]:
                        continue
                    if key in ("download_dir", "proxy_host", "filename_template") and not value.strip():
                        continue
                    setattr(config, key, value)
                if "proxy_mode" not in data and isinstance(data.get("proxy_enabled"), bool):
                    config.proxy_mode = "manual" if data["proxy_enabled"] else "system"
                if config.proxy_mode not in ("system", "manual", "direct", "pac"):
                    config.proxy_mode = "manual"
                config.proxy_enabled = config.proxy_mode == "manual"
                if config.download_mode not in ("video", "audio"):
                    config.download_mode = "video"
                if config.audio_format not in ("flac", "mp3", "m4a"):
                    config.audio_format = "mp3"
            except (json.JSONDecodeError, OSError, UnicodeError):
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
