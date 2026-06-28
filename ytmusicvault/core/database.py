"""SQLite 数据库 — 记录下载历史，实现去重和断点续传。

设计决策：
  - 使用 SQLite 而非 JSON 文件：支持并发读写（WAL 模式）、索引查询、事务
  - check_same_thread=False：允许多线程访问（下载线程写，主线程读）
  - WAL 模式：写操作不阻塞读操作，适合"主线程读历史 + 下载线程写记录"场景
  - video_id 作为主键：YouTube video_id 全局唯一，天然适合去重

表结构：
  downloads(video_id, title, artist, album, duration, file_path, file_size, downloaded_at, status)
"""

import os
import sqlite3
from datetime import datetime
from typing import List, Optional


# SQL 建表语句 — 模块级常量，只定义一次
# IF NOT EXISTS 确保重复执行不会报错（幂等性）
DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    video_id      TEXT PRIMARY KEY,    -- YouTube 视频 ID，全局唯一标识
    title         TEXT,                -- 歌曲标题
    artist        TEXT,                -- 艺术家
    album         TEXT,                -- 专辑
    duration      INTEGER,             -- 时长（秒）
    file_path     TEXT,                -- 本地文件路径
    file_size     INTEGER,             -- 文件大小（字节）
    downloaded_at TEXT,                -- 下载完成时间（ISO 8601）
    status        TEXT DEFAULT 'completed'  -- 状态：completed / failed
);

-- video_id 索引：主键自带索引，但显式创建确保存在
CREATE INDEX IF NOT EXISTS idx_video_id ON downloads(video_id);
-- artist 索引：支持按艺术家筛选已下载歌曲
CREATE INDEX IF NOT EXISTS idx_artist ON downloads(artist);
"""


class Database:
    """管理本地 SQLite 下载历史数据库。
    
    线程安全说明：
      - SQLite 使用 WAL 模式 + check_same_thread=False
      - 多个线程同时读安全；一个写 + 多个读安全
      - 多个线程同时写可能导致 "database is locked"，但本项目中
        写入仅发生在下载完成时（ThreadPoolExecutor worker 串行回调）
    
    存储位置：%APPDATA%/YtMusicVault/downloads.db
    """

    def __init__(self, db_path: Optional[str] = None):
        """初始化数据库连接。
        
        Args:
            db_path: 数据库文件路径。为 None 时自动使用默认路径。
        
        Raises:
            sqlite3.OperationalError: 如果目录无写入权限（调用方需处理）
        """
        if db_path is None:
            import os
            from pathlib import Path
            # 默认路径：%APPDATA%/YtMusicVault/downloads.db（与 config 同目录）
            base = os.environ.get("APPDATA", str(Path.home()))
            db_path = os.path.join(base, "YtMusicVault", "downloads.db")
        
        # 确保目录存在（exist_ok=True 不会因目录已存在而报错）
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db_path = db_path
        # check_same_thread=False：允许下载线程写入，主线程读取
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        # WAL 模式：Write-Ahead Logging，写不阻塞读（SQLite 3.7.0+）
        self._conn.execute("PRAGMA journal_mode=WAL")
        # 执行建表脚本（IF NOT EXISTS 保证幂等）
        self._conn.executescript(DB_SCHEMA)
        self._conn.commit()

    # ── CRUD ────────────────────────────────────────────────

    def is_downloaded(self, video_id: str) -> bool:
        """检查某首歌是否已成功下载。
        
        用于启动时标记已下载歌曲为 COMPLETED 状态，避免重复下载。
        
        Args:
            video_id: YouTube 视频 ID
        Returns:
            True 如果下载记录存在且状态为 'completed'
        """
        row = self._conn.execute(
            "SELECT 1 FROM downloads WHERE video_id=? AND status='completed'",
            (video_id,),
        ).fetchone()
        return row is not None

    def mark_downloaded(
        self,
        video_id: str,
        title: str = "",
        artist: str = "",
        album: str = "",
        duration: int = 0,
        file_path: str = "",
        file_size: int = 0,
    ):
        """记录一次成功的下载。
        
        使用 INSERT OR REPLACE：如果 video_id 已存在则更新，不存在则插入。
        这确保了同一首歌多次下载只保留最新记录。
        """
        self._conn.execute(
            """INSERT OR REPLACE INTO downloads 
               (video_id, title, artist, album, duration, file_path, file_size, downloaded_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed')""",
            (
                video_id, title, artist, album, duration,
                file_path, file_size, datetime.now().isoformat(),
            ),
        )
        self._conn.commit()

    def mark_failed(self, video_id: str):
        """标记下载失败（用于后续重试判断）。
        
        失败记录不会阻止重新下载——只有 status='completed' 才会被跳过。
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO downloads (video_id, status) VALUES (?, 'failed')",
            (video_id,),
        )
        self._conn.commit()

    def get_downloaded_ids(self) -> List[str]:
        """获取所有已成功下载的 video_id 列表。
        
        启动时调用，转为 set 后用 O(1) 查找判断每首歌是否已下载。
        """
        rows = self._conn.execute(
            "SELECT video_id FROM downloads WHERE status='completed'"
        ).fetchall()
        return [r[0] for r in rows]

    def get_all_records(self) -> list:
        """获取所有下载记录（按时间倒序）。
        
        Returns:
            list[tuple]: 原始 SQLite 行元组，字段顺序与建表语句一致
        """
        return self._conn.execute(
            "SELECT * FROM downloads ORDER BY downloaded_at DESC"
        ).fetchall()

    def remove_record(self, video_id: str):
        """删除单条下载记录。"""
        self._conn.execute(
            "DELETE FROM downloads WHERE video_id=?",
            (video_id,),
        )
        self._conn.commit()

    def clear_all(self):
        """清空所有下载历史。"""
        self._conn.execute("DELETE FROM downloads")
        self._conn.commit()

    # ── Cleanup ─────────────────────────────────────────────

    def close(self):
        """关闭数据库连接。
        
        在应用退出时调用（MainWindow.closeEvent）。
        ⚠️ 必须先取消所有下载任务再关闭，否则 worker 线程写已关闭的连接会崩溃。
        """
        if self._conn:
            self._conn.close()
            self._conn = None
