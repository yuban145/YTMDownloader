"""Playlist navigation; titles and identifiers never derived from display text."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QLabel
from PySide6.QtCore import Signal, Qt, QSignalBlocker


class Sidebar(QWidget):
    playlist_selected = Signal(str, str)
    liked_selected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("音乐库"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("筛选播放列表")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self._list = QListWidget()
        layout.addWidget(self._list)
        self._list.currentItemChanged.connect(self._changed)
        self.set_playlists([])

    def set_playlists(self, playlists):
        current = self._list.currentItem()
        selected = current.data(Qt.ItemDataRole.UserRole) if current else "LM"
        with QSignalBlocker(self._list):
            self._list.clear()
            self._liked_item = QListWidgetItem("我喜欢")
            self._liked_item.setData(Qt.ItemDataRole.UserRole, "LM")
            self._liked_item.setData(Qt.ItemDataRole.UserRole + 1, "我喜欢")
            self._list.addItem(self._liked_item)
            for playlist in playlists:
                suffix = f" · {playlist.count} 首" if playlist.count else ""
                item = QListWidgetItem(playlist.title + suffix)
                item.setData(Qt.ItemDataRole.UserRole, playlist.playlist_id)
                item.setData(Qt.ItemDataRole.UserRole + 1, playlist.title)
                item.setToolTip("我创建的歌单" if playlist.owned else "已收藏的歌单")
                self._list.addItem(item)
            self.select(selected)
        self._filter(self.search.text())

    def select(self, playlist_id):
        with QSignalBlocker(self._list):
            for row in range(self._list.count()):
                if self._list.item(row).data(Qt.ItemDataRole.UserRole) == playlist_id:
                    self._list.setCurrentRow(row)
                    return
            self._list.setCurrentRow(0)

    def set_liked_count(self, count):
        self._liked_item.setText(f"我喜欢 · {count} 首")

    def select_liked(self):
        self.select("LM")

    def _changed(self, current, previous):
        if current:
            pid = current.data(Qt.ItemDataRole.UserRole)
            if pid == "LM":
                self.liked_selected.emit()
            else:
                self.playlist_selected.emit(pid, current.data(Qt.ItemDataRole.UserRole + 1))

    def _filter(self, text):
        for row in range(self._list.count()):
            item = self._list.item(row)
            item.setHidden(row != 0 and text.casefold() not in item.text().casefold())
