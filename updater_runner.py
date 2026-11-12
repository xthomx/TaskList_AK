"""Separate Windows helper: wait for exit, install with rollback, restart."""
import argparse
import os
import tempfile
import ctypes
from pathlib import Path
import shutil
import subprocess
import sys
import traceback


def replace_file(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.update-', delete=False) as stream:
        temporary = Path(stream.name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def install(staged, target, backup):
    staged, target, backup = Path(staged), Path(target), Path(backup)
    files = [p for p in staged.rglob('*') if p.is_file()]
    changed = []
    try:
        for source in files:
            relative = source.relative_to(staged)
            dest = target / relative
            saved = backup / relative
            if dest.exists():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, saved)
            existed = dest.exists()
            replace_file(source, dest)
            changed.append((dest, saved, existed))
    except Exception:
        for dest, saved, existed in reversed(changed):
            if existed:
                replace_file(saved, dest)
            elif dest.exists():
                dest.unlink()
        raise


def wait_for_exit(pid):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # process already exited
            return
        raise OSError('Nie można sprawdzić zamknięcia programu.')
    try:
        if kernel.WaitForSingleObject(handle, 120000) != 0:
            raise TimeoutError('Program nie został zamknięty. Aktualizacja anulowana.')
    finally:
        kernel.CloseHandle(handle)


def main():
    if sys.argv[1:] == ['--self-test']:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source', root / 'target'
            source.mkdir(); target.mkdir()
            (source / 'test.txt').write_text('new')
            (target / 'test.txt').write_text('old')
            install(source, target, root / 'backup')
            assert (target / 'test.txt').read_text() == 'new'
            assert (root / 'backup/test.txt').read_text() == 'old'
        return
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--staged', required=True)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    folder = Path(args.staged).resolve().parent.parent
    target = Path(args.target).resolve()
    exited = False
    try:
        wait_for_exit(args.pid)
        exited = True
        install(args.staged, target, folder / 'backup')
        subprocess.Popen([str(target / 'TaskListAK.exe')], cwd=target)
    except Exception:
        log = folder / 'update-error.log'
        log.write_text(traceback.format_exc(), encoding='utf-8')
        ctypes.windll.user32.MessageBoxW(0, 'Aktualizacja nie powiodła się. Szczegóły: ' + str(log), 'TaskList AK', 16)
        # Keep backup and staging for recovery. Never erase user plan files.
        if exited:
            subprocess.Popen([str(target / 'TaskListAK.exe')], cwd=target)


if __name__ == '__main__':
    main()
