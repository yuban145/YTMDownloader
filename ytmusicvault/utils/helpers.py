"""工具函数集

项目级的纯函数工具，无状态、无副作用、无外部依赖（除 re）。
包含：时间格式化、文件大小格式化、yt-dlp 进度解析、文件名清理。
"""

import re


def format_duration(seconds: int) -> str:
    """将秒数转换为 mm:ss 或 h:mm:ss 格式的字符串。
    
    用于在 UI 表格中显示歌曲时长。
    
    Args:
        seconds: 秒数（整数）
    Returns:
        格式化字符串，如 "3:45" 或 "1:23:45"
        如果 seconds <= 0 或为 None，返回 "0:00"
    """
    if not seconds or seconds <= 0:
        return "0:00"
    # divmod 一次性得到商和余数，比分别 // 和 % 更高效
    h, remainder = divmod(int(seconds), 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"   # 超过 1 小时显示 h:mm:ss
    return f"{m}:{s:02d}"               # 不足 1 小时显示 m:ss


def format_size(bytes_count: int) -> str:
    """将字节数格式化为人类可读的文件大小。
    
    Args:
        bytes_count: 字节数
    Returns:
        如 "1.5 MB", "340.2 KB" 等
    """
    for unit in ("B", "KB", "MB", "GB"):
        if abs(bytes_count) < 1024.0:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f} TB"


def parse_ytdlp_progress(line: str) -> dict:
    """解析 yt-dlp 的进度输出行，提取百分比、大小、速度、ETA。
    
    yt-dlp 使用 --newline --progress 时会输出如下格式：
        [download]  45.3% of ~5.20MiB at  2.3MiB/s ETA 00:15
    
    本函数用正则表达式从中提取结构化数据。
    正则设计为容错性强：即使部分字段缺失，也返回默认值而非抛异常。
    
    Args:
        line: yt-dlp 的标准输出行
    Returns:
        dict 包含 percent(float), total_size(str), speed(str), eta(str)
        未匹配到的字段为空字符串或 0.0
    """
    result = {
        "percent": 0.0,
        "total_size": "",
        "speed": "",
        "eta": "",
    }
    
    # 匹配百分比：支持整数和浮点数，如 "45.3%" 或 "100%"
    pct_match = re.search(r"(\d+\.?\d*)%", line)
    if pct_match:
        result["percent"] = float(pct_match.group(1))
    
    # 匹配文件总大小："of ~5.20MiB"，~ 表示约等于
    size_match = re.search(r"of\s+(~?\d+\.?\d*\s*[KMG]iB)", line)
    if size_match:
        result["total_size"] = size_match.group(1)
    
    # 匹配下载速度："at 2.3MiB/s"
    speed_match = re.search(r"at\s+(\d+\.?\d*\s*[KMG]iB/s)", line)
    if speed_match:
        result["speed"] = speed_match.group(1)
    
    # 匹配剩余时间："ETA 00:15" 或 "ETA 1:23:45"
    eta_match = re.search(r"ETA\s+(\d{1,2}:\d{2}(?::\d{2})?)", line)
    if eta_match:
        result["eta"] = eta_match.group(1)
    
    return result


def safe_filename(name: str) -> str:
    """将字符串转换为安全的文件名。
    
    替换 Windows 文件系统禁止的字符，并截断到 200 字符以防止路径过长。
    
    Args:
        name: 原始名称
    Returns:
        安全的文件名（最多 200 字符）
    """
    unsafe = '<>:"/\\|?*'
    for ch in unsafe:
        name = name.replace(ch, "_")
    return name.strip()[:200]
