"""下载队列管理器 — 并发控制、暂停/恢复/取消、重试逻辑。

架构设计：
  - 使用 ThreadPoolExecutor（线程池）实现并发下载
  - threading.Event 实现暂停/恢复（worker 线程在 Event.wait() 处阻塞）
  - as_completed() 按完成顺序收集中，不阻塞后续下载
  - 内置重试机制：失败后等待 retry_delay 秒重新下载，最多 max_retries 次

线程模型：
  - start() 被 _run_download_queue 后台线程调用
  - pause()/resume()/cancel() 从主线程（UI）调用
  - _download_worker() 在 ThreadPoolExecutor 的 worker 线程中执行
  - 跨线程通信通过 PySide6 Signal（线程安全）

⚠️ 已知限制：
  - cancel() 调用 shutdown(cancel_futures=True) 需要 Python 3.9+
  - _futures 字典在 cancel() 与 as_completed() 并发访问时可能抛 RuntimeError
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional

from ..models.song import Song, DownloadStatus


class QueueManager:
    """管理下载队列：并发调度、暂停恢复、取消、失败重试。
    
    使用示例：
        qm = QueueManager(max_workers=4, max_retries=3)
        qm.start(songs, download_fn=downloader.download, on_complete=callback)
        qm.pause()   # 暂停所有下载
        qm.resume()  # 恢复
        qm.cancel()  # 取消全部
    """

    def __init__(
        self,
        max_workers: int = 4,
        max_retries: int = 3,
        retry_delay: int = 5,
    ):
        """初始化队列管理器。
        
        Args:
            max_workers: 最大并发下载数（对应 ThreadPoolExecutor 的 max_workers）
            max_retries: 每首歌的最大重试次数（首次 + 重试 = max_retries 次）
            retry_delay: 失败后等待多少秒再重试
        """
        self._max_workers = max_workers
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._executor: Optional[ThreadPoolExecutor] = None  # 线程池引用
        self._futures = {}          # {Future: Song} 映射，用于追踪任务
        self._paused = False        # 暂停标志
        self._cancelled = False     # 取消标志
        self._lock = threading.Lock()  # 保护 _paused/_cancelled 的读写一致性
        # 暂停事件：set() = 不暂停（可以运行），clear() = 暂停（worker 阻塞）
        self._pause_event = threading.Event()
        self._pause_event.set()     # 初始状态：不暂停

    # ── 公共 API ──────────────────────────────────────────

    def start(
        self,
        songs: List[Song],
        download_fn: Callable[[Song], bool],
        on_progress: Optional[Callable[[Song], None]] = None,
        on_status: Optional[Callable[[Song, DownloadStatus], None]] = None,
        on_complete: Optional[Callable[[Song, bool], None]] = None,
    ):
        """启动下载队列（阻塞直到全部完成或取消）。
        
        此方法应由后台线程调用（如 _run_download_queue），
        否则会阻塞 UI 线程直到所有下载完成。
        
        Args:
            songs: 待下载的歌曲列表
            download_fn: 下载函数，签名为 (Song) -> bool
            on_progress: 进度回调 (Song)
            on_status: 状态变更回调 (Song, DownloadStatus)
            on_complete: 完成回调 (Song, bool)
        """
        # 重置状态
        self._paused = False
        self._cancelled = False
        self._pause_event.set()
        # 创建线程池（with 语句不适合此场景，因为 start() 需要阻塞等待）
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers)

        # 筛选：跳过已完成的歌曲
        pending = [s for s in songs if s.status != DownloadStatus.COMPLETED]

        # 提交所有任务到线程池
        for song in pending:
            if self._cancelled:
                break
            song.status = DownloadStatus.PENDING
            future = self._executor.submit(
                self._download_worker,
                song,
                download_fn,
                on_progress,
                on_status,
            )
            self._futures[future] = song  # 建立 Future → Song 映射

        # 按完成顺序收集结果（阻塞直到所有 future 完成）
        for future in as_completed(self._futures):
            song = self._futures[future]
            try:
                success = future.result()  # 获取 worker 返回值
                if on_complete:
                    on_complete(song, success)
            except Exception:
                if on_complete:
                    on_complete(song, False)

        # 清理：关闭线程池（wait=False 不等待未完成的任务）
        self._executor.shutdown(wait=False)
        self._executor = None
        self._futures.clear()

    def pause(self):
        """暂停所有下载。
        
        实现：清除 pause_event → worker 线程在 _pause_event.wait() 处阻塞。
        已在下载中的歌曲不会被中断（yt-dlp 进程继续），但新任务不启动。
        """
        self._paused = True
        self._pause_event.clear()  # ← 关键：让所有 worker 的 .wait() 阻塞
        for song in self._futures.values():
            if song.status == DownloadStatus.DOWNLOADING:
                song.status = DownloadStatus.PAUSED

    def resume(self):
        """恢复下载。
        
        实现：设置 pause_event → 所有阻塞的 worker 线程继续执行。
        """
        self._paused = False
        self._pause_event.set()    # ← 关键：释放所有阻塞的 .wait()
        for song in self._futures.values():
            if song.status == DownloadStatus.PAUSED:
                song.status = DownloadStatus.PENDING

    def cancel(self):
        """取消所有下载。
        
        实现：
          1. 设置取消标志 → worker 检测到后主动返回
          2. 关闭线程池并取消已提交但未开始的任务
          3. 将所有未完成歌曲标记为 PAUSED
        
        ⚠️ 注意：cancel_futures=True 需要 Python 3.9+
        """
        self._cancelled = True
        self._paused = False
        self._pause_event.set()    # 释放暂停阻塞，让 worker 能检测到 _cancelled
        if self._executor:
            # cancel_futures=True: 取消线程池中尚未开始的任务
            self._executor.shutdown(wait=False, cancel_futures=True)
        for song in self._futures.values():
            if song.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PENDING):
                song.status = DownloadStatus.PAUSED

    @property
    def is_paused(self) -> bool:
        """是否处于暂停状态。"""
        return self._paused

    @property
    def is_running(self) -> bool:
        """是否有活动的下载任务（线程池未关闭即为运行中）。"""
        return self._executor is not None

    # ── 内部 Worker ────────────────────────────────────────

    def _download_worker(
        self,
        song: Song,
        download_fn: Callable[[Song], bool],
        on_progress: Optional[Callable[[Song], None]],
        on_status: Optional[Callable[[Song, DownloadStatus], None]],
    ) -> bool:
        """Worker 线程函数 — 带暂停检测和重试逻辑。
        
        执行流程：
          1. 检查暂停事件（可能阻塞）
          2. 检查取消标志
          3. 调用 download_fn 执行实际下载
          4. 失败时等待 retry_delay 秒后重试（最多 max_retries 次）
        
        Returns:
            True 下载成功，False 所有重试均失败
        """
        # 首次进入时检查暂停
        self._pause_event.wait()  # 如果暂停，这里会阻塞直到 resume() 被调用
        if self._cancelled:
            return False

        # 重试循环
        for attempt in range(1, self._max_retries + 1):
            if self._cancelled:
                return False
            # 每次重试前检查暂停
            self._pause_event.wait()

            song.retry_count = attempt
            song.status = DownloadStatus.DOWNLOADING
            if on_status:
                on_status(song, DownloadStatus.DOWNLOADING)

            try:
                success = download_fn(song)
                if success:
                    song.status = DownloadStatus.COMPLETED
                    if on_status:
                        on_status(song, DownloadStatus.COMPLETED)
                    return True
                else:
                    # 下载函数返回 False（非异常失败，如 yt-dlp 返回非 0）
                    song.status = DownloadStatus.FAILED
                    if attempt < self._max_retries:
                        time.sleep(self._retry_delay)  # 等待后重试
            except Exception as e:
                # 下载函数抛异常
                song.error_msg = str(e)
                song.status = DownloadStatus.FAILED
                if attempt < self._max_retries:
                    time.sleep(self._retry_delay)  # 等待后重试

        # 所有重试耗尽
        song.status = DownloadStatus.FAILED
        if on_status:
            on_status(song, DownloadStatus.FAILED)
        return False
