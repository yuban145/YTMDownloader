"""One place for live download jobs and durable completed-file history."""
from dataclasses import replace
import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMenu, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget, QPlainTextEdit)

from ..models.song import DownloadStatus


STATUS_LABELS = {
    DownloadStatus.PENDING: "排队中", DownloadStatus.DOWNLOADING: "下载中",
    DownloadStatus.COMPLETED: "已完成", DownloadStatus.FAILED: "失败",
    DownloadStatus.PAUSED: "已取消", DownloadStatus.SKIPPED: "已跳过",
}


class DownloadPage(QWidget):
    cancel_requested = Signal()
    retry_requested = Signal(object)
    refresh_requested = Signal()
    open_local_requested = Signal(str)
    open_source_requested = Signal(str)
    open_log_requested = Signal(str)

    def __init__(self, parent=None, log_path=None):
        super().__init__(parent)
        self.log_path = Path(log_path) if log_path else None
        self._tasks = {}
        self._task_keys = []
        self._records = []
        self._running = False
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("下载管理"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标题、作者或文件名")
        self.search.textChanged.connect(self._filter)
        heading.addWidget(self.search, 1)
        refresh = QPushButton("刷新记录")
        refresh.clicked.connect(self.refresh_requested)
        heading.addWidget(refresh)
        layout.addLayout(heading)
        self.tabs = QTabWidget()
        self.tasks = self._table(["标题", "作者", "类型", "进度", "状态"])
        self.history = self._table(["标题", "作者", "类型", "下载时间", "文件状态"])
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(4000)
        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        log_toolbar = QHBoxLayout()
        log_toolbar.addWidget(QLabel("下载过程会自动记录在本地；日志不包含 Cookie 或原始网络响应。"), 1)
        self.open_log_button = QPushButton("打开日志文件")
        self.open_log_button.setEnabled(bool(self.log_path))
        self.open_log_button.clicked.connect(self._open_log)
        log_toolbar.addWidget(self.open_log_button)
        log_layout.addLayout(log_toolbar)
        log_layout.addWidget(self.log_view, 1)
        self.tabs.addTab(self.tasks, "本次任务 (0)")
        self.tabs.addTab(self.history, "已下载 (0)")
        self.tabs.addTab(log_page, "日志")
        layout.addWidget(self.tabs, 1)
        self.tasks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tasks.customContextMenuRequested.connect(lambda pos: self._context_menu(self.tasks, pos))
        self.history.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history.customContextMenuRequested.connect(lambda pos: self._context_menu(self.history, pos))
        self.tasks.doubleClicked.connect(lambda index: self._open_row_file(self.tasks, index.row()))
        self.history.doubleClicked.connect(lambda index: self._open_row_file(self.history, index.row()))
        self.tasks.itemSelectionChanged.connect(self._selection_changed)
        bottom = QHBoxLayout()
        self.retry_button = QPushButton("重试所选失败任务")
        self.retry_button.clicked.connect(self._retry_selected)
        self.retry_button.setEnabled(False)
        bottom.addWidget(self.retry_button)
        self.cancel_button = QPushButton("取消当前批次")
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.cancel_button.setEnabled(False)
        bottom.addWidget(self.cancel_button)
        bottom.addStretch()
        layout.addLayout(bottom)

    @staticmethod
    def _table(headers):
        table = QTableWidget()
        table.setObjectName("songTable")
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, len(headers)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        return table

    @staticmethod
    def _item(value, tooltip=""):
        item = QTableWidgetItem(str(value))
        if tooltip:
            item.setToolTip(tooltip)
        return item

    def set_running(self, running):
        self._running = running
        self.cancel_button.setEnabled(running)
        self._selection_changed()

    def set_batch(self, songs):
        for song in songs:
            self.update_task(replace(song, status=DownloadStatus.PENDING, progress=0,
                                     speed="", error_msg=""))
        self.set_running(True)
        self.tabs.setCurrentIndex(0)

    def update_task(self, song):
        key = (song.video_id, song.download_mode, song.audio_format)
        self._tasks[key] = replace(song)
        if key not in self._task_keys:
            self._task_keys.append(key)
            self.tasks.setRowCount(len(self._task_keys))
        row = self._task_keys.index(key)
        media_label = ("MV" if song.download_mode == "video" else
                       f"音频 {song.audio_format.upper()}")
        progress = f"{song.progress:.0f}%" if song.status == DownloadStatus.DOWNLOADING else "—"
        if song.speed and song.status == DownloadStatus.DOWNLOADING:
            progress += f" · {song.speed}"
        values = [song.title, song.artist, media_label, progress,
                  song.stage or STATUS_LABELS.get(song.status, song.status.value)]
        for column, value in enumerate(values):
            tooltip = "\n".join(filter(None, (song.stage, song.error_msg))) if column == 4 else ""
            self.tasks.setItem(row, column, self._item(value, tooltip))
        self.tabs.setTabText(0, f"本次任务 ({len(self._task_keys)})")
        self._filter(self.search.text())
        self._selection_changed()

    def finish_batch(self, songs):
        for song in songs:
            self.update_task(song)
        self.set_running(False)

    def set_history(self, records):
        self._records = [record for record in records if record[8] == "completed"]
        self.history.setRowCount(len(self._records))
        for row, record in enumerate(self._records):
            path = Path(record[5]) if record[5] else None
            media_type = record[9]
            media_label = ("MV" if media_type == "video" else
                           f"音频 {media_type.removeprefix('audio_').upper()}" if media_type.startswith("audio_") else "音频")
            values = [record[1] or record[0], record[2] or "", media_label,
                      (record[7] or "").replace("T", " ")[:19],
                      "已保存" if path and path.is_file() else "文件不存在"]
            for column, value in enumerate(values):
                self.history.setItem(row, column, self._item(value,
                    (record[5] or "") if column == 4 else ""))
        self.tabs.setTabText(1, f"已下载 ({len(self._records)})")
        self._filter(self.search.text())

    def load_log_file(self):
        if not self.log_path:
            return
        for path in (self.log_path.with_suffix(self.log_path.suffix + ".1"), self.log_path):
            if not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-3000:]
            except OSError:
                continue
            for line in lines:
                try:
                    self.append_log(json.loads(line))
                except (ValueError, TypeError):
                    self.log_view.appendPlainText(line)

    def append_log(self, entry):
        if isinstance(entry, dict):
            text = " · ".join(str(entry.get(key, "")) for key in ("time", "title", "event", "detail") if entry.get(key))
        else:
            text = str(entry)
        if text:
            self.log_view.appendPlainText(text)

    def _open_log(self):
        if self.log_path:
            self.open_log_requested.emit(str(self.log_path))

    def _open_row_file(self, table, row):
        if row < 0:
            return
        if table is self.tasks:
            if row >= len(self._task_keys):
                return
            path = self._tasks[self._task_keys[row]].file_path
        else:
            if row >= len(self._records):
                return
            path = self._records[row][5]
        if path and Path(path).is_file():
            self.open_local_requested.emit(path)

    def _filter(self, query):
        text = query.strip().casefold()
        for row, key in enumerate(self._task_keys):
            song = self._tasks[key]
            self.tasks.setRowHidden(row, bool(text and text not in
                " ".join((song.title, song.artist, song.file_path)).casefold()))
        for row, record in enumerate(self._records):
            self.history.setRowHidden(row, bool(text and text not in
                " ".join((record[1] or "", record[2] or "", record[5] or "")).casefold()))

    def _selection_changed(self):
        row = self.tasks.currentRow()
        song = self._tasks.get(self._task_keys[row]) if 0 <= row < len(self._task_keys) else None
        self.retry_button.setEnabled(bool(song and not self._running and
                                          song.status in (DownloadStatus.FAILED, DownloadStatus.PAUSED)))

    def _retry_selected(self):
        row = self.tasks.currentRow()
        if 0 <= row < len(self._task_keys):
            song = self._tasks[self._task_keys[row]]
            if not self._running and song.status in (DownloadStatus.FAILED, DownloadStatus.PAUSED):
                self.retry_requested.emit(replace(song))

    def _context_menu(self, table, pos):
        row = table.rowAt(pos.y())
        if row < 0:
            return
        if table is self.tasks:
            song = self._tasks[self._task_keys[row]]
            path, source_id = song.file_path, song.download_video_id or song.video_id
        else:
            record = self._records[row]
            path, source_id = record[5], record[10] or record[0]
        menu = QMenu(self)
        local = menu.addAction("打开本地文件")
        local.setEnabled(bool(path and Path(path).is_file()))
        source = menu.addAction("打开源页面")
        selected = menu.exec(table.viewport().mapToGlobal(pos))
        if selected is local:
            self.open_local_requested.emit(path)
        elif selected is source:
            self.open_source_requested.emit(source_id)
