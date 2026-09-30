"""Real yt-dlp + FFmpeg tests against a tiny local fixture; never access YouTube."""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from mutagen.flac import FLAC
from mutagen.id3 import ID3

from ytmusicvault.core.downloader import Downloader, hidden_process_options
from ytmusicvault.core.metadata import MetadataWriter
from ytmusicvault.models.song import Song


class LocalMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise unittest.SkipTest("FFmpeg/ffprobe unavailable")
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.sample = cls.root / "sample.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=10",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                        "-t", "0.5", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(cls.sample)],
                       check=True, capture_output=True, timeout=30, **hidden_process_options())
        cls.data = cls.sample.read_bytes()
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(cls.sample),
                        "-map", "0:v", "-map", "0:a", "-c", "copy", "-f", "dash", "-seg_duration", "1",
                        str(cls.root / "sample.mpd")], cwd=cls.root, check=True, capture_output=True, timeout=30,
                       **hidden_process_options())
        cls.requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_HEAD(self):
                self.serve(False)

            def do_GET(self):
                self.serve(True)

            def serve(self, send_body):
                cls.requests.append(self.path)
                name = Path(urlsplit(self.path).path).name
                asset = cls.root / name
                if not asset.is_file():
                    self.send_error(404)
                    return
                data = asset.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/dash+xml" if name.endswith(".mpd") else "video/mp4")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if send_body:
                    self.wfile.write(data)

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def probe(self, path):
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                                capture_output=True, text=True, encoding="utf-8", check=True, timeout=15,
                                **hidden_process_options())
        return json.loads(result.stdout)

    def download_fixture(self, mode, proxy_url, proxy_env=False, dash=False, audio_format="m4a"):
        downloader = Downloader(str(self.root / (mode + str(proxy_env) + str(dash) + audio_format)),
                                download_mode=mode, proxy_url=proxy_url, audio_format=audio_format)
        original = downloader._build_command
        port = self.server.server_port
        target = "http://fixture.invalid/sample.mp4" if proxy_env else f"http://127.0.0.1:{port}/sample.mp4"
        if dash:
            target = target.replace("sample.mp4", "sample.mpd")
        # Replace ONLY the upstream URL. Run the application's real process,
        # format, proxy, output, progress and metadata options unchanged.
        downloader._build_command = lambda url, output: original(target, output)
        song = Song("fixture", "本地测试 MV", artist="Test Artist", album="Integration", track_number=1, year=2026)
        env = {"http_proxy": f"http://127.0.0.1:{port}", "https_proxy": f"http://127.0.0.1:{port}",
               "all_proxy": f"http://127.0.0.1:{port}", "no_proxy": ""}
        with patch.dict(os.environ, env):
            self.assertTrue(downloader.download(song), song.error_msg)
        return song

    def test_video_system_proxy_real_download_remux_and_metadata(self):
        self.requests.clear()
        song = self.download_fixture("video", None, proxy_env=True)
        self.assertTrue(any(x.startswith("http://fixture.invalid/") for x in self.requests))
        self.assertTrue(song.file_path.endswith(".mkv"))
        before = self.probe(song.file_path)
        self.assertTrue(MetadataWriter(proxy_url="").write(song))
        after = self.probe(song.file_path)
        self.assertEqual([s["codec_name"] for s in before["streams"]], [s["codec_name"] for s in after["streams"]])
        self.assertEqual({s["codec_type"] for s in after["streams"]}, {"video", "audio"})
        tags = {k.lower(): v for k, v in after["format"]["tags"].items()}
        self.assertEqual(tags["title"], song.title)
        self.assertEqual(tags["artist"], song.artist)

    def test_video_pac_routes_real_ytdlp_download(self):
        self.requests.clear()
        pac = self.root / "media.pac"
        pac.write_text('function FindProxyForURL(url, host) { return "PROXY 127.0.0.1:'
                       + str(self.server.server_port) + '; DIRECT"; }')
        song = self.download_fixture("video", "pac:" + str(pac), proxy_env=True)
        self.assertTrue(any(x.startswith("http://fixture.invalid/") for x in self.requests))
        self.assertEqual({s["codec_type"] for s in self.probe(song.file_path)["streams"]}, {"video", "audio"})

    def test_audio_direct_connection_overrides_proxy_environment(self):
        self.requests.clear()
        song = self.download_fixture("audio", "")
        self.assertTrue(self.requests)
        self.assertTrue(all(x.startswith("/") for x in self.requests))
        self.assertTrue(song.file_path.endswith(".m4a"))
        self.assertTrue(MetadataWriter(proxy_url="").write(song))
        result = self.probe(song.file_path)
        self.assertEqual({s["codec_type"] for s in result["streams"]}, {"audio"})
        self.assertEqual(result["format"]["tags"]["title"], song.title)

    def test_separate_dash_video_and_audio_merge_into_mkv(self):
        self.requests.clear()
        song = self.download_fixture("video", "", dash=True)
        self.assertTrue(song.file_path.endswith(".mkv"))
        self.assertTrue(any("chunk-stream0" in path for path in self.requests))
        self.assertTrue(any("chunk-stream1" in path for path in self.requests))
        result = self.probe(song.file_path)
        self.assertEqual({s["codec_type"] for s in result["streams"]}, {"video", "audio"})

    def test_flac_and_mp3_downloads_receive_author_metadata(self):
        for audio_format in ("flac", "mp3"):
            song = self.download_fixture("audio", "", audio_format=audio_format)
            self.assertTrue(song.file_path.endswith("." + audio_format), song.file_path)
            self.assertTrue(MetadataWriter(proxy_url="").write(song))
            if audio_format == "flac":
                tags = FLAC(song.file_path).tags
                self.assertEqual(tags["artist"], ["Test Artist"])
                self.assertEqual(tags["albumartist"], ["Test Artist"])
                self.assertEqual(tags["title"], ["本地测试 MV"])
            else:
                tags = ID3(song.file_path)
                self.assertEqual(tags["TPE1"].text, ["Test Artist"])
                self.assertEqual(tags["TPE2"].text, ["Test Artist"])
                self.assertEqual(tags["TIT2"].text, ["本地测试 MV"])
