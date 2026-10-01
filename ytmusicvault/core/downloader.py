"""Isolated bundled yt-dlp process with explicit media and network policy."""
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Optional
import psutil

from ..models.song import DownloadStatus
from ..utils.helpers import parse_ytdlp_progress
from ..utils.proxy import resolve_proxy_url

RESULT_PREFIX = "__YTMV_FILE__:"


def ytdlp_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def hidden_process_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def download_error(lines):
    # Classify instead of displaying raw stderr: URLs, cookies and proxy passwords
    # may appear in yt-dlp diagnostics.
    text = "\n".join(lines).lower()
    if "proxy" in text or "connection refused" in text or "10061" in text:
        return "代理连接失败，请检查系统代理是否运行，或在设置中选择正确的代理模式。"
    if "ffmpeg" in text or "ffprobe" in text:
        return "未找到可用的 FFmpeg / ffprobe；合并最高画质视频需要它们。"
    if "sign in" in text or "cookies" in text or "403" in text:
        return "YouTube 拒绝下载，请更新登录会话；仍失败时检查网络和 yt-dlp 版本。"
    if "javascript" in text or "challenge" in text or "ejs" in text:
        return "YouTube JavaScript 验证失败，请检查 Deno / Node.js 和 yt-dlp 的配套依赖。"
    if "requested format" in text:
        return "当前视频没有可用的目标音视频格式；可能受登录或地区限制。"
    if "timed out" in text or "timeout" in text:
        return "下载连接超时，请检查系统代理和网络。"
    return "yt-dlp 下载失败，请检查网络、登录会话和下载工具依赖。"


class Downloader:
    MAX_IDLE_SECONDS = 90

    def __init__(self, download_dir, audio_quality="best",
                 filename_template="{artist} - {title}.{ext}", cookies_path="",
                 browser_cookie_source="none", proxy_url=None, download_mode="video", audio_format="m4a"):
        self._download_dir = download_dir
        self._audio_quality = audio_quality
        self._filename_template = filename_template
        self._cookies_path = cookies_path
        self._proxy_url = proxy_url
        self._mode = download_mode
        self._audio_format = audio_format if audio_format in ("flac", "mp3", "m4a") else "mp3"
        self._process = None
        self._cancelled = threading.Event()
        self._stalled = threading.Event()

    def download(self, song, progress_callback: Optional[Callable] = None,
                 status_callback: Optional[Callable] = None, cancel_event=None,
                 event_callback: Optional[Callable] = None):
        if self._cancelled.is_set() or (cancel_event and cancel_event.is_set()):
            return False
        song.error_msg = ""
        self._stalled.clear()
        watchdog_stop = threading.Event()
        watchdog_thread = None
        try:
            if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
                song.error_msg = "请安装 FFmpeg / ffprobe 并加入 PATH；最高画质视频需要合并音视频。"
                return False
            folder = Path(self._download_dir) / ("MV" if self._mode == "video" else "Audio")
            folder.mkdir(parents=True, exist_ok=True)
            target_id = song.download_video_id or song.video_id
            url = f"https://www.youtube.com/watch?v={target_id}"
            cmd = self._build_command(url, self._build_output_template(str(folder)))
            if event_callback:
                event_callback("正在请求视频信息")
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", **hidden_process_options())
            last_output = [time.monotonic()]
            process = self._process

            def watchdog():
                while not watchdog_stop.wait(1):
                    if process.poll() is not None:
                        return
                    # Reading stdout may block during extraction or FFmpeg. An
                    # external cancellation event must still stop the process.
                    if self._cancelled.is_set() or (cancel_event and cancel_event.is_set()):
                        self._stop_process(process)
                        return
                    if time.monotonic() - last_output[0] >= self.MAX_IDLE_SECONDS:
                        self._stalled.set()
                        self._stop_process(process)
                        return

            watchdog_thread = threading.Thread(target=watchdog, daemon=True)
            watchdog_thread.start()
            if self._cancelled.is_set() or (cancel_event and cancel_event.is_set()):
                self.cancel()
            if status_callback:
                status_callback(DownloadStatus.DOWNLOADING)
            output = deque(maxlen=100)
            result = None
            last_stage = "正在解析视频信息"
            for line in self._process.stdout:
                last_output[0] = time.monotonic()
                if self._cancelled.is_set() or (cancel_event and cancel_event.is_set()):
                    self.cancel()
                    break
                line = line.strip()
                output.append(line)
                if line.startswith(RESULT_PREFIX):
                    result = line[len(RESULT_PREFIX):].strip()
                stage = _download_stage(line, self._audio_format, self._mode)
                if stage and stage != last_stage:
                    last_stage = stage
                    if event_callback:
                        event_callback(stage)
                if "[download]" in line and "%" in line and progress_callback:
                    info = parse_ytdlp_progress(line)
                    progress_callback(info["percent"], info["speed"], info["eta"])
            self._process.wait()
            if self._cancelled.is_set() or (cancel_event and cancel_event.is_set()):
                if status_callback:
                    status_callback(DownloadStatus.PAUSED)
                return False
            if self._stalled.is_set():
                song.error_msg = ("YouTube 视频解析超过 90 秒无响应；请优先安装 Deno，"
                                  "或更新 yt-dlp / JS 验证组件后重试。")
                if status_callback:
                    status_callback(DownloadStatus.FAILED)
                return False
            if self._process.returncode == 0 and result and Path(result).is_file():
                song.file_path = str(Path(result).resolve())
                song.progress = 100
                if event_callback:
                    event_callback("媒体文件已下载，准备写入标签")
                return True
            song.error_msg = download_error(output)
        except Exception:
            song.error_msg = "下载进程启动或文件操作失败，请检查输出目录、yt-dlp 和 FFmpeg。"
        finally:
            watchdog_stop.set()
            if self._process:
                if self._process.poll() is None:
                    self._stop_process(self._process)
                self._process.wait()
                if self._process.stdout:
                    self._process.stdout.close()
                self._process = None
            if watchdog_thread:
                watchdog_thread.join()
        if status_callback:
            status_callback(DownloadStatus.FAILED)
        return False

    def cancel(self):
        self._cancelled.set()
        process = self._process
        if process and process.poll() is None:
            self._stop_process(process)

    @staticmethod
    def _stop_process(process):
        try:
            root = psutil.Process(process.pid)
            descendants = root.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            descendants = []
        # The frozen Windows CLI has an outer PyInstaller process and an inner
        # Python worker. Stopping only the outer PID leaves the worker running.
        for child in reversed(descendants):
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if descendants:
            psutil.wait_procs(descendants, timeout=5)
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    def _build_command(self, url, output_template):
        cmd = ytdlp_command() + [
            "--ignore-config", "--no-simulate", "--no-playlist",
            "--newline", "--progress", "--encoding", "utf-8",
            "--socket-timeout", "30", "--retries", "3", "--fragment-retries", "3",
            "--windows-filenames", "--no-overwrites", "-o", output_template,
            "--embed-metadata", "--no-embed-info-json",
            "--print", f"after_move:{RESULT_PREFIX}%(filepath)s",
        ]
        if self._mode == "video":
            # No extension/codec/resolution cap. MKV preserves the best available
            # video and audio streams without lossy re-encoding.
            cmd += ["-f", "bv*+ba/b", "-S", "res,fps",
                    "--merge-output-format", "mkv", "--remux-video", "mkv",
                    "--embed-thumbnail"]
        else:
            cmd += ["-f", "bestaudio/best", "--extract-audio", "--audio-format", self._audio_format,
                    "--audio-quality", {"128": "128K", "256": "256K"}.get(self._audio_quality, "0")]
        if self._cookies_path and os.path.isfile(self._cookies_path):
            cmd += ["--cookies", self._cookies_path]
        # None follows environment and Windows static system proxy; "" forces
        # direct. --ignore-config prevents external yt-dlp config overriding us.
        if self._proxy_url is not None:
            cmd += ["--proxy", resolve_proxy_url(self._proxy_url)]
        for runtime in ("deno", "node"):
            executable = shutil.which(runtime)
            if executable:
                cmd += ["--js-runtimes", f"{runtime}:{Path(executable).resolve()}"]
                break
        cmd.append(url)
        return cmd

    def _build_output_template(self, base_dir):
        template = self._filename_template
        for field, value in {
            "artist": "%(artist,uploader|Unknown Artist)s", "title": "%(title)s",
            "album": "%(album|Unknown Album)s", "track": "%(track_number|0)s",
            "ext": "%(ext)s",
        }.items():
            template = template.replace("{" + field + "}", value)
        # Identity suffix prevents different recordings with identical titles
        # being mistaken for an already downloaded file.
        template = re.sub(r"\.%\(ext\)s$", "", template)
        template += " [%(id)s].%(ext)s"
        # Folder names are literal, even when a playlist contains yt-dlp's
        # percent syntax. Only the filename itself is an output template.
        return os.path.join(str(base_dir).replace("%", "%%"), template)


def _download_stage(line, audio_format, mode):
    text = line.casefold()
    if "solving" in text or "javascript challenge" in text or "challenge" in text:
        return "正在处理 YouTube 验证"
    if "downloading webpage" in text or "downloading api json" in text:
        return "正在获取视频信息"
    if "destination:" in text or ("[download]" in text and "100%" not in text and "%" not in text):
        return "正在下载视频流" if mode == "video" else "正在下载音频流"
    if "merging formats" in text or "merging" in text:
        return "正在合并音视频"
    if "remux" in text:
        return "正在封装视频容器"
    if "extractaudio" in text or "extracting audio" in text:
        return f"正在转换为 {audio_format.upper()}"
    if "embedding" in text or "thumbnail" in text:
        return "正在写入封面与媒体信息"
    return ""
