"""Opt-in live smoke test. Never prints or persists the supplied Cookie values.

Usage: python tests/manual_real_cookie_smoke.py PATH_TO_NETSCAPE_COOKIES
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ytmusicvault.core.auth import AuthManager, LoginRequest, AuthError
from ytmusicvault.core.downloader import Downloader, RESULT_PREFIX, download_error, hidden_process_options
from ytmusicvault.core.ytm_client import YtmClient, user_error
from ytmusicvault.utils.config import AppConfig


def main():
    if len(sys.argv) not in (2, 3, 4):
        print("usage: manual_real_cookie_smoke.py PATH_TO_NETSCAPE_COOKIES [PROXY_URL] [EXE_PATH|source]")
        return 2
    try:
        credentials = AuthManager().prepare(LoginRequest("file", sys.argv[1]))
    except AuthError as exc:
        print(f"cookie_import=failed: {exc}")
        return 1
    print("cookie_import=ok", flush=True)

    config = AppConfig.load()
    proxy_url = sys.argv[2] if len(sys.argv) >= 3 else config.proxy_url
    print(f"proxy_mode={'manual-test' if len(sys.argv) >= 3 else config.proxy_mode}", flush=True)
    # First-version file import generated a browser User-Agent in headers.json.
    credentials.headers.setdefault(
        "user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    client = None
    library_verified = False
    try:
        client, account = YtmClient.connect(credentials, proxy_url)
        print(f"library_connection=ok; identity_available={account.get('identityAvailable', False)}", flush=True)
        playlists = client.get_playlists()
        print(f"playlist_fetch=ok; count={len(playlists)}", flush=True)
        liked = client.get_tracks("LM")
        print(f"liked_songs_fetch=ok; count={len(liked.songs)}", flush=True)
        library_verified = bool(playlists or liked.songs)
        print(f"personal_library_verified={library_verified}", flush=True)
    except Exception as exc:
        print(f"account_or_playlist_fetch=failed: {user_error(exc)}", flush=True)
    finally:
        if client:
            client.close()

    # yt-dlp rewrites cookie jars, so use an isolated short-lived copy just as
    # DownloadController does. Keep the user's source file read-only.
    root = Path(__file__).resolve().parents[1]
    source_mode = len(sys.argv) == 4 and sys.argv[3] == "source"
    exe = Path(sys.argv[3]) if len(sys.argv) == 4 else root / "dist" / "YtMusicVault.exe"
    if not source_mode and not exe.is_file():
        print("packaged_downloader=missing")
        return 1
    label = "source" if source_mode else exe.parent.name
    output_dir = root / "test-output" / "real-cookie" / (label + "-" + uuid4().hex[:8])
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ytmv-live-", dir=root) as temporary:
        cookie_path = Path(temporary) / "cookies.txt"
        cookie_path.write_text(credentials.download_cookies(), encoding="utf-8")
        downloader = Downloader(str(output_dir), cookies_path=str(cookie_path),
                                proxy_url=proxy_url, download_mode="video")
        # Fetch a real five-second section. yt-dlp --test truncates individual
        # streams to dummy bytes, which FFmpeg cannot reliably mux/remux.
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        cmd = downloader._build_command(url, downloader._build_output_template(str(output_dir)))
        if not source_mode:
            cmd[:3] = [str(exe), "--yt-dlp"]
        cmd[-1:-1] = ["--download-sections", "*0-00:00:05"]
        print(f"{label}_ytdlp_live_download=running", flush=True)
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace", **hidden_process_options())
        try:
            stdout, stderr = process.communicate(timeout=100)
        except subprocess.TimeoutExpired:
            Downloader._stop_process(process)
            process.communicate(timeout=10)
            print(f"{label}_ytdlp_live_download=timed_out")
            return 1
        lines = stdout.splitlines() + stderr.splitlines()
        files = [line[len(RESULT_PREFIX):].strip() for line in lines if line.startswith(RESULT_PREFIX)]
        if process.returncode != 0 or not files or not Path(files[-1]).is_file():
            print(f"{label}_ytdlp_live_download=failed: {download_error(lines)}")
            return 1
        output = Path(files[-1])
        print(f"{label}_ytdlp_live_download=ok", flush=True)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                "stream=codec_type,width,height", "-of", "json", str(output)],
                               capture_output=True, text=True, encoding="utf-8", timeout=30, **hidden_process_options())
        if probe.returncode != 0:
            print("ffprobe=failed")
            return 1
        streams = json.loads(probe.stdout).get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if not video or not audio:
            print("muxed_video_and_audio=failed")
            return 1
        print(f"muxed_video_and_audio=ok; resolution={video.get('width')}x{video.get('height')}; bytes={output.stat().st_size}")
        print(f"sample_file={output}")
    if not library_verified:
        print("overall=failed; reason=personal_library_not_verified")
        return 1
    print("overall=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
