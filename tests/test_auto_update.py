import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from auto_update import unpack, verify_package, ASSET_NAME
from updater_runner import install


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def package(self, entries):
        path = self.root / 'update.zip'
        with zipfile.ZipFile(path, 'w') as z:
            for name, data in entries.items():
                z.writestr(name, data)
        return path

    def test_hash_mismatch_refused(self):
        archive = self.package({'TaskListAK/TaskListAK.exe': b'exe'})
        sums = self.root / 'hash.txt'
        sums.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + ASSET_NAME)
        verify_package(archive, sums)
        archive.write_bytes(b'corrupted')
        with self.assertRaises(ValueError): verify_package(archive, sums)

    def test_archive_paths_and_missing_runtime(self):
        for name in ('../outside.exe', 'TaskListAK/../../outside.exe', 'TaskListAK/a:stream', '/TaskListAK/a'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                unpack(self.package({name: b'x'}), self.root / 'extract')
        with self.assertRaises(ValueError):
            unpack(self.package({'TaskListAK/TaskListAK.exe': b'exe'}), self.root / 'extract')

    def test_complete_package(self):
        result = unpack(self.package({'TaskListAK/TaskListAK.exe': b'exe',
                                      'TaskListAK/_internal/a.dll': b'dll'}), self.root / 'extract')
        self.assertEqual((result / '_internal/a.dll').read_bytes(), b'dll')

    def prepare_install(self):
        source, target, backup = [self.root / name for name in ('source', 'target', 'backup')]
        source.mkdir(); target.mkdir()
        (source / 'TaskListAK.exe').write_bytes(b'new')
        (source / 'library.dll').write_bytes(b'new dll')
        (target / 'TaskListAK.exe').write_bytes(b'old')
        (target / 'my-plan.xlsx').write_bytes(b'user plan')
        return source, target, backup

    def test_preserve_user_files_and_backup(self):
        source, target, backup = self.prepare_install()
        install(source, target, backup)
        self.assertEqual((target / 'TaskListAK.exe').read_bytes(), b'new')
        self.assertEqual((backup / 'TaskListAK.exe').read_bytes(), b'old')
        self.assertEqual((target / 'my-plan.xlsx').read_bytes(), b'user plan')

    def test_failed_copy_rolls_back(self):
        source, target, backup = self.prepare_install()
        real_copy = shutil.copy2
        def copy(src, dest):
            if Path(src) == source / 'library.dll':
                raise PermissionError('file locked')
            return real_copy(src, dest)
        with patch('updater_runner.shutil.copy2', side_effect=copy):
            with self.assertRaises(PermissionError): install(source, target, backup)
        self.assertEqual((target / 'TaskListAK.exe').read_bytes(), b'old')
        self.assertEqual((target / 'my-plan.xlsx').read_bytes(), b'user plan')
        self.assertFalse((target / 'library.dll').exists())
