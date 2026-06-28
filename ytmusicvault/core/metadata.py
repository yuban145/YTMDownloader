"""元数据写入模块 — 将歌曲信息和封面图嵌入 M4A 音频文件。

使用 mutagen 库操作 MPEG-4 原子标签（QuickTime metadata atoms）。

M4A 标签键说明（Apple 定义的 iTunes-style 四字符码）：
  ©nam = 标题    ©ART = 艺术家    ©alb = 专辑
  aART = 专辑艺术家    trkn = 曲目编号    ©day = 年份
  covr = 封面图（JPEG/PNG 二进制）

封面下载策略：
  1. 先尝试高清 URL（w1200），超时 15s
  2. 失败时回退原始 URL，超时 10s
  3. 限制最大 5MB，防止异常大文件
"""

import os
import re
import tempfile
from typing import Optional
from urllib import request

from mutagen.mp4 import MP4, MP4Cover, MP4Tags

from ..models.song import Song


class MetadataWriter:
    """向 M4A 音频文件写入元数据标签和封面图。
    
    在下载完成后调用（main_window._run_download_queue > on_complete）。
    写入失败不会阻塞后续下载——返回 False 仅记录日志。
    """

    def write(self, song: Song, file_path: Optional[str] = None) -> bool:
        """将歌曲元数据写入 M4A 文件。
        
        Args:
            song: 包含完整元数据的 Song 对象
            file_path: 音频文件路径。为 None 时使用 song.file_path
        Returns:
            True 写入成功，False 写入失败
        """
        path = file_path or song.file_path
        if not path or not os.path.exists(path):
            return False

        try:
            # 打开 M4A 文件（mutagen 自动解析 MPEG-4 容器结构）
            audio = MP4(path)

            # ── 基础标签 ──────────────────────────────────
            # ©nam (0xa96e616d): Title
            audio.tags["\xa9nam"] = song.title
            # ©ART (0xa9415254): Artist
            audio.tags["\xa9ART"] = song.artist
            if song.album:
                # ©alb (0xa9616c62): Album
                audio.tags["\xa9alb"] = song.album
            if song.artist:
                # aART (0x61415254): Album Artist（合辑中可能与 Artist 不同）
                audio.tags["aART"] = song.artist

            # ── 曲目号 ───────────────────────────────────
            # trkn: [(track_number, total_tracks)]
            # total_tracks 设为 0 表示未知
            if song.track_number > 0:
                audio.tags["trkn"] = [(song.track_number, 0)]

            # ── 年份 ─────────────────────────────────────
            # ©day: 发行日期（字符串格式，如 "2024"）
            if song.year > 0:
                audio.tags["\xa9day"] = str(song.year)

            # ── 封面图 ───────────────────────────────────
            if song.thumbnail:
                cover_data = self._download_cover(song.thumbnail)
                if cover_data:
                    # 根据 URL 后缀判断图片格式
                    fmt = MP4Cover.FORMAT_JPEG   # 默认 JPEG
                    if song.thumbnail.lower().endswith(".png"):
                        fmt = MP4Cover.FORMAT_PNG
                    # covr: 封面图列表（M4A 可存储多张）
                    audio.tags["covr"] = [MP4Cover(cover_data, imageformat=fmt)]

            # 保存所有标签到文件
            audio.save()
            return True

        except Exception:
            # 元数据写入失败不应影响下载流程
            return False

    # ── 封面下载 ────────────────────────────────────────

    def _download_cover(self, url: str) -> Optional[bytes]:
        """从 URL 下载封面图片。
        
        两步策略：
          1. 尝试升级到高清 URL（w1200）下载
          2. 失败时用原始 URL 重试
        
        Args:
            url: YouTube 缩略图 URL（通常为低分辨率）
        Returns:
            图片二进制数据，下载失败或超过 5MB 时返回 None
        """
        try:
            # 尝试升级缩略图分辨率：=w60-h60 → =w1200-h1200
            high_res_url = url
            if "=w" in url:
                high_res_url = _upgrade_thumbnail_url(url)

            # 带 User-Agent 的请求（YouTube 可能对无 UA 的请求限流）
            req = request.Request(
                high_res_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36"
                    ),
                },
            )
            with request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                # 限制最大 5MB，防止异常大图占用内存
                if len(data) > 5 * 1024 * 1024:
                    return None
                return data
        except Exception:
            # 回退：用原始 URL 再试一次
            try:
                req2 = request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with request.urlopen(req2, timeout=10) as resp:
                    return resp.read()
            except Exception:
                return None


def _upgrade_thumbnail_url(url: str) -> str:
    """将 YouTube 缩略图 URL 升级为高分辨率版本。
    
    YouTube 缩略图 URL 模式：
      =w60-h60-l90-rj  → =w1200-h1200-l90-rj  （带宽高）
      =w60             → =w1200                 （仅宽度）
    
    1200px 是 YouTube 提供的最大缩略图尺寸。
    """
    # 先替换带高度的模式：=w<数字>-h<数字>
    url = re.sub(r"=w\d+-h\d+", "=w1200-h1200", url)
    # 再替换仅宽度的模式：=w<数字>
    url = re.sub(r"=w\d+", "=w1200", url)
    return url
