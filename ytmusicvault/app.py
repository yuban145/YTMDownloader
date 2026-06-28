"""应用启动引导 — QApplication 初始化、依赖检查、主窗口创建。

启动顺序（必须严格遵守）：
  1. _setup_webengine_proxy()    设置 QWebEngine 代理环境变量
  2. QApplication.setAttribute()  设置高 DPI 属性
  3. QApplication()               创建 Qt 应用实例
  4. _check_dependencies()        验证 yt-dlp 可用
  5. MainWindow()                 创建主窗口（加载配置、数据库、认证）
  6. show() + exec()              显示窗口并启动事件循环
  7. QTimer.singleShot(100ms)     延迟自动登录（等事件循环就绪）

⚠️ 所有 QApplication 相关的设置必须在 QApplication() 构造之前完成。
"""

import sys
import os
import logging
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .ui.main_window import MainWindow
from .utils.config import AppConfig

# ── 日志初始化（模块级，最早执行） ──────────────────────
# 在 QApplication 创建之前设置，确保启动错误也能被记录
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),  # 输出到 stderr，不影响 stdout
    ],
)
_log = logging.getLogger(__name__)


def _setup_webengine_proxy():
    """在 QApplication 启动前设置 QWebEngine 的代理。

    QWebEngine（Chromium）在启动时读取 QTWEBENGINE_CHROMIUM_FLAGS
    环境变量来设置 --proxy-server。必须在 QApplication 构造之前调用。

    这是唯一能在 QWebEngine 中生效的代理设置方式。
    QNetworkProxy.setApplicationProxy() 对 WebEngine 无效。
    """
    config = AppConfig.load()
    if not config.proxy_enabled:
        return
    proxy_url = config.proxy_url
    if not proxy_url:
        return
    # 追加 --proxy-server 到 Chromium 启动参数
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--proxy-server" not in flags:
        flags += f" --proxy-server={proxy_url}"
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags.strip()
        _log.info(f"WebEngine proxy: {proxy_url}")


class YtMusicVaultApp:
    """应用程序主类 — 负责启动流程编排。

    职责：
      1. 初始化 Qt 应用（高 DPI、应用元信息）
      2. 检查外部依赖（yt-dlp）
      3. 创建并显示主窗口
      4. 启动 Qt 事件循环
    """

    def __init__(self):
        # ── 步骤 1：代理设置（必须在 QApplication 之前） ──
        _setup_webengine_proxy()

        # ── 步骤 2：高 DPI 设置（必须在 QApplication 之前） ──
        # Qt 5.6+: 启用高 DPI 缩放（4K 屏幕上不会模糊）
        if hasattr(Qt, "AA_EnableHighDpiScaling"):
            QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        if hasattr(Qt, "AA_UseHighDpiPixmaps"):
            QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

        # ── 步骤 3：创建 QApplication ─────────────────────
        # sys.argv 传递给 Qt 用于解析命令行参数（如 --style）
        self._app = QApplication(sys.argv)
        self._app.setApplicationName("YtMusicVault")
        self._app.setApplicationVersion("1.0.0")
        self._app.setOrganizationName("YtMusicVault")

        # ── 步骤 4：依赖检查 ──────────────────────────────
        self._check_dependencies()

        # ── 步骤 5：创建主窗口 ────────────────────────────
        # MainWindow.__init__ 中完成：加载配置、创建数据库连接、
        # 初始化认证管理器、构建 UI、注册信号槽
        self._window = MainWindow()

    def _check_dependencies(self):
        """确认 yt-dlp 可执行文件在 PATH 中。

        查找顺序：
          1. shutil.which("yt-dlp") — 在系统 PATH 中搜索
          2. Python Scripts 目录（Windows: .../Python/Scripts/）
          3. Python bin 目录（Unix: .../python/bin/）
          4. 用户本地 bin 目录（~/.local/bin/）

        找不到时不会阻止启动，但下载时会报错。
        """
        import shutil
        if shutil.which("yt-dlp") is None:
            # 尝试在常见位置查找
            possible = [
                os.path.join(sys.prefix, "Scripts", "yt-dlp.exe"),  # Windows
                os.path.join(sys.prefix, "bin", "yt-dlp"),          # Unix venv
                os.path.join(Path.home(), ".local", "bin", "yt-dlp"), # Linux user
            ]
            for p in possible:
                if os.path.exists(p):
                    # 将找到的目录追加到 PATH
                    os.environ["PATH"] = os.path.dirname(p) + os.pathsep + os.environ.get("PATH", "")
                    return
            # 找不到 yt-dlp：应用仍可启动，下载时 Downloader 会报清晰错误

    def run(self):
        """显示主窗口并启动 Qt 事件循环（阻塞直到窗口关闭）。

        Returns:
            QApplication.exec() 的返回码（0 = 正常退出）
        """
        self._window.show()
        return self._app.exec()
