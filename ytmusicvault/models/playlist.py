"""播放列表数据模型

Playlist 是 Song 的容器，代表 YouTube Music 中的一个播放列表。
is_liked 标志区分普通播放列表和"我喜欢"自动播放列表。
"""

from dataclasses import dataclass, field
from typing import List

from .song import Song


@dataclass
class Playlist:
    """代表 YouTube Music 中的一个播放列表。
    
    设计说明：
      - songs 字段默认使用空 list，通过 field(default_factory=list) 避免
        dataclass 中可变默认值的经典陷阱
      - is_liked=True 表示这是"我喜欢"自动播放列表（每个 YTM 账号必有）
      - count 是 YouTube Music 报告的歌曲总数，可能与实际加载数量不同
    """

    playlist_id: str              # YouTube Music 播放列表 ID（如 "PLxxxxxx"）
    title: str                    # 播放列表标题
    description: str = ""         # 播放列表描述
    count: int = 0                # YouTube Music 报告的歌曲数量
    thumbnail: str = ""           # 封面缩略图 URL
    is_liked: bool = False        # 是否为"我喜欢"特殊播放列表
    songs: List[Song] = field(default_factory=list)  # 播放列表中的歌曲（延迟加载）
