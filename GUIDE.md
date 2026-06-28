# YtMusicVault 使用指南

YouTube Music 批量下载器 — 将您的 YouTube Music 歌单变成本地音乐文件。

---

## 📑 目录

1. [快速开始](#快速开始)
2. [登录账号](#登录账号)
3. [浏览歌单](#浏览歌单)
4. [下载歌曲](#下载歌曲)
5. [设置说明](#设置说明)
6. [Cookies 文件格式](#cookies-文件格式)
7. [常见问题](#常见问题)

---

## 🚀 快速开始

### 安装

```bash
# 1. 确保安装了 Python 3.11+ 和 yt-dlp
pip install yt-dlp

# 2. 安装项目依赖
pip install -r requirements.txt

# 3. 启动
python main.py
```

### 打包为 .exe（无需 Python 环境）

```bash
pip install pyinstaller
pyinstaller YtMusicVault.spec
# 生成的 .exe 在 dist/YtMusicVault.exe
```

---

## 🔐 登录账号

YtMusicVault 提供两种登录方式：

### 方法一：OAuth 浏览器登录（推荐 ⭐）

1. 点击菜单 **账号 → 登录 OAuth**
2. 确认后会**自动打开浏览器**
3. 在浏览器中**登录您的 Google 账号**并授权
4. 完成后浏览器自动关闭，应用会自动加载您的音乐库

> ✅ 优点：安全、无需手动处理密码、自动刷新凭据
> ⚠ 前提：电脑上需要有浏览器（Chrome/Edge/Firefox）

### 方法二：导入 Cookies 文件

如果 OAuth 无法使用（如服务器环境），可以手动导入 Cookies：

1. **获取 Cookies 文件**（见下方 [Cookies 文件格式](#cookies-文件格式)）
2. 点击菜单 **账号 → 导入 Cookies**
3. 选择导出的 `.txt` 文件
4. 应用会自动验证文件格式并登录

> 详细格式说明见 [Cookies 文件格式](#cookies-文件格式) 章节

---

## 📋 浏览歌单

登录成功后，左侧边栏会显示：

```
📁 音乐库
├── ❤️ 我喜欢 (1,234首)
├── 🎵 Chill
├── 🎵 Workout
└── 🎵 Study
```

- 点击 **❤️ 我喜欢** 查看所有点赞歌曲
- 点击 **🎵 播放列表名** 查看该列表中的歌曲
- 右侧的歌曲列表支持 **搜索过滤**：在搜索框中输入歌名或作者即可筛选

---

## ⬇ 下载歌曲

### 基本下载流程

1. **勾选** 要下载的歌曲（支持全选）
2. 点击底部 **⬇ 下载选中** 按钮
3. 查看**状态栏**的实时进度

### 进度显示

```
████████████░░░░░░ 65%   15/50   ⬇ 2.3MB/s   剩余 8 分钟
├─ 总体进度条       ├─ 已完成/总数    ├─ 速度       └─ 预计剩余时间
```

### 列表中的状态标识

| 图标 | 含义 |
|------|------|
| ⏳ 待下载 | 等待开始 |
| ⬇ 下载中 | 正在下载 |
| ✅ 已完成 | 下载成功 |
| ❌ 失败 | 下载出错 |
| ⏸ 暂停 | 已暂停 |
| ⏭ 跳过 | 之前已下载，自动跳过 |

### 断点续传

- 已成功下载的歌曲会**自动跳过**，不会重复下载
- 下载记录保存在本地 SQLite 数据库中
- 即使关闭应用重新打开，已下载的歌曲仍标记为 ✅

---

## ⚙ 设置说明

点击菜单 **设置 → 偏好设置** 可配置以下选项：

### 下载设置

| 设置项 | 默认值 | 说明 |
|--------|--------|------|
| 下载目录 | `~/Music/YtMusicVault/` | 文件保存位置 |
| 音质 | 256 kbps | 128/256/最佳 |
| 并发数 | 4 | 同时下载 1-8 首 |
| 失败重试 | 3 次 | 下载失败自动重试 |
| 重试间隔 | 5 秒 | 每次重试等待时间 |

### 文件命名

| 设置项 | 默认值 | 说明 |
|--------|--------|------|
| 文件名模板 | `{artist} - {title}.{ext}` | 可用变量：`{artist}`, `{title}`, `{album}`, `{track}`, `{ext}` |
| 按播放列表建文件夹 | 开启 | 每个播放列表创建单独子文件夹 |

### 命名示例

```
模板: {artist} - {title}.{ext}
结果: 周杰伦 - 七里香.m4a

模板: {track}. {title}.{ext}
结果: 01. 七里香.m4a

模板: {artist}/{album}/{track} - {title}.{ext}
结果: 周杰伦/七里香/03 - 借口.m4a
```

---

## 📄 Cookies 文件格式

### 什么是 Cookies 文件？

Cookies 是浏览器存储的登录状态信息。将 YouTube Music 的 Cookies 导出为特定格式的文件后，应用可以直接使用这些信息登录，无需再次通过浏览器授权。

### 支持格式：Netscape HTTP Cookies

文件必须是 **TAB 分隔** 的 Netscape 格式，示例：

```
# Netscape HTTP Cookie File
# https://curl.se/docs/http-cookies.html
.youtube.com	TRUE	/	TRUE	1798765432	CONSENT	YES+
.youtube.com	TRUE	/	FALSE	1798765432	VISITOR_INFO1_LIVE	abc123def456
.youtube.com	TRUE	/	FALSE	1798765432	LOGIN_INFO	xxxxxxxxxxxxx
.youtube.com	TRUE	/	FALSE	1798765432	SID	xxxxxxxxxxxxx
.youtube.com	TRUE	/	FALSE	1798765432	HSID	xxxxxxxxxxxxx
.youtube.com	TRUE	/	FALSE	1798765432	SSID	xxxxxxxxxxxxx
.youtube.com	TRUE	/	TRUE	1798765432	APISID	xxxxxxxxxxxxx
.youtube.com	TRUE	/	TRUE	1798765432	SAPISID	xxxxxxxxxxxxx
.google.com	TRUE	/	TRUE	1798765432	__Secure-3PAPISID	xxxxxxxxxxxxx
.google.com	TRUE	/	TRUE	1798765432	__Secure-3PSID	xxxxxxxxxxxxx
```

### 字段说明

每行 7 个字段（用 **TAB 键** 分隔）：

| 序号 | 字段 | 说明 | 示例 |
|------|------|------|------|
| 1 | domain | Cookie 所属域名 | `.youtube.com` |
| 2 | flag | 是否所有子域名匹配 | `TRUE` |
| 3 | path | Cookie 路径 | `/` |
| 4 | secure | 是否仅 HTTPS | `TRUE` |
| 5 | expiration | 过期时间（UNIX 秒） | `1798765432` |
| 6 | name | Cookie 名称 | `LOGIN_INFO` |
| 7 | value | Cookie 值 | `xxxxx` |

### 🔧 如何获取 Cookies 文件？

#### 方法 A：浏览器扩展（最简单 ⭐）

1. **Chrome / Edge**：
   - 安装扩展 [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   - 打开 [music.youtube.com](https://music.youtube.com) 并登录
   - 点击扩展图标 → 点击 **Export** → 保存为 `.txt` 文件

2. **Firefox**：
   - 安装扩展 [cookies.txt](https://addons.mozilla.org/firefox/addon/cookies-txt/)
   - 同样访问 music.youtube.com → 导出

#### 方法 B：开发者工具手动导出

1. 打开 Chrome/Edge，访问 [music.youtube.com](https://music.youtube.com) 并登录
2. 按 **F12** 打开开发者工具
3. 切换到 **Application**（应用程序）标签
4. 左侧找到 **Cookies** → 点击 `https://music.youtube.com`
5. 记录以下 Cookie 的 **Name** 和 **Value**：

   | 必需的 Cookie | 用途 |
   |---------------|------|
   | `CONSENT` | 同意状态 |
   | `VISITOR_INFO1_LIVE` | 访客标识 |
   | `LOGIN_INFO` | 登录信息 |
   | `SID` | 会话 ID |
   | `HSID` | 安全会话 |
   | `SSID` | 安全会话 |
   | `APISID` | API 会话 |
   | `SAPISID` | 安全 API 会话 |
   | `__Secure-3PAPISID` | Google 账户 |
   | `__Secure-3PSID` | Google 账户 |

6. 还需要从 `https://accounts.google.com` 的 Cookies 中获取 `__Secure-3PAPISID` 和 `__Secure-3PSID`

7. 按上面的 Netscape 格式将 Cookie 写入 `.txt` 文件：
   ```
   .youtube.com	TRUE	/	TRUE	1798765432	CONSENT	YES+
   .youtube.com	TRUE	/	FALSE	1798765432	VISITOR_INFO1_LIVE	你的值
   ... (以此类推)
   ```

> ⚠ **重要**：Cookies 包含您的账号敏感信息，请勿分享给他人！

---

## ❓ 常见问题

### Q: 下载速度慢怎么办？
- 降低并发数（设置 → 并发数 → 1-2）
- YouTube 可能对高频请求限流，降低并发可缓解

### Q: 下载失败 / 403 错误？
- 尝试降低并发数
- 检查网络连接
- 如果持续失败，尝试重新登录（账号 → 登出 → 重新登录）

### Q: OAuth 浏览器没有自动打开？
- 手动打开浏览器访问 YouTube Music，确保能正常登录
- 尝试使用「导入 Cookies」替代方案
- 检查默认浏览器设置

### Q: 封面图片没有写入？
- 确保下载时网络正常（封面从 YouTube 服务器获取）
- 封面写入仅支持 `.m4a` 格式

### Q: 能在没有 Python 的电脑上运行吗？
- 可以！使用 PyInstaller 打包为 `.exe`：
  ```bash
  pyinstaller YtMusicVault.spec
  ```
- 但注意 `yt-dlp.exe` 也需要在目标电脑的 PATH 中，或随程序一起打包

### Q: 下载的文件在哪里？
- 默认位置：`C:\Users\<用户名>\Music\YtMusicVault\`
- 可在 设置 → 下载目录 中自定义

### Q: 如何更新 yt-dlp？
```bash
pip install --upgrade yt-dlp
```

---

## 📁 项目文件结构

```
YTMDownloader/
├── main.py                    # 程序入口
├── GUIDE.md                   # 本文件（使用指南）
├── README.md                  # 项目说明
├── requirements.txt           # Python 依赖
├── YtMusicVault.spec          # PyInstaller 打包配置
└── ytmusicvault/              # 源代码
    ├── core/                  # 核心逻辑
    │   ├── auth.py            # 认证模块
    │   ├── ytm_client.py      # YouTube Music API
    │   ├── downloader.py      # 下载引擎
    │   ├── metadata.py        # 元数据写入
    │   ├── queue_manager.py   # 队列管理
    │   └── database.py        # 本地数据库
    └── ui/                    # 用户界面
        ├── main_window.py     # 主窗口
        ├── sidebar.py         # 侧边栏
        ├── song_list.py       # 歌曲列表
        └── settings_dialog.py # 设置对话框
```
