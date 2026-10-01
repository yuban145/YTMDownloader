"""YouTube Music service: bounded HTTP requests and robust domain parsing."""
import re
import threading
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse
import requests
from ytmusicapi import YTMusic
from .auth import AuthError
from ..models.song import Song
from ..models.playlist import Playlist
from ..utils.helpers import format_duration
from ..utils.proxy import configure_requests_session


class Cancelled(Exception): pass
class SessionExpired(AuthError): pass
class ServiceError(Exception): pass


class HttpSession(requests.Session):
    def __init__(self, cancel_event=None, authenticated=False):
        super().__init__()
        self.cancel_event = cancel_event or threading.Event()
        self.authenticated = authenticated

    def request(self, method, url, **kwargs):
        if self.cancel_event.is_set():
            raise Cancelled()
        kwargs["timeout"] = (10, 30)
        response = super().request(method, url, **kwargs)
        if self.cancel_event.is_set():
            raise Cancelled()
        if response.status_code in (401, 403):
            raise SessionExpired("登录已过期或账号无权限，请重新登录并确认账号序号。")
        if self.authenticated and _is_signed_out_response(url, response):
            raise SessionExpired("YouTube Music 未识别到有效登录状态，请重新导入 Cookie 并确认账号序号。")
        response.raise_for_status()
        return response


def _is_signed_out_response(url, response):
    """Recognize only explicit signed-out markers on authenticated Music API calls."""
    try:
        parsed = urlparse(url)
        if parsed.hostname != "music.youtube.com" or not parsed.path.startswith("/youtubei/v1/"):
            return False
        content_type = response.headers.get("Content-Type", "")
        if content_type and "json" not in content_type.lower():
            return False
        data = response.json()
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    contexts = [data]
    response_context = data.get("responseContext")
    if isinstance(response_context, dict):
        contexts.append(response_context)
    for context in contexts:
        app_context = context.get("mainAppWebResponseContext")
        if isinstance(app_context, dict) and app_context.get("loggedOut") is True:
            return True
        tracking = context.get("serviceTrackingParams")
        if not isinstance(tracking, list):
            continue
        for service in tracking:
            if not isinstance(service, dict) or not isinstance(service.get("params"), list):
                continue
            if any(isinstance(param, dict) and param.get("key") == "logged_in"
                   and param.get("value") == "0" for param in service["params"]):
                return True
    return False


def user_error(exc):
    if isinstance(exc, (AuthError, ServiceError)):
        return str(exc)
    if isinstance(exc, requests.exceptions.ProxyError):
        return "代理连接失败，请检查代理地址、端口和运行状态。"
    if isinstance(exc, requests.exceptions.SSLError):
        return "HTTPS 证书校验失败，请检查系统时间或代理证书。"
    if isinstance(exc, requests.exceptions.Timeout):
        return "请求超时，请检查网络或代理后重试。"
    if isinstance(exc, requests.exceptions.RequestException):
        return "网络请求失败，请检查网络或代理后重试。"
    return "服务返回了无法解析的数据，请重试；持续失败时请更新 ytmusicapi。"


@dataclass
class TrackBatch:
    songs: list[Song] = field(default_factory=list)
    skipped: int = 0


class YtmClient:
    def __init__(self, ytm, session=None):
        self._ytm, self._session = ytm, session

    @classmethod
    def connect(cls, credentials, proxy_url=None, cancel_event=None):
        session = HttpSession(cancel_event, authenticated=bool(credentials.headers.get("cookie")))
        try:
            proxies = configure_requests_session(session, proxy_url)
            api = YTMusic(auth=dict(credentials.headers), requests_session=session,
                          proxies=proxies or None, language="en",
                          user=credentials.headers.get("x-goog-pageid"))
            # Identity is best-effort only: never make login or playlist access
            # depend on this extra endpoint. The original library flow stays
            # unchanged if account-menu parsing/network access fails.
            account = {"accountName": "账号未验证", "verified": False, "identityAvailable": False}
            try:
                identity = api.get_account_info()
                if (isinstance(identity, dict) and isinstance(identity.get("accountName"), str)
                        and identity["accountName"].strip()):
                    # Only copy fields consumed as display metadata. API responses
                    # can be incomplete or contain unexpected nested values.
                    account["accountName"] = identity["accountName"].strip()
                    handle = identity.get("channelHandle")
                    if isinstance(handle, str):
                        account["channelHandle"] = handle
                    # Keep the existing session-persistence gate unchanged;
                    # this extra response is only for the account-switch label.
                    account["verified"] = False
                    account["identityAvailable"] = True
            except Cancelled:
                raise
            except Exception:
                pass
            return cls(api, session), account
        except Exception:
            session.close()
            raise

    def account(self):
        try:
            account = self._ytm.get_account_info()
        except (KeyError, IndexError):
            raise SessionExpired("无法确认登录账号，请在浏览器完成 YouTube Music 登录后重新导入。") from None
        if (not isinstance(account, dict) or not isinstance(account.get("accountName"), str)
                or not account["accountName"].strip()):
            raise SessionExpired("服务器未返回登录账号，请重新登录。")
        return account

    def close(self):
        if self._session:
            self._session.close()

    def get_playlists(self):
        # Keep the original library endpoint and limit from the working flow.
        raw = self._ytm.get_library_playlists(limit=100)
        if not isinstance(raw, list):
            raise ServiceError("播放列表响应异常，请重试。")
        result, seen = [], set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            pid = item.get("playlistId")
            if not isinstance(pid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", pid) or pid in seen or pid == "LM":
                continue
            seen.add(pid)
            result.append(Playlist(playlist_id=pid, title=_text(item.get("title")) or "未命名歌单",
                                   count=_number(item.get("count")), thumbnail=_best_thumbnail(item.get("thumbnails")),
                                   description=_text(item.get("description")), owned=bool(item.get("owned"))))
        return result

    def get_tracks(self, playlist_id):
        pid = parse_playlist_id(playlist_id)
        # First-version liked songs used the dedicated endpoint. Current
        # ytmusicapi accepts playlistId (positional), not playlist_id.
        raw = (self._ytm.get_liked_songs(limit=5000) if pid == "LM" else
               self._ytm.get_playlist(pid, limit=5000))
        if not isinstance(raw, dict) or not isinstance(raw.get("tracks"), list):
            raise ServiceError("无法获取歌曲：歌单可能已删除、设为私密，或当前账号没有权限。")
        batch = TrackBatch()
        for track in raw["tracks"]:
            song = self._parse_track(track)
            if song is None:
                batch.skipped += 1
            else:
                batch.songs.append(song)
        return batch

    def get_liked_songs(self):
        return self.get_tracks("LM").songs

    def get_playlist_songs(self, playlist_id):
        return self.get_tracks(playlist_id).songs

    @staticmethod
    def _parse_track(raw):
        if not isinstance(raw, dict) or raw.get("isAvailable") is False:
            return None
        video_id = raw.get("videoId")
        if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", video_id):
            return None
        artists = raw.get("artists") or []
        if not isinstance(artists, list):
            artists = []
        artist = ", ".join(filter(None, (_text(a.get("name")) for a in artists if isinstance(a, dict))))
        album = raw.get("album")
        seconds = _number(raw.get("duration_seconds")) or _parse_duration_seconds(raw.get("duration"))
        return Song(video_id=video_id, title=_text(raw.get("title")) or "未知标题",
                    artist=artist or "未知艺术家", album=_text(album.get("name")) if isinstance(album, dict) else "",
                    duration=seconds, duration_str=format_duration(seconds),
                    thumbnail=_best_thumbnail(raw.get("thumbnails")),
                    track_number=_number(raw.get("trackNumber") or raw.get("track_number")),
                    year=_number(raw.get("year")))


def parse_playlist_id(value):
    if not isinstance(value, str):
        raise ServiceError("无效的播放列表 ID 或链接。")
    value = value.strip()
    if "://" in value:
        try:
            url = urlparse(value)
        except ValueError:
            raise ServiceError("无效的播放列表 ID 或链接。") from None
        if url.scheme not in ("https", "http") or url.hostname not in ("youtube.com", "www.youtube.com", "music.youtube.com"):
            raise ServiceError("请输入 YouTube 或 YouTube Music 播放列表链接。")
        value = parse_qs(url.query).get("list", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ServiceError("无效的播放列表 ID 或链接。")
    return value


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        runs = value.get("runs")
        if isinstance(runs, list):
            return "".join(r["text"] for r in runs if isinstance(r, dict) and isinstance(r.get("text"), str))
        simple_text = value.get("simpleText")
        return simple_text if isinstance(simple_text, str) else ""
    return ""


def _number(value):
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str):
        match = re.fullmatch(r"([\d,\s]+)(?: songs?| tracks?| 首.*)?", value.strip())
        if match:
            digits = re.sub(r"\D", "", match[1])
            return int(digits) if digits else 0
    return 0


def _parse_duration_seconds(value):
    if not isinstance(value, str):
        return 0
    parts = value.split(":")
    if len(parts) > 3 or not all(p.isdecimal() for p in parts):
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def _best_thumbnail(thumbnails):
    if not isinstance(thumbnails, list):
        return ""
    valid = [t for t in thumbnails if isinstance(t, dict) and isinstance(t.get("url"), str) and t["url"]]
    return max(valid, key=lambda t: _number(t.get("width")) * _number(t.get("height")),
               default={}).get("url", "")
