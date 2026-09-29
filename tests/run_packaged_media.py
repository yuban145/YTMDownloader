"""Run the same real media integration checks through the frozen EXE worker."""
import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_local_media_integration import LocalMediaTests

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    args = parser.parse_args()
    exe = Path(args.exe).resolve()
    if not exe.is_file():
        parser.error("Packaged executable not found")
    with patch("ytmusicvault.core.downloader.ytdlp_command", return_value=[str(exe), "--yt-dlp"]):
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(LocalMediaTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
