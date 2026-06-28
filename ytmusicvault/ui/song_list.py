"""歌曲列表组件 — Qt 表格显示歌曲、支持勾选/搜索/状态展示。

核心功能：
  1. QTableWidget 展示歌曲（标题、艺术家、时长、状态）
  2. 每行带 QCheckBox 用于批量选择
  3. 全选/取消全选（三态复选框）
  4. 实时搜索过滤（标题/艺术家/专辑）
  5. 下载状态颜色标记

数据流：
  MainWindow → song_list.set_songs(songs) → 填充表格
  用户勾选 + 点击下载 → download_clicked 信号 → MainWindow._on_download_clicked
  MainWindow → song_list.update_song_status(song) → 更新单行状态
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QPushButton, QLineEdit, QLabel,
    QAbstractItemView,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor

from ..models.song import Song, DownloadStatus


class SongListWidget(QWidget):
    """歌曲表格组件 — 核心 UI 控件之一。

    信号：
      download_clicked(list[Song]) — 用户点击下载按钮
      selection_changed(int, int) — 选中数量/总数变化
    """

    download_clicked = Signal(list)  # list[Song]
    selection_changed = Signal(int, int)  # selected_count, total

    def __init__(self, parent=None):
        """初始化歌曲列表。"""
        super().__init__(parent)
        self._songs: list[Song] = []            # 全部歌曲（未过滤）
        self._filtered_songs: list[Song] = []   # 过滤后的歌曲（当前显示）
        self._checkboxes: dict[int, QCheckBox] = {}  # {行号: 复选框}
        self._setup_ui()

    def _setup_ui(self):
        """构建歌曲列表 UI 布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── 顶部工具栏 ─────────────────────────────────
        toolbar = QHBoxLayout()

        # 全选复选框（三态：全选/半选/未选）
        self._select_all_cb = QCheckBox("全选")
        self._select_all_cb.setTristate(True)  # 允许半选状态
        self._select_all_cb.stateChanged.connect(self._on_select_all)
        toolbar.addWidget(self._select_all_cb)

        toolbar.addStretch()  # 弹性空间，把搜索框推到右边

        # 搜索输入框
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍  搜索歌曲...")
        self._search_input.setMaximumWidth(300)
        # 文本变化即触发过滤（实时搜索，无需按回车）
        self._search_input.textChanged.connect(self._on_search)
        toolbar.addWidget(self._search_input)

        layout.addLayout(toolbar)

        # ── 歌曲表格 ───────────────────────────────────
        self._table = QTableWidget()
        self._table.setObjectName("songTable")  # CSS 选择器
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["", "标题", "作者", "时长", "状态"])
        self._table.setAlternatingRowColors(True)  # 交替行颜色（斑马纹）
        # 禁止用户选择单元格（选择由复选框处理）
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        # 禁止编辑单元格内容
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)  # 隐藏行号
        self._table.setShowGrid(False)  # 隐藏网格线

        # 列宽策略
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)    # 复选框列
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # 标题列（自动拉伸）
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # 艺术家列（自动拉伸）
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)    # 时长列
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)    # 状态列
        self._table.setColumnWidth(0, 40)   # 复选框
        self._table.setColumnWidth(3, 60)   # 时长
        self._table.setColumnWidth(4, 80)   # 状态

        # ⚠️ 连接了 itemChanged 但表格设为 NoEditTriggers，实际不会触发
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table)

        # ── 底部工具栏 ─────────────────────────────────
        bottom = QHBoxLayout()

        self._info_label = QLabel("共 0 首歌")
        bottom.addWidget(self._info_label)

        bottom.addStretch()

        # 取消选择按钮
        self._deselect_btn = QPushButton("取消选择")
        self._deselect_btn.setObjectName("secondaryBtn")  # CSS 选择器
        self._deselect_btn.clicked.connect(self._deselect_all)
        bottom.addWidget(self._deselect_btn)

        # 下载按钮
        self._download_btn = QPushButton("⬇ 下载选中")
        self._download_btn.clicked.connect(self._on_download_clicked)
        self._download_btn.setEnabled(False)  # 初始禁用（未勾选任何歌曲）
        bottom.addWidget(self._download_btn)

        layout.addLayout(bottom)

    # ── 公共 API ──────────────────────────────────────

    def set_songs(self, songs: list[Song]):
        """替换全部歌曲数据并刷新显示。

        Args:
            songs: Song 对象列表
        """
        self._songs = songs
        self._apply_filter()

    def update_song_status(self, song: Song):
        """更新单首歌曲的显示状态（下载进度/完成/失败）。

        由 MainWindow._on_status_updated 调用，
        频率高（每首歌每次状态变化都调用）。

        Args:
            song: 状态已更新的 Song 对象
        """
        self._update_song_row(song)

    def get_selected_songs(self) -> list[Song]:
        """获取所有已勾选的歌曲列表。

        Returns:
            勾选的 Song 对象列表
        """
        selected = []
        for row, song in enumerate(self._filtered_songs):
            cb = self._checkboxes.get(row)
            if cb and cb.isChecked():
                selected.append(song)
        return selected

    # ── 内部方法 ──────────────────────────────────────

    def _apply_filter(self, query: str = ""):
        """根据搜索关键词过滤歌曲并重建表格。

        Args:
            query: 搜索关键词（空字符串 = 不过滤）
        """
        query = query.strip().lower()
        if query:
            # 在标题、艺术家、专辑中搜索
            self._filtered_songs = [
                s for s in self._songs
                if query in s.title.lower()
                or query in s.artist.lower()
                or query in s.album.lower()
            ]
        else:
            self._filtered_songs = list(self._songs)

        self._populate_table()

    def _populate_table(self):
        """根据 _filtered_songs 重建整个表格。

        性能注意：对于大量歌曲（5000+），逐行创建 QTableWidgetItem
        可能较慢。考虑使用 QTableView + 自定义 Model 优化。
        """
        self._table.setRowCount(0)          # 清空现有行
        self._checkboxes.clear()
        self._table.setRowCount(len(self._filtered_songs))

        # 在填充期间阻止信号，避免 itemChanged 触发（性能优化）
        self._table.blockSignals(True)

        for row, song in enumerate(self._filtered_songs):
            self._create_row(row, song)

        self._table.blockSignals(False)

        self._update_info()
        # 填充后重置全选复选框
        self._select_all_cb.setCheckState(Qt.CheckState.Unchecked)

    def _create_row(self, row: int, song: Song):
        """为表格创建一行数据。

        Args:
            row: 行号
            song: Song 数据对象
        """
        # ── 列 0：复选框 ──────────────────────────────
        cb = QCheckBox()
        # lambda 捕获 row 的值（而非引用），确保回调知道是第几行
        cb.stateChanged.connect(
            lambda state, r=row: self._on_checkbox_toggled(r, state)
        )
        self._checkboxes[row] = cb
        # 将复选框嵌入 QWidget 以实现居中布局
        widget = QWidget()
        wl = QHBoxLayout(widget)
        wl.addWidget(cb)
        wl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wl.setContentsMargins(0, 0, 0, 0)
        self._table.setCellWidget(row, 0, widget)

        # ── 列 1：标题 ────────────────────────────────
        title_item = QTableWidgetItem(song.title)
        # 存储 video_id 到 UserRole，供需要时读取
        title_item.setData(Qt.ItemDataRole.UserRole, song.video_id)
        self._table.setItem(row, 1, title_item)

        # ── 列 2：艺术家 ──────────────────────────────
        self._table.setItem(row, 2, QTableWidgetItem(song.artist))

        # ── 列 3：时长 ────────────────────────────────
        self._table.setItem(row, 3, QTableWidgetItem(song.duration_str))

        # ── 列 4：状态 ────────────────────────────────
        self._set_status_cell(row, song.status)

        # 行高统一为 36px
        self._table.setRowHeight(row, 36)

    def _set_status_cell(self, row: int, status: DownloadStatus):
        """设置状态列的文本和颜色。

        使用颜色映射让不同状态一目了然：
          绿色 = 已完成，蓝色 = 下载中，红色 = 失败，黄色 = 暂停

        Args:
            row: 行号
            status: DownloadStatus 枚举值
        """
        status_map = {
            DownloadStatus.PENDING: ("⏳ 待下载", "#a6adc8"),      # 灰色
            DownloadStatus.DOWNLOADING: ("⬇ 下载中", "#89b4fa"),  # 蓝色
            DownloadStatus.COMPLETED: ("✅ 已完成", "#a6e3a1"),     # 绿色
            DownloadStatus.FAILED: ("❌ 失败", "#f38ba8"),          # 红色
            DownloadStatus.PAUSED: ("⏸ 暂停", "#f9e2af"),          # 黄色
            DownloadStatus.SKIPPED: ("⏭ 跳过", "#6c7086"),         # 暗灰色
        }
        text, color = status_map.get(status, ("未知", "#cdd6f4"))
        item = QTableWidgetItem(text)
        item.setForeground(QColor(color))  # 设置文字颜色
        self._table.setItem(row, 4, item)

    def _update_song_row(self, song: Song):
        """查找并更新指定歌曲的显示状态行。

        Args:
            song: 状态已变更的 Song 对象
        """
        for row, s in enumerate(self._filtered_songs):
            if s.video_id == song.video_id:
                self._set_status_cell(row, song.status)
                # Also update local reference
                self._filtered_songs[row] = song
                break

    def _update_info(self):
        """Update info label and download button."""
        total = len(self._filtered_songs)
        selected = len(self.get_selected_songs())
        self._info_label.setText(f"共 {total} 首歌，已选 {selected} 首")
        self._download_btn.setEnabled(selected > 0)
        self._download_btn.setText(f"⬇ 下载选中 ({selected})")
        self.selection_changed.emit(selected, total)

    # ── Slots ───────────────────────────────────────────

    def _on_search(self, text: str):
        self._apply_filter(text)

    def _on_select_all(self, state: int):
        if state == Qt.CheckState.Checked.value:
            self._select_all(True)
        elif state == Qt.CheckState.Unchecked.value:
            self._select_all(False)

    def _select_all(self, checked: bool):
        for cb in self._checkboxes.values():
            cb.setChecked(checked)
        self._update_info()

    def _deselect_all(self):
        self._select_all(False)
        self._select_all_cb.setCheckState(Qt.CheckState.Unchecked)

    def _on_checkbox_toggled(self, row: int, state: int):
        self._update_info()

    def _on_item_changed(self, item: QTableWidgetItem):
        """Table item edited (unused for now)."""
        pass

    def _on_download_clicked(self):
        selected = self.get_selected_songs()
        if selected:
            self.download_clicked.emit(selected)
