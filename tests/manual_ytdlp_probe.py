"""Bounded live YouTube extractor diagnostic; does not print Cookie data."""
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ytmusicvault.core.downloader import Downloader, download_error


def main():
    if len(sys.argv) not in (3, 4, 5):
        print("usage: manual_ytdlp_probe.py COOKIE_FILE_OR_DASH source|package|official|nightly [RUNTIME] [EXTRACTOR_ARGS]")
        return 2
    cookie_file = Path(sys.argv[1])
    if sys.argv[1] != "-" and not cookie_file.is_file():
        print("cookie_file=missing")
        return 1
    mode = sys.argv[2]
    if mode == "source":
        command = [sys.executable, "-m", "yt_dlp"]
    elif mode == "package":
        command = [str(Path(__file__).resolve().parents[1] / "dist" / "YtMusicVault.exe"), "--yt-dlp"]
    elif mode == "official":
        command = [str(Path(__file__).resolve().parents[1] / "yt-dlp-official-2026.08.19.exe")]
    elif mode == "nightly":
        command = [str(Path(__file__).resolve().parents[1] / "yt-dlp-official-nightly-2026.09.16.exe")]
    else:
        return 2
    command += ["--ignore-config", "--no-playlist", "--skip-download", "--verbose",
                "--socket-timeout", "10", "--retries", "0", "--extractor-retries", "0",
                "--proxy", "http://127.0.0.1:7890",
                "--print", "id"]
    if sys.argv[1] != "-":
        command += ["--cookies", str(cookie_file)]
    if len(sys.argv) == 5:
        command += ["--extractor-args", sys.argv[4]]
    runtimes = (sys.argv[3],) if len(sys.argv) >= 4 else ("deno", "node")
    for runtime in runtimes:
        if runtime == "deno-local":
            path = Path(__file__).resolve().parents[1] / "tools" / "deno-2.9.7" / "deno.exe"
            runtime = "deno"
        else:
            path = shutil.which(runtime)
        if path:
            command += ["--js-runtimes", f"{runtime}:{Path(path).resolve()}"]
            break
    command.append("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    print(f"mode={mode}; phase=extracting", flush=True)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace")
    print(f"child_pid={process.pid}", flush=True)
    lines = []
    stage = [""]
    def read_output():
        for line in process.stdout:
            lines.append(line)
            low = line.lower()
            for marker in ("downloading webpage", "downloading tv client config",
                           "downloading player api json", "downloading ios player api json",
                           "downloading web player api json", "downloading m3u8", "solving",
                           "challenge", "extracting url"):
                if marker in low and stage[0] != marker:
                    stage[0] = marker
                    print(f"stage={marker}", flush=True)
                    break
    threading.Thread(target=read_output, daemon=True).start()
    deadline = time.monotonic() + 50
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.2)
    if process.poll() is None:
        Downloader._stop_process(process)
        print(f"extractor=timed_out; last_stage={stage[0] or 'none'}")
        return 1
    process.wait(timeout=5)
    stdout = "".join(lines)
    if process.returncode:
        print(f"extractor=failed: {download_error(stdout.splitlines())}")
        return 1
    print(f"extractor={'ok' if 'dQw4w9WgXcQ' in stdout else 'unexpected_output'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "-":
        # yt-dlp may rewrite --cookies on exit. Never point it at the user's
        # original export, including during a read-only extraction probe.
        with tempfile.TemporaryDirectory(prefix="ytmv-cookie-probe-",
                                         dir=Path(__file__).resolve().parents[1]) as temp:
            source = Path(sys.argv[1])
            copied = Path(temp) / "cookies.txt"
            shutil.copyfile(source, copied)
            sys.argv[1] = str(copied)
            raise SystemExit(main())
    raise SystemExit(main())
