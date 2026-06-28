"""YtMusicVault — YouTube Music 批量下载器 | 应用入口

启动方式：
    python main.py

架构概述：
  main.py → YtMusicVaultApp (app.py) → MainWindow (ui/main_window.py)
                                          ├── Sidebar (播放列表)
                                          ├── SongListWidget (歌曲表格)
                                          └── 核心模块 (auth, downloader, metadata, ...)
"""

import sys

from ytmusicvault.app import YtMusicVaultApp


def main():
    """应用入口函数。

    创建 YtMusicVaultApp 实例并启动 Qt 事件循环。
    app.run() 内部调用 QApplication.exec()，阻塞直到窗口关闭。
    返回值传递给 sys.exit() 作为进程退出码。
    """
    app = YtMusicVaultApp()
    return app.run()


if __name__ == "__main__":
    # sys.exit(main()) 将 main() 的返回值（QApplication.exec() 的返回码）
    # 作为进程退出码传递给操作系统
    sys.exit(main())
