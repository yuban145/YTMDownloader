"""认证模块 — 基于 Cookies 的 YouTube Music 登录。

认证策略（无需 OAuth，无需 Google API Key）：
    1. 用户在嵌入式浏览器（login_browser.py）登录 music.youtube.com
    2. 登录成功后提取两类凭据：
       - cookies.txt  (Netscape 格式) → 给 yt-dlp 下载引擎使用
       - headers.json (HTTP headers)    → 给 ytmusicapi 库使用
    3. headers.json 包含 Cookie 头 + SAPISIDHASH 授权头

为什么不用 OAuth？
    - OAuth 需要 Google Cloud 项目，普通用户难以配置
    - Cookies 方式与浏览器登录体验一致，支持二步验证
    - yt-dlp 原生支持 --cookies 参数

⚠️ 安全提醒：cookies.txt 和 headers.json 包含敏感凭据，切勿分享！
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

from ytmusicapi import YTMusic

_log = logging.getLogger(__name__)


class AuthManager:
    """管理 YouTube Music 的 Cookies + Headers 认证。
    
    职责：
      1. 维护 cookies.txt 和 headers.json 的路径
      2. 检测是否已有有效凭据（has_cookies）
      3. 用 headers.json 创建 YTMusic 实例（login）
      4. 清除凭据（clear）
    
    存储位置：%APPDATA%/YtMusicVault/（Windows）或 ~/YtMusicVault/（其他平台）
    """

    def __init__(self, config_dir: Optional[str] = None):
        """初始化 AuthManager。
        
        Args:
            config_dir: 凭据存储目录。为 None 时自动使用系统默认路径。
        """
        if config_dir is None:
            # Windows: %APPDATA%/YtMusicVault/
            # 其他: ~/YtMusicVault/
            config_dir = os.path.join(
                os.environ.get("APPDATA", str(Path.home())),
                "YtMusicVault"
            )
        self._config_dir = config_dir
        # cookies.txt — Netscape 格式，给 yt-dlp 用
        self._cookies_path = os.path.join(config_dir, "cookies.txt")
        # headers.json — HTTP Headers，给 ytmusicapi 用
        self._headers_path = os.path.join(config_dir, "headers.json")
        # 确保目录存在（exist_ok=True 不会抛异常）
        os.makedirs(config_dir, exist_ok=True)

    @property
    def cookies_path(self) -> str:
        """Netscape cookies.txt 的完整路径（供 yt-dlp --cookies 使用）。"""
        return self._cookies_path

    @property
    def headers_path(self) -> str:
        """headers.json 的完整路径（供 ytmusicapi auth= 参数使用）。"""
        return self._headers_path

    @property
    def has_cookies(self) -> bool:
        """Return whether a usable generated header file is present."""
        return (
            os.path.isfile(self._headers_path)
            and os.path.getsize(self._headers_path) > 0
            and os.path.isfile(self._cookies_path)
            and os.path.getsize(self._cookies_path) > 0
        )

    def import_cookies(self, source_path: str) -> None:
        """Import a Netscape cookies.txt and generate ytmusicapi headers.

        Browser exports contain the cookies needed by yt-dlp, while
        ytmusicapi expects a JSON headers file (including SAPISIDHASH).
        Keeping this conversion here makes file import and embedded-browser
        login use the same credential contract.
        """
        import shutil
        import time
        import hashlib

        source = Path(source_path)
        if not source.is_file():
            raise ValueError("Cookies 文件不存在")
        rows = []
        auth_names = {
            "LOGIN_INFO", "SID", "HSID", "SSID", "APISID", "SAPISID",
            "__Secure-3PSID", "__Secure-3PAPISID",
        }
        with source.open("r", encoding="utf-8-sig", errors="replace") as f:
            for line_no, raw_line in enumerate(f, 1):
                line = raw_line.rstrip("\r\n")
                if not line or line.startswith("#"):
                    continue
                fields = line.split("\t")
                if len(fields) != 7:
                    raise ValueError(f"Cookies 文件第 {line_no} 行不是 7 列 Netscape 格式")
                domain, flag, path, secure, expires, name, value = fields
                if not domain or not path or not name:
                    raise ValueError(f"Cookies 文件第 {line_no} 行包含空字段")
                try:
                    expiry = int(expires)
                except ValueError as exc:
                    raise ValueError(f"Cookies 文件第 {line_no} 行过期时间无效") from exc
                if expiry and expiry < int(time.time()):
                    continue
                rows.append((domain, flag, path, secure, expires, name, value))

        if not rows:
            raise ValueError("Cookies 文件为空或所有 Cookie 均已过期")
        if not any(row[5] in auth_names for row in rows):
            raise ValueError("Cookies 文件中未找到 Google 登录凭据")

        # Keep the original Netscape export for yt-dlp.
        os.makedirs(self._config_dir, exist_ok=True)
        shutil.copy2(source, self._cookies_path)

        # A request must contain one value per cookie name. Prefer the most
        # specific domain when browser exports contain duplicates.
        by_name = {}
        domain_rank = lambda d: (
            3 if d in ("music.youtube.com", "www.youtube.com") else
            2 if "youtube.com" in d else
            1 if "google.com" in d else 0
        )
        for row in rows:
            current = by_name.get(row[5])
            if current is None or domain_rank(row[0]) >= domain_rank(current[0]):
                by_name[row[5]] = row
        cookie_header = "; ".join(
            f"{row[5]}={row[6]}" for row in by_name.values()
        )

        sapisid = ""
        for name in ("__Secure-3PAPISID", "SAPISID", "APISID"):
            if name in by_name:
                sapisid = by_name[name][6]
                break
        timestamp = str(int(time.time()))
        digest = hashlib.sha1(
            f"{timestamp} {sapisid}".encode("utf-8")
        ).hexdigest()
        headers = {
            "cookie": cookie_header,
            "authorization": f"SAPISIDHASH {timestamp}_{digest}",
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
        temp_path = self._headers_path + ".tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(headers, f, indent=2)
            os.replace(temp_path, self._headers_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        try:
            os.chmod(self._cookies_path, 0o600)
            os.chmod(self._headers_path, 0o600)
        except OSError:
            pass

    def login(self, proxy_url: str = "") -> Optional[YTMusic]:
        """用 headers.json 创建 YTMusic 实例。
        
        YTMusic 是 ytmusicapi 库的主入口，提供 get_liked_songs、
        get_playlist 等 API 方法。
        
        Args:
            proxy_url: 代理 URL（如 http://127.0.0.1:1080），为空则不使用代理
        Returns:
            YTMusic 实例（登录成功）或 None（未登录/凭据损坏）
        """
        if not self.has_cookies:
            _log.info("No headers.json found — user needs to log in")
            return None
        try:
            # 先验证 JSON 格式，避免传损坏的文件给 ytmusicapi 导致难以调试的错误
            with open(self._headers_path, encoding="utf-8") as f:
                json.load(f)

            # ytmusicapi 底层使用 requests 库 → 通过 proxies 参数设置代理
            extra_kwargs = {}
            if proxy_url:
                extra_kwargs["proxies"] = {"http": proxy_url, "https": proxy_url}
                _log.info(f"Using proxy for ytmusicapi: {proxy_url}")

            # auth= 参数接受 headers.json 文件路径，自动读取 Cookie 和 Authorization
            ytm = YTMusic(auth=self._headers_path, **extra_kwargs)
            _log.info("Logged in via headers.json")
            return ytm
        except json.JSONDecodeError:
            # headers.json 损坏（如写入过程被中断）→ 清除凭据让用户重新登录
            _log.warning("headers.json is corrupted, clearing")
            self.clear()
            return None
        except Exception as e:
            # 网络错误、认证过期等其他异常
            _log.warning(f"Login failed: {e}")
            return None

    def clear(self):
        """删除所有已保存的凭据文件（cookies.txt + headers.json）。
        
        用于用户登出或凭据损坏时清理。
        """
        for path in (self._cookies_path, self._headers_path):
            if os.path.exists(path):
                os.remove(path)
                _log.info(f"Removed {path}")
                _log.info(f"Removed {path}")
