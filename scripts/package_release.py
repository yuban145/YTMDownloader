"""Package explicitly approved release files; never collect local user data."""
import argparse
import hashlib
import importlib.metadata
import platform
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ytmusicvault import __version__


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'release')
    args = parser.parse_args()
    exe = args.exe.resolve()
    if not exe.is_file() or exe.suffix.lower() != '.exe':
        parser.error('A built Windows EXE is required')
    documents = ['README.md', 'GUIDE.md', 'CHANGELOG.md']
    for name in documents:
        if not (ROOT / name).is_file():
            parser.error(f'Missing release document: {name}')
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
                            capture_output=True, text=True).stdout.strip()
    info = [f'YtMusicVault {__version__}', f'Source commit: {commit}',
            'Target: Windows x64', f'Python: {platform.python_version()}',
            'Packaged: ' + datetime.now(timezone(timedelta(hours=8))).isoformat(),
            'Runtime requirements: FFmpeg/ffprobe and Deno or Node.js on PATH',
            f'EXE SHA256: {sha256(exe)}']
    for name in ['PyInstaller', 'PySide6', 'yt-dlp', 'ytmusicapi', 'pypac', 'requests', 'mutagen', 'psutil']:
        info.append(f'{name}: {importlib.metadata.version(name)}')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f'YtMusicVault-{__version__}-windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        bundle.write(exe, 'YtMusicVault.exe')
        for name in documents:
            bundle.write(ROOT / name, name)
        bundle.writestr('BUILD-INFO.txt', '\n'.join(info) + '\n')
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError('Release archive failed its integrity check')
        if set(bundle.namelist()) != {'YtMusicVault.exe', 'BUILD-INFO.txt', *documents}:
            raise RuntimeError('Unexpected release archive contents')
    (output / 'SHA256SUMS.txt').write_text(f'{sha256(archive)}  {archive.name}\n', encoding='utf-8')
    print(f'Release archive: {archive}')
    print(f'Bytes: {archive.stat().st_size}; SHA256: {sha256(archive)}')


if __name__ == '__main__':
    main()
