"""侧边栏组件 — 显示播放列表列表和"我喜欢"快捷入口。

使用 QListWidget 实现：
  - 第一项固定为"❤️ 我喜欢"（特殊标记 __liked__）
  - 后续项为用户的播放列表
  - 选中项通过 liked_selected / playlist_selected 信号通知 MainWindow

数据流：
  MainWindow._load_library() → sidebar.set_playlists(playlists) → 填充列表
  用户点击项 → signal → MainWindow._on_playlist_selected / _on_liked_selected
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QLabel,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont, QIcon

from ..models.playlist import Playlist


class Sidebar(QWidget):
    """左侧播放列表侧边栏。

    信号：
      playlist_selected(playlist_id, playlist_title) — 选中了一个播放列表
      liked_selected() — 选中了"我喜欢"
    """

    # PySide6 信号定义（类属性）
    playlist_selected = Signal(str, str)  # playlist_id, playlist_title
    liked_selected = Signal()             # 无参数

    def __init__(self, parent=None):
        """初始化侧边栏。"""
        super().__init__(parent)
        self.setObjectName("sidebar")  # CSS 选择器 #sidebar
        self._playlists: list[Playlist] = []
        self._setup_ui()

    def _setup_ui(self):
        """构建侧边栏 UI 布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题标签
        title = QLabel("📁  音乐库")
        title.setObjectName("sidebarTitle")  # CSS 选择器 #sidebarTitle
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        layout.addWidget(title)

        # "我喜欢" 特殊项 — 排在第一项
        self._liked_item = QListWidgetItem("❤️  我喜欢")
        # UserRole 存储特殊标记 __liked__，用于区分普通播放列表
        self._liked_item.setData(Qt.ItemDataRole.UserRole, "__liked__")

        # 播放列表控件
        self._list = QListWidget()
        self._list.setIconSize(self._list.iconSize())
        self._list.addItem(self._liked_item)  # 添加"我喜欢"到列表顶部
        # 选项变更信号 → 触发加载
        self._list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list)

        # 默认选中"我喜欢"
        self._list.setCurrentRow(0)

    def set_playlists(self, playlists: list[Playlist]):
        """用播放列表数据填充侧边栏。

        Args:
            playlists: Playlist 对象列表
        """
        self._playlists = playlists
        # 清除现有播放列表项（保留第一项"我喜欢"）
        while self._list.count() > 1:
            self._list.takeItem(1)  # takeItem 移除但不删除

        for pl in playlists:
            # 构造显示文本：播放列表名 + 歌曲数
            item = QListWidgetItem(f"🎵  {pl.title}")
            if pl.count > 0:
                item.setText(f"🎵  {pl.title}  ({pl.count})")
            # 存储 playlist_id 到 UserRole，供选择时读取
            item.setData(Qt.ItemDataRole.UserRole, pl.playlist_id)
            self._list.addItem(item)

    def set_liked_count(self, count: int):
        """更新"我喜欢"的歌曲数量显示。

        Args:
            count: 喜欢的歌曲数量
        """
        self._liked_item.setText(f"❤️  我喜欢  ({count})")

    def _on_item_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        """用户点击侧边栏中的某项（currentItemChanged 信号槽）。

        QListWidget 的 currentItemChanged 在选中项变化时触发，
        包括程序化选择（如 setCurrentRow）和用户点击。
        """
        if current is None:
            return
        # 从 UserRole 读取存储的 playlist_id
        playlist_id = current.data(Qt.ItemDataRole.UserRole)
        if playlist_id == "__liked__":
            # 选中"我喜欢" → 发 liked_selected 信号
            self.liked_selected.emit()
        else:
            # 选中普通播放列表 → 发 playlist_selected 信号
            # 从显示文本中提取标题（去除图标和数量后缀）
            self.playlist_selected.emit(
                playlist_id,
                current.text().replace("🎵  ", "").split("  (")[0]
            )

    def select_liked(self):
        """程序化选中"我喜欢"项（用于登出后重置等场景）。"""
        self._list.setCurrentRow(0)
