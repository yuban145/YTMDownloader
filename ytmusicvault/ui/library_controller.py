"""Serialized background service with stale-result rejection on the Qt thread."""
import threading
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal, Slot
from ..core.auth import LoginRequest
from ..core.ytm_client import YtmClient, Cancelled, SessionExpired, user_error


class LibraryController(QObject):
    account_changed = Signal(object)
    playlists_loaded = Signal(list)
    tracks_loaded = Signal(str, object)
    error = Signal(str, str)
    busy_changed = Signal(str, bool)
    signed_out = Signal()
    _completed = Signal(object)

    def __init__(self, auth, parent=None, connect=YtmClient.connect):
        super().__init__(parent)
        self.auth, self._connect = auth, connect
        self.credentials = None
        self.client = None
        self._pending_session = None
        self._generation = 0
        self._jobs = {}
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ytm-library")
        self._completed.connect(self._finish)

    def _invalidate(self):
        self._generation += 1
        for key, (token, future) in self._jobs.items():
            token.set()
            future.cancel()
            self.busy_changed.emit(key, False)
        self._jobs.clear()
        if self.client:
            client = self.client
            self._executor.submit(client.close)
        self.client = self.credentials = None
        self._pending_session = None

    def login(self, request, proxy_url=None):
        self._invalidate()
        self.signed_out.emit()

        def work(token):
            credentials = self.auth.prepare(request)
            if token.is_set():
                raise Cancelled()
            client, account = self._connect(credentials, proxy_url, token)
            return credentials, client, account, request
        self._submit("login", work)

    def restore(self, proxy_url=None):
        if self.auth.has_saved_session:
            self.login(LoginRequest("saved", remember=True), proxy_url)
        else:
            # A saved profile can lose its file after the account menu is built.
            # Never retain the preceding account under the newly selected name.
            self._invalidate()
            self.signed_out.emit()

    def refresh(self):
        if self.client:
            client = self.client
            self._submit("playlists", lambda token: self._call(client, token, client.get_playlists))

    def load_tracks(self, playlist_id):
        if self.client:
            client = self.client
            self._submit("tracks", lambda token: (playlist_id, self._call(
                client, token, lambda: client.get_tracks(playlist_id))))

    @staticmethod
    def _call(client, token, callback):
        if client._session:
            client._session.cancel_event = token
        if token.is_set():
            raise Cancelled()
        return callback()

    def _submit(self, kind, callback):
        if self._closed:
            return
        previous = self._jobs.get(kind)
        if previous:
            previous[0].set()
            previous[1].cancel()
        generation = self._generation
        token = threading.Event()
        self.busy_changed.emit(kind, True)

        def run():
            result, error = None, None
            try:
                if token.is_set():
                    raise Cancelled()
                result = callback(token)
            except Exception as exc:
                error = exc
            if self._closed:
                if kind == "login" and result:
                    result[1].close()
                return
            self._completed.emit((generation, kind, token, result, error))

        future = self._executor.submit(run)
        self._jobs[kind] = token, future

    @Slot(object)
    def _finish(self, message):
        generation, kind, token, result, error = message
        current = self._jobs.get(kind)
        if self._closed or generation != self._generation or not current or current[0] is not token:
            if kind == "login" and result:
                self._executor.submit(result[1].close) if not self._closed else result[1].close()
            return
        self._jobs.pop(kind)
        self.busy_changed.emit(kind, False)
        if isinstance(error, Cancelled):
            return
        if error:
            if isinstance(error, SessionExpired):
                self._invalidate()
                self.signed_out.emit()
            self.error.emit(kind, user_error(error))
            return
        if kind == "login":
            self.credentials, self.client, account, request = result
            if account.get("verified", True):
                self._persist_session(request.remember)
            else:
                # The original connection flow does not verify identity. Do
                # not overwrite a previously saved session merely because a
                # YTMusic object could be created; wait for personal data.
                self._pending_session = request.remember
            self.account_changed.emit(account)
        elif kind == "playlists":
            self.playlists_loaded.emit(result)
            if result:
                self._confirm_pending_session()
        elif kind == "tracks":
            self.tracks_loaded.emit(*result)
            if result[0] == "LM" and result[1].songs:
                self._confirm_pending_session()

    def _confirm_pending_session(self):
        if self._pending_session is not None:
            self._persist_session(self._pending_session)

    def _persist_session(self, remember):
        try:
            if remember:
                self.auth.save(self.credentials)
            else:
                self.auth.clear()
            self._pending_session = None
        except OSError:
            self.error.emit("storage", "音乐库已连接，但无法更新本地会话文件。")

    def logout(self):
        self._invalidate()
        self.auth.clear()
        self.signed_out.emit()

    def close(self):
        if self._closed:
            return
        self._invalidate()
        self._closed = True
        # Pending HTTP work exits at its bounded timeout; no QWidget touched.
        self._executor.shutdown(wait=False)
