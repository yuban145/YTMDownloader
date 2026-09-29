"""CLI worker entry for a PyInstaller windowed application."""
import os
import sys


def run_ytdlp(args):
    # runw.exe sets sys.stdout/stderr to None even when Popen provides pipes.
    # Reopen the inherited Windows handles so progress and after_move reach UI.
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.argtypes = [ctypes.c_uint32]
        kernel.GetStdHandle.restype = ctypes.c_void_p
        for name, number in (("stdout", -11), ("stderr", -12)):
            if getattr(sys, name) is None:
                handle = kernel.GetStdHandle(number & 0xffffffff)
                if handle not in (None, ctypes.c_void_p(-1).value):
                    fd = msvcrt.open_osfhandle(handle, os.O_WRONLY)
                    stream = os.fdopen(fd, "w", encoding="utf-8", errors="replace", buffering=1)
                else:
                    stream = open(os.devnull, "w", encoding="utf-8")
                setattr(sys, name, stream)
                setattr(sys, "__" + name + "__", stream)
        if sys.stdin is None:
            sys.stdin = open(os.devnull, "r")
    from yt_dlp import main
    main(args)
