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



def main():
    """应用入口函数。

    创建 YtMusicVaultApp 实例并启动 Qt 事件循环。
    app.run() 内部调用 QApplication.exec()，阻塞直到窗口关闭。
    返回值传递给 sys.exit() 作为进程退出码。
    """
    from ytmusicvault.app import YtMusicVaultApp
    app = YtMusicVaultApp()
    return app.run()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--yt-dlp":
        # Frozen builds use the same tested yt-dlp instead of a stale PATH launcher.
        from ytmusicvault.core.runtime import run_ytdlp
        run_ytdlp(sys.argv[2:])
        sys.exit(0)
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        import os
        import tempfile
        import traceback
        from pathlib import Path

        report = Path(sys.argv[2]).resolve()
        try:
            with tempfile.TemporaryDirectory(prefix="ytmv-smoke-") as test_dir:
                os.environ["APPDATA"] = test_dir
                os.environ["QT_QPA_PLATFORM"] = "offscreen"
                from ytmusicvault.app import YtMusicVaultApp
                from ytmusicvault.ui.login_dialog import LoginDialog
                from ytmusicvault.ui.settings_dialog import SettingsDialog
                from ytmusicvault.core.auth import normalize_headers
                from ytmusicvault.core.downloader import ytdlp_command, hidden_process_options
                import subprocess
                worker = subprocess.run(ytdlp_command() + ["--version"], capture_output=True,
                                        text=True, encoding="utf-8", timeout=30, **hidden_process_options())
                if worker.returncode != 0 or not worker.stdout.strip():
                    raise RuntimeError("Bundled yt-dlp subprocess/stdio smoke test failed")
                from ytmusicapi import YTMusic
                import requests

                class OfflineSession(requests.Session):
                    def request(self, *args, **kwargs):
                        raise AssertionError("Smoke test must not access the network")

                # Exercise real API construction: imports alone do not reveal
                # missing packaged gettext locale files used at login time.
                credentials = normalize_headers({"cookie": "__Secure-3PAPISID=synthetic-smoke",
                                                  "x-goog-visitor-id": "offline-smoke"})
                with OfflineSession() as session:
                    api = YTMusic(auth=credentials.headers, requests_session=session, language="en")
                    assert "SAPISIDHASH" in api.headers["authorization"]
                app = YtMusicVaultApp(auto_restore=False)
                login = LoginDialog(app._window)
                settings = SettingsDialog(app._window._config, app._window)
                app._app.processEvents()
                login.close()
                settings.close()
                app._window.close()
                report.write_text("PASS: QtWidgets, login/settings, YTMusic locales, bundled yt-dlp subprocess "
                                  + worker.stdout.strip() + " (offline)\n", encoding="utf-8")
        except Exception:
            report.write_text(traceback.format_exc(), encoding="utf-8")
            sys.exit(1)
        sys.exit(0)
    # sys.exit(main()) 将 main() 的返回值（QApplication.exec() 的返回码）
    # 作为进程退出码传递给操作系统
    sys.exit(main())
