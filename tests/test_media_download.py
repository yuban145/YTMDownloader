import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import psutil
import requests

from yt_dlp import YoutubeDL
from ytmusicvault.core.auth import normalize_headers
from ytmusicvault.core.database import Database, LEGACY_SCHEMA, media_type_for_download
from ytmusicvault.core.downloader import Downloader, download_error, ytdlp_command
from ytmusicvault.core.ytm_client import YtmClient, ServiceError
from ytmusicvault.core.mv_lookup import find_counterpart
from ytmusicvault.models.song import Song
from ytmusicvault.utils.config import AppConfig
from ytmusicvault.utils.proxy import proxy_description, configure_requests_session, requests_proxy_map


class MediaPolicyTests(unittest.TestCase):
    def test_first_run_defaults_and_legacy_proxy_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            c = AppConfig.load(str(path))
            self.assertEqual((c.proxy_mode, c.download_mode, c.audio_quality), ("manual", "video", "best"))
            self.assertEqual(c.proxy_url, "http://127.0.0.1:7890")
            path.write_text(json.dumps({"proxy_enabled": True, "proxy_host": "localhost", "proxy_port": 3210}))
            c = AppConfig.load(str(path))
            self.assertEqual(c.proxy_mode, "manual")
            self.assertIn(":3210", c.proxy_url)
            path.write_text(json.dumps({"proxy_enabled": False}))
            self.assertEqual(AppConfig.load(str(path)).proxy_mode, "system")

    def test_direct_roundtrip_and_manual_password_encoding(self):
        with tempfile.TemporaryDirectory() as temp:
            c = AppConfig(proxy_mode="direct", _config_path=str(Path(temp) / "config.json"))
            c.save()
            self.assertEqual(AppConfig.load(c._config_path).proxy_url, "")
        c = AppConfig(proxy_mode="manual", proxy_username="a@b", proxy_password="x:/?", proxy_host="::1")
        self.assertEqual(c.proxy_url, "http://a%40b:x%3A%2F%3F@[::1]:7890")
        self.assertNotIn("a%40b", proxy_description(c.proxy_url))

    def test_system_manual_and_direct_cli(self):
        for value in (None, "", "socks5://127.0.0.1:7890"):
            command = Downloader("unused", proxy_url=value)._build_command("https://example.test/video", "out.%(ext)s")
            self.assertIn("--ignore-config", command)
            if value is None:
                self.assertNotIn("--proxy", command)
            else:
                self.assertEqual(command[command.index("--proxy") + 1], value)

    def test_actual_ytdlp_system_proxy_discovery(self):
        with patch("yt_dlp.YoutubeDL.urllib.request.getproxies", return_value={"https": "http://127.0.0.1:19999"}):
            with YoutubeDL({"quiet": True}) as ydl:
                self.assertEqual(ydl.proxies["https"], "http://127.0.0.1:19999")
            with YoutubeDL({"quiet": True, "proxy": ""}) as ydl:
                self.assertEqual(ydl.proxies, {"all": "__noproxy__"})

    def test_mv_lookup_uses_download_proxy_without_touching_library(self):
        from ytmusicvault.core.mv_lookup import resolve_mv
        import threading
        credentials = normalize_headers({"cookie": "__Secure-3PAPISID=synthetic", "x-goog-visitor-id": "offline"})
        with patch("ytmusicvault.utils.proxy.getproxies", return_value={}):
            for value in (None, "", "http://127.0.0.1:1234"):
                with patch("ytmusicvault.core.mv_lookup.YTMusic") as factory:
                    factory.return_value.get_watch_playlist.return_value = {
                        "tracks": [{"videoId": "song", "counterpart": {"videoId": "mv"}}]}
                    self.assertEqual(resolve_mv(Song("song", "Song"), credentials, value, threading.Event()), "mv")
                    session = factory.call_args.kwargs["requests_session"]
                    self.assertEqual(session.trust_env, value is None)
                    self.assertEqual(factory.call_args.kwargs["proxies"],
                                     {"http": value, "https": value} if value else None)

    def test_requests_system_proxy_resolves_windows_settings_explicitly(self):
        system = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890", "no": "localhost"}
        with patch("ytmusicvault.utils.proxy.getproxies", return_value=system):
            self.assertEqual(requests_proxy_map(None), {"http": system["http"], "https": system["https"]})
            session = requests.Session()
            self.assertEqual(configure_requests_session(session, None), {})
            self.assertTrue(session.trust_env)
            self.assertEqual(configure_requests_session(session, ""), {})
            self.assertFalse(session.trust_env)
            self.assertEqual(configure_requests_session(session, "http://127.0.0.1:4567"),
                             {"http": "http://127.0.0.1:4567", "https": "http://127.0.0.1:4567"})
            session.close()
    def test_video_command_preserves_best_streams_and_audio_not_m4a_biased(self):
        command = Downloader("unused")._build_command("url", "out")
        self.assertEqual(command[command.index("-f") + 1], "bv*+ba/b")
        self.assertEqual(command[command.index("--merge-output-format") + 1], "mkv")
        self.assertNotIn("--extract-audio", command)
        self.assertNotIn("--audio-quality", command)
        self.assertNotIn("--recode-video", command)
        audio = Downloader("unused", download_mode="audio")._build_command("url", "out")
        self.assertEqual(audio[audio.index("-f") + 1], "bestaudio/best")
        self.assertEqual(audio[audio.index("--audio-quality") + 1], "0")
        for audio_format in ("flac", "mp3"):
            command = Downloader("unused", download_mode="audio", audio_format=audio_format)._build_command("url", "out")
            self.assertEqual(command[command.index("--audio-format") + 1], audio_format)

    def test_real_selector_chooses_4k_over_1080p_without_codec_filter(self):
        info = {"id": "test", "title": "Test", "extractor": "test", "webpage_url": "https://fixture.invalid/",
                "formats": [
                    {"format_id": "1080", "url": "https://fixture.invalid/1080.mp4", "ext": "mp4", "height": 1080,
                     "width": 1920, "vcodec": "avc1", "acodec": "none", "fps": 60},
                    {"format_id": "2160", "url": "https://fixture.invalid/4k.webm", "ext": "webm", "height": 2160,
                     "width": 3840, "vcodec": "vp9", "acodec": "none", "fps": 30},
                    {"format_id": "opus", "url": "https://fixture.invalid/audio.webm", "ext": "webm",
                     "vcodec": "none", "acodec": "opus", "abr": 160},
                ]}
        with YoutubeDL({"format": "bv*+ba/b", "format_sort": ["res", "fps"], "quiet": True,
                        "no_warnings": True}) as ydl:
            result = ydl.process_video_result(info, download=False)
        self.assertEqual(result["requested_formats"][0]["height"], 2160)
        self.assertEqual(result["requested_formats"][1]["acodec"], "opus")

    def test_filename_has_single_extension_and_identity(self):
        result = Downloader("unused")._build_output_template("folder")
        self.assertEqual(result.count("%(ext)s"), 1)
        self.assertIn("[%(id)s]", result)

    def test_bundled_command_avoids_path_launcher(self):
        self.assertEqual(ytdlp_command()[1:], ["-m", "yt_dlp"])
        with patch("sys.frozen", True, create=True):
            self.assertEqual(ytdlp_command()[1:], ["--yt-dlp"])

    def test_mv_counterpart_is_not_an_unrelated_recommendation(self):
        api = Mock()
        api.get_watch_playlist.return_value = {"tracks": [
            {"videoId": "other", "counterpart": {"videoId": "wrong"}},
            {"videoId": "song", "videoType": "MUSIC_VIDEO_TYPE_ATV", "counterpart": {"videoId": "mv"}}]}
        self.assertEqual(find_counterpart(api, Song("song", "Title")), "mv")
        api.get_watch_playlist.return_value = {"tracks": [{"videoId": "direct", "videoType": "MUSIC_VIDEO_TYPE_OMV"}]}
        self.assertEqual(find_counterpart(api, Song("direct", "MV")), "direct")
        with self.assertRaises(ServiceError):
            find_counterpart(api, Song("missing", "No MV"))

    def test_legacy_audio_migration_and_video_history_remain_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.db"
            audio, video = Path(temp) / "test.m4a", Path(temp) / "test.mkv"
            audio.touch()
            video.touch()
            with sqlite3.connect(path) as conn:
                conn.executescript(LEGACY_SCHEMA)
                conn.execute("INSERT INTO downloads(video_id,file_path,status) VALUES ('song',?,'completed')", (str(audio),))
            conn.close()
            db = Database(str(path))
            self.assertTrue(db.is_downloaded("song", "audio"))
            self.assertFalse(db.is_downloaded("song", "video"))
            db.mark_downloaded("song", file_path=str(video), media_type="video", source_video_id="mv")
            self.assertTrue(db.is_downloaded("song", "audio"))
            self.assertTrue(db.is_downloaded("song", "video"))
            self.assertEqual(db.get_all_records("video")[0][10], "mv")
            db.remove_record("song", "audio")
            db.close()
            db = Database(str(path))
            self.assertFalse(db.is_downloaded("song", "audio"))
            self.assertTrue(db.is_downloaded("song", "video"))
            db.close()

    def test_audio_formats_have_separate_download_history(self):
        self.assertEqual(media_type_for_download("video", "mp3"), "video")
        self.assertEqual(media_type_for_download("audio", "flac"), "audio_flac")
        self.assertEqual(media_type_for_download("audio", "mp3"), "audio_mp3")
        with tempfile.TemporaryDirectory() as temp:
            db = Database(str(Path(temp) / "history.db"))
            flac, mp3 = Path(temp) / "track.flac", Path(temp) / "track.mp3"
            flac.touch()
            mp3.touch()
            db.mark_downloaded("track", file_path=str(flac), media_type="audio_flac")
            db.mark_downloaded("track", file_path=str(mp3), media_type="audio_mp3")
            self.assertTrue(db.is_downloaded("track", "audio_flac"))
            self.assertTrue(db.is_downloaded("track", "audio_mp3"))
            self.assertEqual(len(db.get_all_records()), 2)
            db.close()

    def test_download_errors_do_not_echo_secrets(self):
        message = download_error(["proxy socks5://secret:password@host failed"])
        self.assertIn("代理", message)
        self.assertNotIn("secret", message)
        self.assertNotIn("password", message)

    def test_silent_extractor_is_stopped_instead_of_hanging_forever(self):
        with tempfile.TemporaryDirectory() as temp:
            song = Song("silent", "Silent")
            with patch("ytmusicvault.core.downloader.ytdlp_command",
                       return_value=[sys.executable, "-c", "import time; time.sleep(10)"]), \
                 patch.object(Downloader, "MAX_IDLE_SECONDS", 0.1):
                self.assertFalse(Downloader(temp).download(song))
            self.assertIn("无响应", song.error_msg)

    def test_process_stop_terminates_nested_worker(self):
        code = ("import subprocess,sys,time;"
                "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)']);"
                "print(child.pid,flush=True);time.sleep(20)")
        parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                                  text=True, **({"creationflags": subprocess.CREATE_NO_WINDOW}
                                                if sys.platform == "win32" else {}))
        try:
            child_pid = int(parent.stdout.readline().strip())
            self.assertTrue(psutil.pid_exists(child_pid))
            Downloader._stop_process(parent)
            parent.wait(timeout=5)
            self.assertTrue(not psutil.pid_exists(child_pid) or
                            psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE)
        finally:
            Downloader._stop_process(parent)
            parent.stdout.close()
