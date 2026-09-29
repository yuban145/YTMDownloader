"""Credential inputs and atomic storage. No network or Qt dependency here."""
import json
import os
import tempfile
from dataclasses import dataclass, field
from http.cookiejar import MozillaCookieJar
from http.cookies import SimpleCookie
from pathlib import Path
from ytmusicapi.helpers import get_authorization

ORIGIN = "https://music.youtube.com"
BROWSERS = ("edge", "chrome", "firefox", "brave", "vivaldi", "opera", "chromium")
LEGACY_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0.0.0 Safari/537.36")


class AuthError(ValueError):
    """Safe user-facing error, never includes credential contents."""


@dataclass(frozen=True)
class Credentials:
    headers: dict = field(repr=False)
    source: str = "headers"
    download_cookie_text: str = field(default="", repr=False, compare=False)

    def download_cookies(self):
        if self.download_cookie_text:
            return self.download_cookie_text
        jar = SimpleCookie()
        jar.load(self.headers["cookie"])
        lines = ["# Netscape HTTP Cookie File"]
        for key, cookie in jar.items():
            lines.append(f".youtube.com\tTRUE\t/\tTRUE\t0\t{key}\t{cookie.value}")
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class LoginRequest:
    kind: str
    value: str = field(default="", repr=False)
    profile: str = ""
    account_index: str = "0"
    remember: bool = False


def normalize_headers(raw, source="headers"):
    if not isinstance(raw, dict):
        raise AuthError("请求头必须是 JSON 对象或浏览器复制的请求头文本。")
    allowed = {"cookie", "x-goog-authuser", "x-goog-pageid", "x-goog-visitor-id", "user-agent"}
    headers = {str(k).lower(): v for k, v in raw.items() if str(k).lower() in allowed}
    if any(not isinstance(v, str) or any(c in v for c in "\r\n\t\x00") for v in headers.values()):
        raise AuthError("请求头格式无效，请重新复制完整请求头。")
    jar = SimpleCookie()
    try:
        jar.load(headers.get("cookie", ""))
    except Exception:
        raise AuthError("Cookie 格式无效。") from None
    secret = jar.get("__Secure-3PAPISID")
    if not secret or not secret.value:
        raise AuthError("缺少 __Secure-3PAPISID 登录 Cookie。请在浏览器登录 music.youtube.com 后重新导入。")
    if any(any(c in item.value for c in "\r\n\t\x00") for item in jar.values()):
        raise AuthError("Cookie 内容含无效字符。")
    account = headers.get("x-goog-authuser", "0")
    if not account.isdigit():
        raise AuthError("账号序号必须是非负整数。")
    headers.update({"accept": "*/*", "content-type": "application/json",
                    "x-goog-authuser": account, "origin": ORIGIN, "x-origin": ORIGIN,
                    "authorization": get_authorization(secret.value + " " + ORIGIN)})
    # The original cookies.txt login supplied a browser User-Agent. Keep that
    # request shape for file and browser imports without replacing pasted UAs.
    headers.setdefault("user-agent", LEGACY_USER_AGENT)
    # ytmusicapi regenerates SAPISIDHASH for every request.
    return Credentials(headers, source)


def parse_headers(text):
    if not text.strip():
        # ytmusicapi.setup treats empty input as an interactive CLI prompt.
        raise AuthError("请先粘贴浏览器请求头。")
    try:
        if text.lstrip().startswith("{"):
            raw = json.loads(text)
        else:
            from ytmusicapi import setup
            raw = json.loads(setup(headers_raw=text))
        return normalize_headers(raw)
    except AuthError:
        raise
    except Exception:
        raise AuthError("无法解析请求头。请粘贴 /browse 请求的完整请求头，或仅包含请求头的 JSON。") from None


def from_cookie_jar(jar, source, account_index="0"):
    selected = {}
    for cookie in sorted(jar, key=lambda c: len(c.domain or "")):
        # Browser exporters commonly encode a session cookie as expiry=0.
        if cookie.expires == 0:
            cookie.expires = None
        domain = (cookie.domain or "").lstrip(".").lower()
        if domain not in {"youtube.com", "music.youtube.com"} or cookie.is_expired():
            continue
        if not cookie.value or any(c in cookie.value for c in "\r\n\t;\x00"):
            continue
        selected[cookie.name] = cookie.value
    return normalize_headers({"cookie": "; ".join(f"{k}={v}" for k, v in selected.items()),
                              "x-goog-authuser": str(account_index)}, source)


def download_cookie_text(jar):
    """Keep extracted YouTube cookie scope/expiry for yt-dlp --cookies."""
    lines = ["# Netscape HTTP Cookie File"]
    for cookie in jar:
        domain = (cookie.domain or "").lstrip(".").lower()
        if domain != "youtube.com" and not domain.endswith(".youtube.com"):
            continue
        if cookie.expires not in (None, 0) and cookie.is_expired():
            continue
        if not cookie.name or not cookie.value or any(
                bad in cookie.name + cookie.value for bad in "\r\n\t\x00"):
            continue
        host = cookie.domain or "youtube.com"
        subdomains = cookie.domain_initial_dot or host.startswith(".")
        if subdomains and not host.startswith("."):
            host = "." + host
        lines.append("\t".join((host, "TRUE" if subdomains else "FALSE",
                                cookie.path or "/", "TRUE" if cookie.secure else "FALSE",
                                str(cookie.expires or 0), cookie.name, cookie.value)))
    return "\n".join(lines) + "\n"


def detect_browsers():
    local, roaming = os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")
    roots = {"edge": (local, "Microsoft/Edge/User Data"),
             "chrome": (local, "Google/Chrome/User Data"),
             "firefox": (roaming, "Mozilla/Firefox/Profiles"),
             "brave": (local, "BraveSoftware/Brave-Browser/User Data"),
             "vivaldi": (local, "Vivaldi/User Data"),
             "opera": (roaming, "Opera Software/Opera Stable"),
             "chromium": (local, "Chromium/User Data")}
    return [name for name, (base, suffix) in roots.items() if base and (Path(base) / suffix).is_dir()]


class _QuietCookieLogger:
    def debug(self, *args, **kwargs): pass
    def info(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
    def error(self, *args, **kwargs):
        raise AuthError("浏览器 Cookie 读取失败。请尝试请求头登录。")


class AuthManager:
    def __init__(self, config_dir=None):
        self.directory = Path(config_dir or Path(os.environ.get("APPDATA", str(Path.home()))) / "YtMusicVault")
        self.path = self.directory / "session.json"

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
        if not any(row[5] in {"__Secure-3PAPISID", "SAPISID", "APISID"} for row in rows):
            raise ValueError("Cookies 文件中未找到 SAPISID 授权凭据")

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
        for name in ("session.json", "headers.json", "cookies.txt"):
            (self.directory / name).unlink(missing_ok=True)
