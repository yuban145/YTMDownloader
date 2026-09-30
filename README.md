# YtMusicVault 2.1

Windows 桌面 YouTube Music 音乐库下载工具。登录和歌单请求沿用最初版本的调用方式，网络访问仍在后台执行。

> AI 辅助开发项目，请先用少量内容验证。仅下载您有权下载的内容，并遵守服务条款。

## 已实现

- 从 Edge、Chrome、Firefox、Brave、Vivaldi、Opera、Chromium 导入浏览器会话；自动检测浏览器目录，读取操作由用户点击触发。
- 可选内置 Chromium 浏览器登录：使用内存会话提取 YouTube Cookie，再交给原有音乐库与 yt-dlp 流程；它不跳过播放器 JS 验证，且 Google 可能限制内嵌登录。
- 请求头文本 / JSON 登录、Netscape Cookie 文件登录；多 Google 账号支持账号序号，请求头支持品牌频道 Page ID。
- Google 账号名称仅作为可选显示信息获取，不作为登录或会话保存前置条件；不可用时仍沿用原歌单验证流程。
- 按早期版本调用 `get_library_playlists(limit=100)`、`get_liked_songs(limit=5000)` 和 `get_playlist(..., limit=5000)`；支持手动打开歌单链接、搜索、刷新、错误提示和重试。
- 后台串行访问音乐库，切换歌单 / 退出登录后丢弃旧请求结果，避免串号、旧数据覆盖和 UI 被网络阻塞。
- yt-dlp 下载使用当前导入的 YouTube 会话，每个并发任务独立临时 Cookie 文件；支持最高画质 MV、FLAC 与 MP3，并写入作者 / 艺术家等标签。
- 主界面可下载选中歌曲或整个已加载歌单；「下载」页展示处理阶段、实时进度、失败重试与取消，以及跨重启保留的记录。双击完成项打开本地文件，右键可打开文件或源页面；详细日志可在日志页查看。
- 多账号可分别保存会话并在顶部账号列表切换；旧版单账号会话原位保留，账号备注与当前选择写入 `accounts.json`，各账号 Cookie 仍由独立的 `session.json` 保存。登录验证和歌单接口未改动。
- 「记住登录」默认关闭。只有读到个人歌单或收藏歌曲后才会替换先前保存的会话；开启后会话明文存入本机用户目录，退出登录则清除应用保存的会话，不影响浏览器本身。

这不是 OAuth 授权客户端，不收集 Google 密码。Chrome / Edge 的系统加密或文件锁可能阻止自动读取，失败时请用「请求头登录」，详细步骤见 [GUIDE.md](GUIDE.md)。

默认下载 **MV 最高可用画质**：`bv*+ba/b`，按分辨率 / 帧率优先，不限制分辨率或编码；音视频无损合并为 MKV。主窗口可切换为 FLAC 或 MP3 单独音频模式。专辑音轨会查询 YouTube Music 的视频 counterpart；没有对应 MV 时提示失败，不搜索替换为不确定的视频。

初次使用默认启用 **HTTP 代理 `127.0.0.1:7890`**；请先启动监听该端口的代理软件。新建音乐库会话、内置浏览器、下载、MV 查询和封面请求采用所选代理。设置中可改为系统代理（Windows 静态代理及环境变量）或直连。系统模式按请求地址处理绕过列表；另有 **PAC 自动代理** 模式，可填写 HTTP/HTTPS PAC 地址或选择本地 `.pac` 文件。所有网络模块通过本机临时网关执行 PAC 的 `PROXY` / SOCKS / `DIRECT` 路线及顺序回退，规则每 5 分钟重新加载，加载失败不会自动直连。HTTPS 按目标主机与端口匹配规则，网关不解密 TLS，也无法读取 HTTPS 路径。已有显式代理设置和自定义端口保留。更改代理后，已连接的音乐库需重新登录，内置浏览器需重新打开。

## 运行

要求 Windows 10/11、Python 3.11+（从源码运行时）、PATH 中的 FFmpeg / ffprobe，以及 Deno 或 Node.js（YouTube JS 验证）。源码与 EXE 均使用本项目的 yt-dlp 和配套 EJS，不再寻找 PATH 中可能失效的 yt-dlp.exe。

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-build\Scripts\python.exe main.py
```

启动后：添加账号 → 连接音乐库 → 核对实际歌单内容 → 选择 MV / 音频 → 勾选下载。下载页可看本次任务和下载记录；切换已保存账号用顶部下拉框，更新当前账号凭据用「重新登录」。主窗口显示当前代理模式和脱敏地址。账号显示「未验证」时，空列表不能证明登录成功，请重新导出完整 Cookie。

依赖文档：[ytmusicapi 浏览器认证](https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html)、[音乐库 API](https://ytmusicapi.readthedocs.io/en/stable/reference/library.html)、[yt-dlp](https://github.com/yt-dlp/yt-dlp)。

## 测试与构建

```powershell
.\.venv-build\Scripts\python.exe -B -m unittest discover -s tests -v
.\build.ps1
# 已装好依赖时：
.\build.ps1 -SkipInstall -PythonPath .\.venv-build\Scripts\python.exe
# 正在运行旧版 EXE 时，将新版输出到另一个目录，避免覆盖被占用文件：
.\build.ps1 -SkipInstall -OutputDirectory dist-browser
```

构建依次执行语法检查、自动化测试、源码启动测试、PyInstaller 打包、实际 EXE 启动测试。输出为 `dist/YtMusicVault.exe`；EXE 启动报告使用每次唯一的 `build/exe-smoke-*.txt`，避免读到旧报告误判成功。启动测试使用临时配置，不读取账号、不访问 YouTube、不下载歌曲。

`-Clean` 可清理本项目 build / dist（先检查路径和链接）。已有构建会被替换，请自行保留需要的旧版本。Spec 保留 Windows ICU DLL 冲突修复，并关闭 UPX；内置浏览器需要 QtWebEngine。

PAC 回归覆盖本地及远程规则文件、按主机选路、HTTP/SOCKS 代理、代理端 DNS、HTTPS 证书校验、后备路线、规则刷新和失败关闭。`tests/fixtures/localhost-test-*.pem` 仅为本地 HTTPS 测试使用的公开测试证书和测试密钥。

自动测试采用合成 Cookie 和模拟服务，覆盖早期歌单端点、Qt 后台操作、竞态、错误、下载会话隔离及取消。新增本地 HTTP/代理测试服务器，实际运行 yt-dlp、FFmpeg 下载合并和标签写入，并用 ffprobe 核对音视频流。缺少 FFmpeg 时该集成测试会跳过。**本地测试不能替代真实 YouTube 下载验收。**

可选的真实验收脚本 `tests/manual_embedded_browser_probe.py` 将提供的 Cookie 装入内存浏览器并验证页面和 Cookie 回传；`tests/manual_real_cookie_smoke.py` 用 Cookie 临时副本下载五秒真实视频，检查封装后的音视频流。脚本不会输出 Cookie 值。

## 结构

- `core/auth.py`：凭据解析、浏览器导入、会话存储与旧文件兼容。
- `core/ytm_client.py`：超时、早期版本歌单端点调用和数据转换。
- `ui/library_controller.py`：异步任务与旧结果隔离。
- `ui/download_controller.py`：并发下载、取消、临时会话与结果持久化。
- `ui/main_window.py`、`ui/login_dialog.py`：交互与状态展示。
- `core/downloader.py`、`core/metadata.py`、`core/database.py`：下载工具、媒体标签和历史记录。
- `tests/`：无需账号的回归测试。
