"""Opt-in live Qt WebEngine cookie and page probe; never prints cookie values."""
import sys
from http.cookiejar import MozillaCookieJar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QDateTime, QTimer, QUrl
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from ytmusicvault.core.auth import AuthManager, LoginRequest
from ytmusicvault.ui.embedded_browser import youtube_cookie_line


def main():
    if len(sys.argv) != 2:
        return 2
    source = MozillaCookieJar()
    source.load(sys.argv[1], ignore_discard=True, ignore_expires=True)
    app = QApplication.instance() or QApplication([])
    profile = QWebEngineProfile()
    store = profile.cookieStore()
    cookies = {}

    def added(cookie):
        if youtube_cookie_line(cookie):
            cookies[(cookie.domain(), cookie.path(), bytes(cookie.name()))] = QNetworkCookie(cookie)

    store.cookieAdded.connect(added)
    expected = 0
    for item in source:
        if item.domain.lstrip(".").lower() != "youtube.com":
            continue
        if item.expires not in (None, 0) and item.is_expired():
            continue
        cookie = QNetworkCookie(item.name.encode(), item.value.encode())
        cookie.setDomain(item.domain)
        cookie.setPath(item.path)
        cookie.setSecure(item.secure)
        cookie.setHttpOnly(bool(item.has_nonstandard_attr("HTTPOnly")))
        if item.expires:
            cookie.setExpirationDate(QDateTime.fromSecsSinceEpoch(item.expires))
        store.setCookie(cookie)
        expected += 1

    view = QWebEngineView(profile)
    result = {"loaded": False, "finished": False}
    view.loadFinished.connect(lambda ok: (
        result.update(loaded=ok, finished=True, host=view.url().host(), title=view.title()), app.quit()))
    QTimer.singleShot(1000, lambda: view.setUrl(QUrl("https://music.youtube.com")))
    QTimer.singleShot(30000, app.quit)
    app.exec()
    lines = [youtube_cookie_line(cookie) for cookie in cookies.values()]
    lines = [line for line in lines if line]
    host_ok = result.get("host") == "music.youtube.com"
    title_ok = "YouTube Music" in result.get("title", "")
    print(f"webengine_page_loaded={result['loaded']}; host_ok={host_ok}; title_ok={title_ok}; captured_youtube_cookies={len(lines)}; "
          f"imported={expected}; memory_only={profile.isOffTheRecord()}", flush=True)
    if not result["loaded"] or not host_ok or not title_ok:
        return 1
    try:
        credentials = AuthManager().prepare(LoginRequest("embedded", "# Netscape HTTP Cookie File\n" +
                                                    "\n".join(lines) + "\n"))
    except Exception:
        print("embedded_cookie_handoff=failed", flush=True)
        return 1
    print(f"embedded_cookie_handoff=ok; source={credentials.source}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
