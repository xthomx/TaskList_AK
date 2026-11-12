"""Download a verified release to staging. Never overwrite a running application."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from urllib.request import Request, urlopen
import zipfile
from updates import ASSET_NAME, check_updates, version_tuple

MAX_DOWNLOAD = 300 * 1024 * 1024
MAX_EXPANDED = 1000 * 1024 * 1024


def download(url, path, limit):
    request = Request(url, headers={'User-Agent': 'TaskListAK-Updater'})
    size = 0
    with urlopen(request, timeout=60) as source, Path(path).open('wb') as dest:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError('Przekroczono rozmiar aktualizacji.')
            dest.write(chunk)


def verify_package(archive, checksums):
    matches = re.findall(r'^([a-fA-F0-9]{64})\s+\*?' + re.escape(ASSET_NAME) + r'\s*$',
                         Path(checksums).read_text(encoding='utf-8-sig'), re.M)
    if len(matches) != 1:
        raise ValueError('Brak jednoznacznej sumy SHA256 wydania.')
    with Path(archive).open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != matches[0].lower():
        raise ValueError('Suma SHA256 paczki jest niezgodna. Aktualizacja przerwana.')


def unpack(archive, destination):
    destination = Path(destination)
    names = set()
    with zipfile.ZipFile(archive) as source:
        items = source.infolist()
        if len(items) > 20000 or sum(i.file_size for i in items) > MAX_EXPANDED:
            raise ValueError('Paczka aktualizacji jest zbyt duża.')
        for info in items:
            name = info.filename.replace('\\', '/')
            parts = PurePosixPath(name).parts
            if (not parts or parts[0] != 'TaskListAK' or any(p in ('..', '.') or ':' in p or p.endswith((' ', '.')) for p in parts)
                    or stat.S_ISLNK(info.external_attr >> 16) or name.casefold() in names):
                raise ValueError('Nieprawidłowa ścieżka w paczce aktualizacji.')
            names.add(name.casefold())
        source.extractall(destination)
    root = destination / 'TaskListAK'
    if not (root / 'TaskListAK.exe').is_file() or not (root / '_internal').is_dir():
        raise ValueError('Niekompletna paczka programu.')
    return root


def prepare():
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        raise RuntimeError('Instalacja aktualizacji jest dostępna w wersji EXE dla Windows.')
    result = check_updates()
    if result.get('status') != 'available':
        raise RuntimeError(result.get('message', 'Brak gotowej nowszej wersji.'))
    tag = result['latest']
    version_tuple(tag)
    target = Path(sys.executable).resolve().parent
    helper = target / 'TaskListUpdater.exe'
    if not helper.is_file():
        raise RuntimeError('Brak modułu aktualizacji. Zainstaluj pełną paczkę programu.')
    # Fail before closing if the installation directory is not writable.
    with tempfile.TemporaryFile(dir=target):
        pass
    folder = Path(tempfile.mkdtemp(prefix='TaskListAK-update-'))
    try:
        base = 'https://github.com/xthomx/TaskList_AK/releases/download/' + tag + '/'
        archive, sums = folder / ASSET_NAME, folder / 'SHA256SUMS.txt'
        download(base + ASSET_NAME, archive, MAX_DOWNLOAD)
        download(base + 'SHA256SUMS.txt', sums, 65536)
        verify_package(archive, sums)
        staged = unpack(archive, folder / 'staged')
        runner = folder / 'TaskListUpdater.exe'
        shutil.copy2(helper, runner)
        return {'folder': str(folder), 'staged': str(staged), 'target': str(target),
                'runner': str(runner), 'version': tag}
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
