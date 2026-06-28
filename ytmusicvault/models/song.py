"""歌曲数据模型

定义 Song 数据类和 DownloadStatus 枚举，是整个下载流程的核心数据结构。
每个 Song 实例代表一首 YouTube Music 曲目，包含：
  - 静态元数据：video_id, title, artist, album, duration 等（来自 ytmusicapi）
  - 运行时状态：status, progress, speed, file_path 等（下载过程中实时更新）

设计要点：
  - 使用 @dataclass 而非 Pydantic，减少依赖，数据来源已由 ytmusicapi 校验
  - DownloadStatus 枚举覆盖完整生命周期：PENDING → DOWNLOADING → COMPLETED/FAILED/PAUSED
  - url 属性动态拼接，不存储完整 URL，节省内存
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DownloadStatus(Enum):
    """下载状态枚举 — 定义一首歌在下载流程中可能处于的所有状态。
    
    状态流转：
      PENDING → DOWNLOADING → COMPLETED（成功）
      PENDING → DOWNLOADING → FAILED（失败，可重试）
      DOWNLOADING → PAUSED（用户暂停）
      PAUSED → PENDING（恢复后重新排队）
    """
    PENDING = "pending"          # 待下载：已加入队列，等待分配线程
    DOWNLOADING = "downloading"   # 下载中：yt-dlp 正在获取音频
    COMPLETED = "completed"       # 已完成：下载成功且元数据已写入
    FAILED = "failed"             # 失败：重试次数耗尽仍未成功
    SKIPPED = "skipped"           # 跳过：已下载过，自动跳过
    PAUSED = "paused"             # 暂停：用户手动暂停


@dataclass
class Song:
    """代表 YouTube Music 中的一首歌曲。
    
    属性分为两类：
      1. 静态元数据（来自 ytmusicapi API 响应）
      2. 运行时状态（下载过程中动态变化）
    """

    # ═══════════════════════════════════════════════════════
    # 静态元数据（来自 YouTube Music API）
    # ═══════════════════════════════════════════════════════
    video_id: str                 # YouTube 视频 ID（11 位字符，唯一标识）
    title: str                    # 歌曲标题
    artist: str = ""              # 艺术家（多人用 ", " 分隔）
    album: str = ""               # 专辑名称
    duration: int = 0             # 时长（秒）
    duration_str: str = ""        # 时长（格式化字符串，如 "3:45"）
    thumbnail: str = ""           # 封面缩略图 URL（最高分辨率）
    track_number: int = 0         # 在专辑中的曲目编号
    year: int = 0                 # 发行年份

    # ═══════════════════════════════════════════════════════
    # 运行时状态（下载过程中动态更新，跨线程共享）
    # ⚠️ 这些属性会被后台线程修改，主线程通过 Signal 安全读取
    # ═══════════════════════════════════════════════════════
    status: DownloadStatus = DownloadStatus.PENDING  # 当前下载状态
    progress: float = 0.0         # 下载进度 0.0 ~ 100.0
    speed: str = ""               # 下载速度（如 "2.3MiB/s"）
    file_path: str = ""           # 下载完成后本地文件路径
    error_msg: str = ""           # 失败时的错误信息
    retry_count: int = 0          # 已重试次数

    # ═══════════════════════════════════════════════════════
    # 计算属性
    # ═══════════════════════════════════════════════════════

    @property
    def is_downloaded(self) -> bool:
        """是否已下载完成。用于快速筛选，避免重复下载。"""
        return self.status == DownloadStatus.COMPLETED

    @property
    def url(self) -> str:
        """拼接 YouTube Music 歌曲页面 URL。
        
        动态生成而非存储，因为 video_id 已足够唯一标识。
        yt-dlp 使用此 URL 作为下载目标。
        """
        return f"https://music.youtube.com/watch?v={self.video_id}"

    @property
    def filename_safe_artist(self) -> str:
        """文件名安全的艺术家名称（去除非法字符）。
        
        用于生成下载文件名，防止因特殊字符导致路径错误。
        """
        return _sanitize(self.artist or "Unknown Artist")

    @property
    def filename_safe_title(self) -> str:
        """文件名安全的歌曲标题（去除非法字符）。
        
        用于生成下载文件名，防止因特殊字符导致路径错误。
        """
        return _sanitize(self.title or "Unknown Title")


def _sanitize(name: str) -> str:
    """移除文件名中的非法字符。
    
    Windows/Mac/Linux 共同禁止的字符：< > : " / \ | ? *
    这些字符在文件名中出现会导致文件创建失败。
    
    Args:
        name: 原始名称
    Returns:
        替换非法字符为 _ 后的安全名称
    """
    unsafe = '<>:"/\\|?*'
    for ch in unsafe:
        name = name.replace(ch, "_")
    return name.strip()
