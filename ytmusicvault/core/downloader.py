"""下载引擎 — 通过子进程调用 yt-dlp 实现音频下载。

架构决策：为什么用子进程而非 yt-dlp Python API？
  1. yt-dlp 的 Python API 不稳定/文档不全，CLI 参数更稳定
  2. 子进程隔离崩溃：yt-dlp 挂了不会拖垮主进程
  3. 逐行解析 stdout → 实时进度反馈
  4. subprocess.Popen 的 terminate() 天然支持取消

核心流程：
  1. _build_command()     构建 yt-dlp 命令行
  2. _build_output_template() 将用户模板 {artist} 转为 yt-dlp %(artist)s
  3. subprocess.Popen()   启动下载进程
  4. 逐行读取 stdout      → 解析进度 → 回调 UI
  5. wait()               → 等待完成
  6. _find_output_file()  → 从输出中提取最终文件路径
"""

import os
import re
import subprocess
import sys
import logging
from pathlib import Path
from typing import Callable, Optional

from ..models.song import DownloadStatus
from ..utils.helpers import parse_ytdlp_progress

_log = logging.getLogger(__name__)


class Downloader:
    """封装 yt-dlp，下载 YouTube Music 音频并实时报告进度。

    设计要点：
      - 单例使用：每个 Downloader 实例同时只下载一首歌
      - _cancelled 标志 + terminate() 实现取消
      - Windows 平台通过 STARTUPINFO + CREATE_NO_WINDOW 隐藏控制台窗口
      - 支持 Cookies（认证下载）和 Proxy（代理）
    """

    def __init__(
        self,
        download_dir: str,
        audio_quality: str = "256",
        filename_template: str = "{artist} - {title}.{ext}",
        cookies_path: str = "",
        proxy_url: str = "",
    ):
        """初始化下载器。

        Args:
            download_dir: 下载输出目录
            audio_quality: 音质 — "128", "256", "best"
            filename_template: 文件名模板 — 如 "{artist} - {title}.{ext}"
            cookies_path: Netscape cookies.txt 路径（用于认证）
            proxy_url: 代理 URL（如 "http://127.0.0.1:1080"）
        """
        self._download_dir = download_dir
        self._audio_quality = audio_quality
        self._filename_template = filename_template
        self._cookies_path = cookies_path
        self._proxy_url = proxy_url
        self._process: Optional[subprocess.Popen] = None  # 当前下载进程引用
        self._cancelled = False  # 取消标志（线程安全由 GIL 保证）

    # ── 公共 API ──────────────────────────────────────────

    def download(
        self,
        song,
        progress_callback: Optional[Callable] = None,
        status_callback: Optional[Callable] = None,
    ) -> bool:
        """下载单首歌曲（同步阻塞方法，应在 worker 线程中调用）。

        执行流程：
          1. 创建输出目录
          2. 构建 yt-dlp 命令
          3. 启动子进程（隐藏控制台窗口）
          4. 逐行读取 stdout → 解析进度 → 回调 UI
          5. 等待子进程完成
          6. 从输出中找到最终文件路径
          7. 将文件路径写入 song.file_path

        Args:
            song: Song 对象（需要 video_id 和 url 属性）
            progress_callback: 进度回调 (percent: float, speed: str, eta: str)
            status_callback: 状态回调 (DownloadStatus)

        Returns:
            True 下载成功，False 失败或取消
        """
        self._cancelled = False
        output_dir = self._download_dir
        # 确保下载目录存在（exist_ok=True 静默处理已存在的情况）
        os.makedirs(output_dir, exist_ok=True)

        # 构建 yt-dlp 输出模板路径（如 D:/Music/%(artist)s - %(title)s.%(ext)s）
        output_template = self._build_output_template(output_dir)

        # 构建完整的 yt-dlp 命令行参数
        cmd = self._build_command(song.url, output_template)

        try:
            # ── Windows 控制台隐藏 ──────────────────────────
            # 防止 yt-dlp 弹出黑色 cmd 窗口（Windows 特有处理）
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                # STARTF_USESHOWWINDOW: 使用 wShowWindow 成员
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                # SW_HIDE: 隐藏窗口
                startupinfo.wShowWindow = subprocess.SW_HIDE

            # CREATE_NO_WINDOW: 不创建控制台窗口（双重保险）
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            # ── 启动 yt-dlp 子进程 ──────────────────────────
            # stderr=STDOUT: 将错误输出合并到标准输出，统一解析
            # errors="replace": 处理非 UTF-8 字符用替换符（不崩溃）
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startupinfo,
                creationflags=creationflags,
            )

            if status_callback:
                status_callback(DownloadStatus.DOWNLOADING)

            # ── 逐行读取输出 → 实时进度解析 ──────────────────
            output_lines = []
            for line in self._process.stdout:
                # 检查取消标志（由 cancel() 方法设置）
                if self._cancelled:
                    self._process.terminate()  # 发送 SIGTERM（Windows 上等效 TerminateProcess）
                    if status_callback:
                        status_callback(DownloadStatus.PAUSED)
                    return False

                line = line.strip()
                output_lines.append(line)  # 保存所有输出用于后续文件路径查找

                # 解析下载进度行：如 "[download]  45.3% of ~5.20MiB at 2.3MiB/s ETA 00:15"
                if "[download]" in line and "%" in line:
                    info = parse_ytdlp_progress(line)
                    if progress_callback:
                        progress_callback(
                            info["percent"],
                            info["speed"],
                            info["eta"],
                        )

            # ── 等待子进程完成 ──────────────────────────────
            # 不设超时：大文件在慢速网络下可能需要数分钟
            self._process.wait()

            # ── 检查下载结果 ─────────────────────────────────
            if self._process.returncode == 0:
                # 从 yt-dlp 输出中解析最终文件路径
                # yt-dlp 输出格式：[ExtractAudio] Destination: C:\\path\\to\\file.m4a
                output_file = self._find_output_file(output_lines)
                if output_file and os.path.exists(output_file):
                    song.file_path = output_file  # 写入路径，供 MetadataWriter 使用
                    if status_callback:
                        status_callback(DownloadStatus.COMPLETED)
                    return True

            # 下载失败（returncode != 0 或文件未找到）
            if status_callback:
                status_callback(DownloadStatus.FAILED)
            return False

        except Exception as e:
            # 捕获所有异常（子进程启动失败、管道读取异常等）
            song.error_msg = str(e)
            if status_callback:
                status_callback(DownloadStatus.FAILED)
            return False

    def cancel(self):
        """取消当前下载。

        设置取消标志 → 主循环检测到后调用 terminate() 杀死 yt-dlp 进程。
        poll() is None 表示进程仍在运行（否则已结束，无需终止）。
        """
        self._cancelled = True
        if self._process and self._process.poll() is None:
            self._process.terminate()

    # ── 内部辅助方法 ──────────────────────────────────────

    def _build_command(self, url: str, output_template: str) -> list:
        """构建 yt-dlp 命令行参数列表。

        yt-dlp 参数说明：
          -f bestaudio[ext=m4a]/bestaudio/best
            优先选择 M4A 音频流 → 其次任意音频流 → 最后任意格式
          --extract-audio: 从视频中提取纯音频
          --audio-format m4a: 输出 M4A 格式（AAC 编码，兼容性最好）
          --embed-metadata: 让 yt-dlp 先写入基础元数据（我们再用 mutagen 覆盖）
          --newline: 每行一条进度信息（而非 \r 覆盖刷新）
          --no-playlist: 不下载整个播放列表（只下载单曲）
          --no-overwrites: 不覆盖已存在的文件

        Args:
            url: 歌曲 URL
            output_template: yt-dlp 格式的输出模板

        Returns:
            命令行参数列表（可直接传给 subprocess.Popen）
        """
        cmd = [
            "yt-dlp",
            # ── 格式选择 ────────────────────────────────────
            "-f", "bestaudio[ext=m4a]/bestaudio/best",
            "--extract-audio",
            "--audio-format", "m4a",
            # ── 输出路径 ────────────────────────────────────
            "-o", output_template,
            # ⚠️ --no-overwrites: 如果文件已存在则跳过
            # 这可能导致"下载成功"但实际并未下载（文件已存在）
            "--no-overwrites",
            # ── 元数据 ──────────────────────────────────────
            "--embed-metadata",     # yt-dlp 写入基础标签
            # ── 进度输出 ────────────────────────────────────
            "--newline",            # 每行一条进度信息，便于解析
            "--no-playlist",        # 防止误下载整个播放列表
            "--no-warnings",        # 减少噪音输出
            "--progress",           # 显示进度信息
        ]

        # ── Cookies（认证） ──────────────────────────────────
        # yt-dlp 读取 Netscape 格式的 cookies 文件来模拟登录状态
        if self._cookies_path and os.path.exists(self._cookies_path):
            cmd.extend(["--cookies", self._cookies_path])
            _log.info(f"Using cookies from {self._cookies_path}")
        else:
            _log.debug("No cookies file — downloading without authentication")

        # ── 代理 ────────────────────────────────────────────
        # 支持 http://, socks5:// 等格式
        if self._proxy_url:
            cmd.extend(["--proxy", self._proxy_url])
            _log.info(f"Using proxy: {self._proxy_url}")

        # ── 音质 ────────────────────────────────────────────
        # "best" 不传参数（yt-dlp 默认下载最高质量）
        if self._audio_quality == "128":
            cmd.extend(["--audio-quality", "128K"])
        elif self._audio_quality == "256":
            cmd.extend(["--audio-quality", "256K"])

        cmd.append(url)  # URL 放在最后
        return cmd

    def _build_output_template(self, base_dir: str) -> str:
        """将用户友好的模板转换为 yt-dlp 格式。

        用户模板语法 → yt-dlp 输出模板语法：
          {artist} → %(artist)s
          {title}  → %(title)s
          {ext}    → %(ext)s
          {album}  → %(album)s
          {track}  → %(track_number)s

        Args:
            base_dir: 基础下载目录

        Returns:
            完整路径模板，如 "D:/Music/%(artist)s - %(title)s.%(ext)s"
        """
        template = self._filename_template
        # 逐一替换占位符（replace 方法不修改原字符串）
        template = template.replace("{artist}", "%(artist)s")
        template = template.replace("{title}", "%(title)s")
        template = template.replace("{ext}", "%(ext)s")
        template = template.replace("{album}", "%(album)s")
        template = template.replace("{track}", "%(track_number)s")
        # os.path.join 处理跨平台路径分隔符
        return os.path.join(base_dir, template)

    def _find_output_file(self, lines: list) -> Optional[str]:
        """从 yt-dlp 输出中提取最终文件路径。

        yt-dlp 在完成转码后会输出：
          [ExtractAudio] Destination: C:\\path\\to\\file.m4a
        或者：
          [download] Destination: C:\\path\\to\\file.m4a

        从最后一行开始反向搜索，因为最终目标文件出现在输出的末尾。

        ⚠️ 当前仅匹配 .m4a 扩展名。如果音频格式改为 opus/webm，需要更新正则。

        Args:
            lines: yt-dlp 的 stdout 行列表

        Returns:
            文件绝对路径，未找到时返回 None
        """
        for line in reversed(lines):
            match = re.search(
                r"Destination:\s+(.+\.m4a)",
                line,
                re.IGNORECASE,
            )
            if match:
                return match.group(1).strip()
        return None
