[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$SkipInstall,
    [string]$PythonPath = "",
    [string]$OutputDirectory = "dist"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
$outputRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $OutputDirectory))
if ((Split-Path -Parent $outputRoot) -ne $ProjectRoot) {
    throw "输出目录必须是项目根目录下的一级目录：$outputRoot"
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList
    )

    Write-Host "> $FilePath $($ArgumentList -join ' ')" -ForegroundColor DarkGray
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "命令执行失败（退出码 $LASTEXITCODE）：$FilePath"
    }
}

function Resolve-Python {
    $candidates = @()
    if ($PythonPath) {
        $candidates += $PythonPath
    }
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    $candidates += Join-Path $ProjectRoot '.venv-build\Scripts\python.exe'
    if ($pythonCommand) {
        $candidates += $pythonCommand.Source
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate)) {
            continue
        }
        try {
            $version = & $candidate -c "import sys; print(sys.version_info[0])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $version -match "^3$") {
                return $candidate
            }
        } catch {
            # WindowsApps 的 python 占位入口可能存在但无法启动，继续尝试其他候选。
        }
    }

    throw "找不到可用的 Python 3。可通过 -PythonPath 指定 python.exe。"
}

function Remove-BuildOutputs {
    foreach ($path in @("build", "dist")) {
        $rootPath = [System.IO.Path]::GetFullPath($ProjectRoot)
        $fullPath = [System.IO.Path]::GetFullPath((Join-Path $rootPath $path))
        if ((Split-Path -Parent $fullPath) -ne $rootPath) {
            throw "Refusing to clean a path outside the project: $fullPath"
        }
        if (Test-Path -LiteralPath $fullPath) {
            $item = Get-Item -LiteralPath $fullPath -Force
            $links = @(Get-ChildItem -LiteralPath $fullPath -Recurse -Force -Attributes ReparsePoint)
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $links.Count) {
                throw "Refusing recursive cleanup containing a junction or symlink: $fullPath"
            }
            Remove-Item -LiteralPath $fullPath -Recurse -Force
        }
    }
}

$python = Resolve-Python
Write-Host "使用 Python：$python" -ForegroundColor Cyan

if ($Clean) {
    Remove-BuildOutputs
}

if (-not $SkipInstall) {
    Invoke-Checked $python @("-m", "pip", "install", "-r", "requirements-build.txt")
}

Invoke-Checked $python @("-m", "compileall", "-q", "ytmusicvault")
Invoke-Checked $python @("-B", "-m", "unittest", "discover", "-s", "tests", "-v")
Invoke-Checked $python @("main.py", "--smoke-test", (Join-Path $ProjectRoot "source-smoke.txt"))
Invoke-Checked $python @("-m", "PyInstaller", "--clean", "--noconfirm", "--distpath", $outputRoot, "YtMusicVault.spec")

$exe = Join-Path $outputRoot "YtMusicVault.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "构建结束但未找到输出文件：$exe"
}

$sizeMb = [math]::Round((Get-Item -LiteralPath $exe).Length / 1MB, 2)
if ($sizeMb -le 1) {
    throw "输出文件异常偏小：$sizeMb MB"
}

$report = Join-Path $ProjectRoot ('build\exe-smoke-' + [guid]::NewGuid().ToString('N') + '.txt')
$process = Start-Process -FilePath $exe -ArgumentList @('--smoke-test', ('"' + $report + '"')) -PassThru -WindowStyle Hidden
if (-not $process.WaitForExit(60000)) {
    $process.Kill()
    throw 'EXE startup test timed out.'
}
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) {
    if (Test-Path -LiteralPath $report) { Get-Content -LiteralPath $report }
    throw 'EXE startup test failed.'
}
Get-Content -LiteralPath $report
Invoke-Checked $python @("-B", "tests/run_packaged_media.py", "--exe", $exe)
Write-Host "构建成功：$exe ($sizeMb MB)" -ForegroundColor Green
