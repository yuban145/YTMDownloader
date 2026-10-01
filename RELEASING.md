# 发布步骤

发布前统一修改 `ytmusicvault/__init__.py` 的版本号，并更新 README、指南和 CHANGELOG。应用界面读取同一个版本号。

使用 Windows x64、Python 3.11+，并配置 FFmpeg、ffprobe、Deno 或 Node.js。源码依赖在 `requirements.txt`，构建依赖在 `requirements-build.txt`。

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\build.ps1 -SkipInstall -PythonPath .\.venv-build\Scripts\python.exe -OutputDirectory dist-release
```

构建脚本执行语法检查、完整测试、源码启动、打包 EXE 启动及实际打包媒体集成测试。只有全部通过才生成可发布的构建结果。

可用自己的 Cookie 进行真实测试；该文件会保持在本机，下载使用临时副本。

```powershell
.\.venv-build\Scripts\python.exe -X utf8 -B tests/manual_real_cookie_smoke.py cookies.txt http://127.0.0.1:7890 dist-release\YtMusicVault.exe
```

提交经过检查的源码后，在该提交上生成发布 ZIP 和校验文件：

```powershell
.\.venv-build\Scripts\python.exe scripts/package_release.py --exe dist-release\YtMusicVault.exe
```

脚本只打包 EXE、README、GUIDE、CHANGELOG 和自动生成的构建信息，不会扫描用户目录或将 Cookie、会话、数据库、测试输出放进 ZIP。输出在被 Git 忽略的 `release/`，GitHub 自动提供对应版本的源代码归档。

发布时上传 `YtMusicVault-<版本>-windows-x64.zip` 和 `SHA256SUMS.txt`，Release 标签使用 `v<版本>` 并指向被验证的源码提交。说明运行依赖、主要修复和已完成的验收范围。

```powershell
Get-FileHash release\YtMusicVault-2.1.1-windows-x64.zip -Algorithm SHA256
```

将输出与 `SHA256SUMS.txt` 中对应 ZIP 的哈希比对。Windows 发布 EXE 当前没有代码签名。
