"""Corrupt preference recovery and atomic persistence regressions."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ytmusicvault.utils.config import AppConfig


class ConfigTests(unittest.TestCase):
    def test_invalid_types_and_ranges_do_not_reach_qt_or_download_workers(self):
        invalid = {'download_dir': None, 'proxy_host': [], 'proxy_password': {},
                   'proxy_port': 999999, 'concurrent_downloads': True, 'max_retries': -1,
                   'retry_delay': '5', 'window_width': 10**50, 'window_height': None,
                   'create_playlist_folders': 'false', 'proxy_mode': [],
                   'audio_format': None, 'filename_template': '  ', '_config_path': 'wrong'}
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'config.json'
            path.write_text(json.dumps(invalid), encoding='utf-8')
            loaded, defaults = AppConfig.load(str(path)), AppConfig()
            for field in invalid:
                if not field.startswith('_'):
                    self.assertEqual(getattr(loaded, field), getattr(defaults, field), field)
            self.assertEqual(loaded._config_path, str(path))
            self.assertEqual(loaded.proxy_url, defaults.proxy_url)

    def test_non_object_and_invalid_utf8_configs_use_defaults(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'config.json'
            for raw in (b'null', b'[]', b'1', b'\xff\xfe'):
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    self.assertEqual(AppConfig.load(str(path)).download_dir, AppConfig().download_dir)

    def test_failed_save_keeps_previous_complete_preferences(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'config.json'
            config = AppConfig(_config_path=str(path))
            config.save()
            before = path.read_bytes()
            config.proxy_mode = 'direct'
            with patch('ytmusicvault.utils.config.os.replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    config.save()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(root).iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
