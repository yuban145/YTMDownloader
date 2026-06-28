"""YouTube Music API 客户端封装

对 ytmusicapi 库的薄封装层，职责：
  1. 调用 ytmusicapi 的 API 方法（get_liked_songs, get_playlist 等）
  2. 将 ytmusicapi 的复杂嵌套字典响应解析为 Song/Playlist 数据类
  3. 处理 YouTube Music API 的两种数据格式（flat string 和 runs[] 嵌套结构）

数据格式说明：
  YouTube Music API 的字段可能是：
    - 简单字符串：{"title": "Bohemian Rhapsody"}
    - runs[] 嵌套：{"title": {"runs": [{"text": "Bohemian Rhapsody"}]}}
  本模块统一处理这两种格式。
"""

from typing import List, Optional

from ytmusicapi import YTMusic

from ..models.song import Song
from ..models.playlist import Playlist
from ..utils.helpers import format_duration


class YtmClient:
    """封装 ytmusicapi，提供类型安全的 Song/Playlist 返回。
    
    所有公共方法返回 Song 或 Playlist 对象列表，
    而非原始的 dict 嵌套结构，隔离了 API 响应格式变化。
    """

    def __init__(self, ytm: YTMusic):
        """注入已认证的 YTMusic 实例。
        
        Args:
            ytm: 已通过 AuthManager.login() 创建的 YTMusic 实例
        """
        self._ytm = ytm

    # ── "我喜欢" 歌曲 ─────────────────────────────────────

    def get_liked_songs(self, limit: int = 5000) -> List[Song]:
        """获取用户"我喜欢"（点赞）的所有歌曲。
        
        limit=5000 是 ytmusicapi 的默认上限，覆盖绝大多数用户的收藏量。
        
        Returns:
            Song 对象列表（已解析，可直接显示/下载）
        """
        # ytmusicapi 返回 {"tracks": [...]} 结构
        raw = self._ytm.get_liked_songs(limit=limit)
        songs = []
        if "tracks" in raw:
            for track in raw["tracks"]:
                song = self._parse_track(track)
                if song:
                    songs.append(song)
        return songs

    # ── 用户播放列表 ──────────────────────────────────────

    def get_playlists(self) -> List[Playlist]:
        """获取用户创建和收藏的所有播放列表。
        
        注：此方法只返回播放列表元数据（标题、数量等），
        不包含歌曲列表。歌曲通过 get_playlist_songs() 按需加载。
        
        Returns:
            Playlist 对象列表（songs 字段为空）
        """
        raw = self._ytm.get_library_playlists(limit=100)
        playlists = []
        for item in raw:
            playlist = Playlist(
                playlist_id=item.get("playlistId", ""),
                title=item.get("title", "Untitled"),
                description=item.get("description", ""),
                count=int(item.get("count", 0)),
                # 选择最高分辨率缩略图
                thumbnail=_best_thumbnail(item.get("thumbnails", [])),
            )
            playlists.append(playlist)
        return playlists

    # ── 播放列表内容 ──────────────────────────────────────

    def get_playlist_songs(self, playlist_id: str) -> List[Song]:
        """获取指定播放列表中的所有歌曲。
        
        与 get_playlists() 分离的设计原因：
          用户可能有很多播放列表，但每次只查看一个。
          按需加载避免启动时加载全部歌曲导致 UI 卡顿。
        
        Args:
            playlist_id: YouTube Music 播放列表 ID
        Returns:
            Song 对象列表
        """
        raw = self._ytm.get_playlist(playlist_id=playlist_id, limit=5000)
        songs = []
        if "tracks" in raw:
            for track in raw["tracks"]:
                song = self._parse_track(track)
                if song:
                    songs.append(song)
        return songs

    # ── 搜索 ──────────────────────────────────────────────

    def search(self, query: str, limit: int = 20) -> List[Song]:
        """在 YouTube Music 中搜索歌曲。
        
        filter="songs" 确保只返回歌曲结果（不含视频、专辑、艺人等）。
        
        Args:
            query: 搜索关键词
            limit: 返回结果数量上限
        Returns:
            匹配的 Song 对象列表
        """
        raw = self._ytm.search(query=query, filter="songs", limit=limit)
        songs = []
        for item in raw:
            # resultType 过滤：只保留 "song" 类型的结果
            if item.get("resultType") == "song":
                song = self._parse_track(item)
                if song:
                    songs.append(song)
        return songs

    # ── 解析引擎 ──────────────────────────────────────────

    def _parse_track(self, raw: dict) -> Optional[Song]:
        """将 ytmusicapi 的原始 track 字典解析为 Song 对象。
        
        这是整个模块最核心的方法，负责处理：
          1. 两种标题/艺术家格式（flat string vs runs[] 嵌套）
          2. 多种时长格式（"3:45", "1:23:45"）
          3. 缺失字段的默认值处理
        
        Args:
            raw: ytmusicapi 返回的单首歌曲字典
        Returns:
            Song 对象，缺少 video_id 或解析异常时返回 None
        """
        try:
            # video_id 是必须字段，没有则无法下载
            video_id = raw.get("videoId", "")
            if not video_id:
                return None

            # 标题解析 — 兼容两种格式
            title = raw.get("title", "Unknown")
            if isinstance(title, dict):
                # runs[] 格式: {"runs": [{"text": "歌名"}]}
                title = title.get("runs", [{}])[0].get("text", "Unknown")

            # 艺术家解析 — 可能有多个艺术家
            artists = []
            artist_list = raw.get("artists", [])
            for a in artist_list:
                name = a.get("name", "")
                if isinstance(name, dict):
                    # runs[] 格式兼容
                    name = name.get("runs", [{}])[0].get("text", "")
                if name:
                    artists.append(name)
            # 多个艺术家用 ", " 拼接，无艺术家时用 "Unknown Artist"
            artist = ", ".join(artists) if artists else "Unknown Artist"

            # 专辑 — 可能在 album.name 中
            album = ""
            album_data = raw.get("album", {})
            if isinstance(album_data, dict):
                album = album_data.get("name", "")

            # 时长 — 从 "mm:ss" 字符串转换为秒数
            duration_str = raw.get("duration", "0:00")
            duration_sec = _parse_duration_seconds(duration_str)

            # 缩略图 — 选择最高分辨率
            thumbnails = raw.get("thumbnails", [])
            thumbnail = _best_thumbnail(thumbnails)

            # 曲目号 — 可能是 trackNumber 或 track_number
            track_number = 0
            try:
                tn = raw.get("trackNumber") or raw.get("track_number", 0)
                if tn:
                    track_number = int(tn)
            except (ValueError, TypeError):
                pass  # 无法解析则保持 0

            # 发行年份
            year = 0
            try:
                yr = raw.get("year", 0)
                if yr:
                    year = int(yr)
            except (ValueError, TypeError):
                pass  # 无法解析则保持 0

            return Song(
                video_id=video_id,
                title=title,
                artist=artist,
                album=album,
                duration=duration_sec,
                duration_str=duration_str,
                thumbnail=thumbnail,
                track_number=track_number,
                year=year,
            )
        except Exception:
            # 单首歌曲解析失败不应影响整个列表
            # ⚠️ 审查: 建议至少记录 _log.warning 再返回 None
            return None


# ═══════════════════════════════════════════════════════════
# 模块级工具函数
# ═══════════════════════════════════════════════════════════

def _best_thumbnail(thumbnails: list) -> str:
    """从缩略图列表中选择最高分辨率的 URL。
    
    按 width × height 乘积排序，选最大的。
    
    Args:
        thumbnails: [{"url": "...", "width": 120, "height": 90}, ...]
    Returns:
        最高分辨率缩略图的 URL 字符串
    """
    if not thumbnails:
        return ""
    # max() 的 key 参数按像素总数排序
    best = max(
        thumbnails,
        key=lambda t: (t.get("width", 0) * t.get("height", 0)),
        default={}
    )
    return best.get("url", "")


def _parse_duration_seconds(dur: str) -> int:
    """将时长字符串解析为秒数。
    
    支持格式：
      "3:45"     → 225 秒 (mm:ss)
      "1:23:45"  → 5025 秒 (h:mm:ss)
      "45"       → 45 秒 (ss)
    
    Args:
        dur: 时长字符串
    Returns:
        总秒数，解析失败返回 0
    """
    if not dur:
        return 0
    parts = dur.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(parts[0])
    except (ValueError, IndexError):
        return 0
