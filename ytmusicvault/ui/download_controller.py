"""Download batches have independent workers, credentials and lifecycle."""
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from PySide6.QtCore import QObject, Signal
from ..core.downloader import Downloader
from ..core.metadata import MetadataWriter
from ..models.song import DownloadStatus
from ..core.ytm_client import Cancelled, user_error
from ..core.mv_lookup import resolve_mv
from ..core.download_log import DownloadLog
from ..core.database import media_type_for_download


class DownloadController(QObject):
    updated = Signal(object)
    finished = Signal(object)
    log_entry = Signal(object)

    def __init__(self, db, parent=None, log_path=None):
        super().__init__(parent)
        self.db = db
        self.running = False
        self._cancel = threading.Event()
        self._active = set()
        self._lock = threading.Lock()
        self._log = DownloadLog(log_path)
        self._progress_buckets = {}

    def start(self, songs, config, credentials):
        if self.running:
            return
        self.running = True
        self._cancel.clear()
        self._progress_buckets.clear()
        config = replace(config)
        songs = list({s.video_id: replace(s, status=DownloadStatus.PENDING, error_msg="", progress=0,
                                        speed="", file_path="",
                                        download_mode=config.download_mode, audio_format=config.audio_format,
                                        stage="", download_video_id="") for s in songs}.values())
        self.total = len(songs)
        threading.Thread(target=self._run, args=(songs, config, credentials), daemon=True).start()

    def cancel(self):
        self._cancel.set()
        with self._lock:
            for downloader in self._active:
                downloader.cancel()

    def _run(self, songs, config, credentials):
        try:
            with ThreadPoolExecutor(max_workers=max(1, config.concurrent_downloads)) as pool:
                jobs = [pool.submit(self._one, song, config, credentials) for song in songs]
                for job in as_completed(jobs):
                    job.result()
        finally:
            self.running = False
            self.finished.emit(songs)

    def _one(self, song, config, credentials):
        try:
            if self._cancel.is_set():
                song.status = DownloadStatus.PAUSED
                self._record(song, "已取消", "任务开始前已取消")
                return
            song.status = DownloadStatus.DOWNLOADING
            self._stage(song, "准备任务", "已加入下载队列")
            self.updated.emit(replace(song))
            if config.download_mode == "video":
                self._stage(song, "查找对应 MV", "正在查询歌曲对应的视频")
                song.download_video_id = resolve_mv(song, credentials, config.proxy_url, self._cancel)
                self._record(song, "已找到 MV", "将下载对应视频并保留最高可用画质")
            # yt-dlp may rewrite its jar: each worker owns its temporary copy.
            with tempfile.TemporaryDirectory(prefix="ytmv-download-") as directory:
                path = os.path.join(directory, "cookies.txt")
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write(credentials.download_cookies())
                downloader = Downloader(config.download_dir, config.audio_quality, config.filename_template,
                                        cookies_path=path, browser_cookie_source="none", proxy_url=config.proxy_url,
                                        download_mode=config.download_mode, audio_format=config.audio_format)
                with self._lock:
                    self._active.add(downloader)
                try:
                    for attempt in range(max(0, config.max_retries) + 1):
                        if self._cancel.is_set():
                            break
                        song.status = DownloadStatus.DOWNLOADING
                        song.stage = "正在启动 yt-dlp"
                        self._record(song, "开始下载", f"第 {attempt + 1} 次尝试；类型：{self._media_label(config)}")
                        self.updated.emit(replace(song))
                        success = downloader.download(song, progress_callback=lambda p, s, e: self._progress(song, p, s),
                                                      event_callback=lambda stage: self._stage(song, stage, stage),
                                                      cancel_event=self._cancel)
                        if self._cancel.is_set():
                            break
                        if success:
                            self._stage(song, "写入元数据", "写入标题、作者、专辑等本地标签")
                            if not MetadataWriter(proxy_url=config.proxy_url).write(song, cancel_event=self._cancel):
                                song.error_msg = "文件已下载，但元数据写入失败；请重试。"
                                self._record(song, "元数据失败", song.error_msg)
                                break
                            if self._cancel.is_set():
                                break
                            self.db.mark_downloaded(song.video_id, song.title, song.artist, song.album,
                                                    song.duration, song.file_path, os.path.getsize(song.file_path),
                                                    media_type=media_type_for_download(config.download_mode, config.audio_format),
                                                    source_video_id=song.download_video_id or song.video_id)
                            song.status = DownloadStatus.COMPLETED
                            song.stage = "下载完成"
                            self._record(song, "下载完成", song.file_path)
                            return
                        if song.error_msg:
                            self._record(song, "本次尝试失败", song.error_msg)
                        if attempt < config.max_retries and self._cancel.wait(config.retry_delay):
                            break
                    song.status = DownloadStatus.PAUSED if self._cancel.is_set() else DownloadStatus.FAILED
                finally:
                    with self._lock:
                        self._active.discard(downloader)
        except Exception as exc:
            song.status = DownloadStatus.PAUSED if self._cancel.is_set() or isinstance(exc, Cancelled) else DownloadStatus.FAILED
            song.error_msg = "" if song.status == DownloadStatus.PAUSED else user_error(exc)
            self._record(song, "已取消" if song.status == DownloadStatus.PAUSED else "下载失败", song.error_msg)
        finally:
            if song.status == DownloadStatus.PAUSED:
                song.stage = "已取消"
                self._record(song, "已取消", "任务已停止")
            elif song.status == DownloadStatus.FAILED:
                song.stage = "下载失败"
                if song.error_msg:
                    self._record(song, "下载失败", song.error_msg)
            self.updated.emit(replace(song))

    def _progress(self, song, percent, speed):
        song.progress, song.speed = percent, speed
        song.stage = f"下载媒体流 · {percent:.1f}%" + (f" · {speed}" if speed else "")
        bucket = int(percent // 10)
        key = (song.video_id, song.download_mode, song.audio_format)
        if bucket > self._progress_buckets.get(key, -1):
            self._progress_buckets[key] = bucket
            self._record(song, "下载进度", f"{percent:.0f}%" + (f" · {speed}" if speed else ""))
        self.updated.emit(replace(song))

    def _record(self, song, event, detail=""):
        self.log_entry.emit(self._log.append(song, event, detail))

    def _stage(self, song, stage, detail=None):
        song.stage = stage
        self._record(song, "处理阶段", detail or stage)
        self.updated.emit(replace(song))

    @staticmethod
    def _media_label(config):
        return "最高画质 MV" if config.download_mode == "video" else f"音频 {config.audio_format.upper()}"
