"""Local tags for audio/MP4 and lossless MKV metadata remux."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests
from mutagen.mp4 import MP4, MP4Cover
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (APIC, TALB, TDRC, TIT2, TPE1, TPE2, TRCK, ID3, ID3NoHeaderError)
from .downloader import hidden_process_options
from ..utils.proxy import configure_requests_session


class MetadataWriter:
    def __init__(self, proxy_url=None):
        self.proxy_url = proxy_url

    def write(self, song, file_path=None, cancel_event=None):
        path = file_path or song.file_path
        if not path or not os.path.isfile(path):
            return False
        if cancel_event and cancel_event.is_set():
            return False
        try:
            if Path(path).suffix.lower() == ".mkv":
                return self._write_mkv(song, path, cancel_event)
            suffix = Path(path).suffix.lower()
            if suffix == ".flac":
                return self._write_flac(song, path, cancel_event)
            if suffix == ".mp3":
                return self._write_mp3(song, path, cancel_event)
            audio = MP4(path)
            if audio.tags is None:
                audio.add_tags()
            for key, value in {"\xa9nam": song.title, "\xa9ART": song.artist,
                               "\xa9alb": song.album, "aART": song.artist}.items():
                if value:
                    audio.tags[key] = [value]
            if song.track_number > 0:
                audio.tags["trkn"] = [(song.track_number, 0)]
            if song.year > 0:
                audio.tags["\xa9day"] = [str(song.year)]
            if song.thumbnail:
                cover = self._download_cover(song.thumbnail)
                if cover:
                    fmt = MP4Cover.FORMAT_PNG if cover.startswith(b"\x89PNG") else MP4Cover.FORMAT_JPEG
                    audio.tags["covr"] = [MP4Cover(cover, imageformat=fmt)]
            if cancel_event and cancel_event.is_set():
                return False
            audio.save()
            return True
        except Exception:
            return False

    def _write_flac(self, song, path, cancel_event):
        audio = FLAC(path)
        audio["title"] = song.title
        audio["artist"] = song.artist
        audio["albumartist"] = song.artist
        if song.album:
            audio["album"] = song.album
        if song.track_number > 0:
            audio["tracknumber"] = str(song.track_number)
        if song.year > 0:
            audio["date"] = str(song.year)
        if song.thumbnail:
            cover = self._download_cover(song.thumbnail)
            if cover:
                picture = Picture()
                picture.data = cover
                picture.type = 3
                picture.mime = "image/png" if cover.startswith(b"\x89PNG") else "image/jpeg"
                audio.clear_pictures()
                audio.add_picture(picture)
        if cancel_event and cancel_event.is_set():
            return False
        audio.save()
        return True

    def _write_mp3(self, song, path, cancel_event):
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.add(TIT2(encoding=3, text=song.title))
        tags.add(TPE1(encoding=3, text=song.artist))
        tags.add(TPE2(encoding=3, text=song.artist))
        if song.album:
            tags.add(TALB(encoding=3, text=song.album))
        if song.track_number > 0:
            tags.add(TRCK(encoding=3, text=str(song.track_number)))
        if song.year > 0:
            tags.add(TDRC(encoding=3, text=str(song.year)))
        if song.thumbnail:
            cover = self._download_cover(song.thumbnail)
            if cover:
                tags.add(APIC(encoding=3, mime="image/png" if cover.startswith(b"\x89PNG") else "image/jpeg",
                              type=3, desc="Cover", data=cover))
        if cancel_event and cancel_event.is_set():
            return False
        tags.save(path)
        return True

    def _write_mkv(self, song, path, cancel_event):
        # Keep all streams, chapters, attachments and existing tags. Stream copy
        # avoids quality loss; replace the original only after successful remux.
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return False
        fd, output = tempfile.mkstemp(prefix=".ytmv-tags-", suffix=".mkv", dir=str(Path(path).parent))
        os.close(fd)
        process = None
        try:
            command = [ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-i", path,
                       "-map", "0", "-map_metadata", "0", "-map_chapters", "0", "-c", "copy"]
            for key, value in {"title": song.title, "artist": song.artist, "album": song.album,
                               "album_artist": song.artist,
                               "track": str(song.track_number) if song.track_number else "",
                               "date": str(song.year) if song.year else ""}.items():
                if value:
                    command += ["-metadata", f"{key}={value}"]
            command.append(output)
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       **hidden_process_options())
            while True:
                if cancel_event and cancel_event.is_set():
                    process.kill()
                    process.wait()
                    return False
                try:
                    code = process.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if code != 0 or not os.path.getsize(output):
                return False
            os.replace(output, path)
            return True
        finally:
            if process and process.poll() is None:
                process.kill()
                process.wait()
            if os.path.exists(output):
                os.unlink(output)

    def _download_cover(self, url):
        with requests.Session() as session:
            configure_requests_session(session, self.proxy_url)
            for candidate in dict.fromkeys((_upgrade_thumbnail_url(url), url)):
                try:
                    with session.get(candidate, timeout=(10, 15), stream=True) as response:
                        response.raise_for_status()
                        data = bytearray()
                        for chunk in response.iter_content(64 * 1024):
                            data.extend(chunk)
                            if len(data) > 5 * 1024 * 1024:
                                break
                        if len(data) <= 5 * 1024 * 1024 and (
                            data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG")
                        ):
                            return bytes(data)
                except requests.RequestException:
                    continue
        return None


def _upgrade_thumbnail_url(url):
    return re.sub(r"=w\d+(?:-h\d+)?", "=w1200-h1200", url)
