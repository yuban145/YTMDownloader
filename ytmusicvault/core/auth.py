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
    def has_saved_session(self):
        return self.path.is_file() or (self.directory / "headers.json").is_file()

    def prepare(self, request):
        if request.kind == "saved":
            return self.load()
        if request.kind == "headers":
            return parse_headers(request.value)
        jar = MozillaCookieJar()
        try:
            if request.kind == "browser":
                if request.value not in BROWSERS:
                    raise AuthError("请选择支持的浏览器。")
                from yt_dlp.cookies import extract_cookies_from_browser
                jar = extract_cookies_from_browser(request.value, request.profile or None,
                                                   logger=_QuietCookieLogger())
            elif request.kind == "file":
                jar.load(request.value, ignore_discard=True, ignore_expires=True)
            elif request.kind == "embedded":
                # MozillaCookieJar's parser is file based; keep this temporary
                # export isolated and delete it immediately after parsing.
                with tempfile.TemporaryDirectory(prefix="ytmv-cookie-") as folder:
                    path = Path(folder) / "cookies.txt"
                    path.write_text(request.value, encoding="utf-8")
                    jar.load(str(path), ignore_discard=True, ignore_expires=True)
            else:
                raise AuthError("未知的登录方式。")
            credentials = from_cookie_jar(jar, request.kind, request.account_index)
            return Credentials(credentials.headers, request.kind, download_cookie_text(jar))
        except AuthError:
            raise
        except Exception:
            raise AuthError("浏览器或 Cookie 文件读取失败，请重新导出或使用请求头登录。") from None

    def load(self):
        source = self.path if self.path.is_file() else self.directory / "headers.json"
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
            if source == self.path:
                credentials = normalize_headers(data["headers"], data.get("source", "saved"))
                text = data.get("download_cookie_text", "")
                if not isinstance(text, str):
                    raise ValueError("Invalid cookie text")
                return Credentials(credentials.headers, credentials.source, text)
            return normalize_headers(data, "saved")
        except Exception:
            raise AuthError("已保存的会话无法读取，请重新登录。") from None

    def save(self, credentials):
        validated = normalize_headers(credentials.headers, credentials.source)
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".session-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "headers": validated.headers, "source": credentials.source,
                           "download_cookie_text": credentials.download_cookies()}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def clear(self):
        for name in ("session.json", "headers.json", "cookies.txt"):
            (self.directory / name).unlink(missing_ok=True)
