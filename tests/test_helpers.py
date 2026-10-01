"""Windows playlist directory safety."""
import tempfile
import unittest
from pathlib import Path

from ytmusicvault.utils.helpers import safe_filename


class FilenameTests(unittest.TestCase):
    def test_playlist_names_stay_in_download_directory(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ('..', '.', '...', '../outside', '..\\outside', 'CON', 'NUL.txt',
                         'COM1', 'LPT².txt', 'trailing. ', 'a\x00b', '', 'x' * 201):
                with self.subTest(name=name):
                    safe = safe_filename(name)
                    target = Path(root) / safe
                    self.assertEqual(target.resolve().parent, Path(root).resolve())
                    self.assertTrue(safe)
                    self.assertLessEqual(len(safe), 200)
                    self.assertFalse(safe.endswith(('.', ' ')))
                    target.mkdir(exist_ok=True)

    def test_normal_unicode_titles_are_preserved(self):
        self.assertEqual(safe_filename('  我的歌单  '), '我的歌单')


if __name__ == '__main__':
    unittest.main()
