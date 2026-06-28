# **纯AI作品 谨慎使用！**
# YtMusicVault — YouTube Music 批量下载器
Windows 桌面应用，登录 YouTube Music 账号，批量下载个人收藏歌曲，自动写入封面和元数据，生成本地音乐库。

## ✨ 功能

- 🔐 **OAuth 登录** — 浏览器安全授权，无需手动填密码
- 📋 **歌单浏览** — 查看「我喜欢」和所有自建/收藏播放列表
- ⬇ **批量下载** — 多选歌曲，1-8 并发下载，自动跳过已完成
- 🏷 **元数据写入** — 自动写入歌名、作者、专辑、封面图（m4a）
- 🔄 **断点续传** — 已下载自动跳过，失败自动重试
- 📊 **实时进度** — 单曲进度 + 总体进度 + 下载速度
- 🗄 **下载记录** — SQLite 记录下载历史，避免重复

## 🚀 快速开始

### 环境要求

- Windows 10/11
- Python 3.11+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)（需在 PATH 中）

### 安装

```bash
# 1. 克隆 / 解压项目
cd YTMDownloader

# 2. 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate   # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 确保 yt-dlp 可用
pip install yt-dlp

# 5. 启动
python main.py
```

### 打包为 .exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name YtMusicVault --add-data "ytmusicvault;ytmusicvault" main.py
```

## 📁 项目结构

```
YTMDownloader/
├── main.py                      # 入口
├── requirements.txt             # 依赖
├── README.md
└── ytmusicvault/
    ├── __init__.py
    ├── app.py                   # QApplication 启动
    ├── core/
    │   ├── auth.py              # OAuth + Cookies 认证
    │   ├── ytm_client.py        # ytmusicapi 封装
    │   ├── downloader.py        # yt-dlp 下载引擎
    │   ├── metadata.py          # mutagen 元数据写入
    │   ├── queue_manager.py     # 并发下载队列
    │   └── database.py          # SQLite 下载记录
    ├── models/
    │   ├── song.py              # 歌曲数据模型
    │   └── playlist.py          # 播放列表模型
    ├── ui/
    │   ├── main_window.py       # 主窗口
    │   ├── sidebar.py           # 侧边栏
    │   ├── song_list.py         # 歌曲列表
    │   ├── settings_dialog.py   # 设置对话框
    │   ├── login_dialog.py      # 登录对话框
    │   └── styles.py            # QSS 主题
    └── utils/
        ├── config.py            # 配置管理
        └── helpers.py           # 工具函数
```

## 🛠 技术栈

| 组件 | 技术 |
|------|------|
| UI 框架 | PySide6 (Qt for Python) |
| 下载引擎 | yt-dlp (subprocess) |
| YouTube API | ytmusicapi |
| 元数据 | mutagen |
| 数据库 | SQLite |
| 打包 | PyInstaller |

## 📝 使用说明

1. **登录**：点击菜单「账号 → 登录 OAuth」，浏览器自动打开，登录 Google 账号授权
2. **浏览**：左侧查看「我喜欢」和所有播放列表，点击切换
3. **选择**：勾选要下载的歌曲，支持全选/搜索过滤
4. **下载**：点击「下载选中」，实时查看进度
5. **设置**：菜单「设置 → 偏好设置」配置下载目录、音质、命名规则

## ⚠️ 注意事项

- 请遵守 YouTube 服务条款，仅下载您有权下载的内容
- 大量下载可能触发 YouTube 限流，建议降低并发数
- 首次 OAuth 登录需要浏览器完成 Google 授权
- 下载的音频文件保存在 `~/Music/YtMusicVault/`（可自定义）
