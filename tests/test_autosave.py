import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import storage
import xlsx_format
from main import Api
from storage import Storage


def T(i, title, cal='local'):
    return {'id': i, 'title': title, 'date': '2026-11-12', 'end_date': '2026-11-12', 'start': '', 'end': '',
            'priority': 1, 'status': 'pending', 'progress': 0, 'notes': '', 'assignees': [], 'calendar': cal}


def D(*tasks):
    return {'people': [], 'tasks': list(tasks)}


class AutosaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = Storage(self.root / 'dane')
        self.api = Api(self.storage)
        self.xlsx = self.root / 'moje.xlsx'
        self.gfile = self.root / 'grupowy.json'

    def link_excel(self, data):
        self.api._pick_save = lambda *a: self.xlsx
        self.api.save_xlsx(data, as_new=True)

    def link_group(self, data):
        self.api._pick_save = lambda *a: self.gfile
        self.api.group_create(data)

    def test_changes_are_written_to_excel_without_pressing_save(self):
        self.link_excel(D(T('a', 'Stare')))
        out = self.api.sync_files(D(T('a', 'Stare'), T('b', 'Nowe')))
        self.assertEqual(out['errors'], {})
        self.assertEqual(sorted(t['title'] for t in xlsx_format.loads(self.xlsx.read_bytes())['tasks']), ['Nowe', 'Stare'])
        self.assertFalse(out['file']['dirty'])
        self.assertEqual(self.api.sync_files(D(T('a', 'Stare'), T('b', 'Nowe')))['errors'], {})   # bez zmian: nic do zapisu

    def test_group_changes_are_written_and_merged_automatically(self):
        self.link_group(D(T('g', 'Wspólne', 'group')))
        doc = json.loads(self.gfile.read_text('utf-8'))
        doc['tasks'].append(T('k', 'Od kolegi', 'group'))
        self.gfile.write_text(json.dumps(doc), encoding='utf-8')
        out = self.api.sync_files(D(T('g', 'Wspólne', 'group'), T('m', 'Moje', 'group')))
        self.assertEqual(out['group_result']['report']['added'], ['Od kolegi'])
        self.assertEqual(sorted(t['title'] for t in json.loads(self.gfile.read_text('utf-8'))['tasks']), ['Moje', 'Od kolegi', 'Wspólne'])
        self.assertFalse(out['group']['dirty'])

    def test_excel_locked_reports_error_and_retries_later(self):
        self.link_excel(D(T('a', 'Stare')))
        with mock.patch('os.replace', side_effect=PermissionError), mock.patch('main.time.sleep'):
            out = self.api.sync_files(D(T('a', 'Zmienione')))
        self.assertIn('Excel', out['errors']['file'])
        self.assertTrue(out['file']['dirty'])
        out = self.api.sync_files(D(T('a', 'Zmienione')))               # plik znów dostępny
        self.assertEqual(out['errors'], {})
        self.assertEqual([t['title'] for t in xlsx_format.loads(self.xlsx.read_bytes())['tasks']], ['Zmienione'])

    def test_group_file_read_by_someone_else_is_still_written(self):
        self.link_group(D(T('g', 'Wspólne', 'group')))
        with mock.patch.object(Api, '_swap', side_effect=PermissionError), mock.patch('main.time.sleep') as sleep:
            out = self.api.sync_files(D(T('g', 'Wspólne', 'group'), T('m', 'Moje', 'group')))
        self.assertEqual(out['errors'], {})                         # podmiana zablokowana, zapis w miejscu przeszedł
        self.assertGreaterEqual(sleep.call_count, 4)                # najpierw ponowienia podmiany
        self.assertEqual(sorted(t['title'] for t in json.loads(self.gfile.read_text('utf-8'))['tasks']), ['Moje', 'Wspólne'])
        self.assertFalse(list(self.gfile.parent.glob('.grupowy-*')))   # brak śmieci po pliku tymczasowym

    def test_excel_changed_outside_is_not_overwritten(self):
        self.link_excel(D(T('a', 'Stare')))
        self.xlsx.write_bytes(xlsx_format.dumps(D(T('x', 'Edytowane w Excelu'))))
        out = self.api.sync_files(D(T('a', 'Moja zmiana')))
        self.assertIn('poza programem', out['errors']['file'])
        self.assertEqual([t['title'] for t in xlsx_format.loads(self.xlsx.read_bytes())['tasks']], ['Edytowane w Excelu'])

    def test_group_unreachable_does_not_raise(self):
        self.link_group(D(T('g', 'Wspólne', 'group')))
        self.gfile.unlink()
        self.gfile.parent.joinpath('x').mkdir()
        with mock.patch.object(Api, '_read_group', side_effect=OSError('brak sieci')):
            out = self.api.sync_files(D(T('g', 'Zmienione', 'group')))
        self.assertIn('brak sieci', out['errors']['group'])
        self.assertTrue(out['group']['dirty'])


class LocationTests(unittest.TestCase):
    def test_data_and_logs_live_next_to_the_program_and_legacy_data_is_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, old = Path(tmp) / 'app', Path(tmp) / 'stare'
            app.mkdir(); old.mkdir()
            (old / 'tasks.json').write_text('{"people":[],"tasks":[]}', encoding='utf-8')
            with mock.patch.object(storage, 'app_dir', return_value=app), mock.patch.object(storage, 'legacy_dir', return_value=old):
                folder = storage.data_dir()
                self.assertEqual(folder, app / 'dane')
                self.assertTrue((folder / 'tasks.json').is_file())          # skopiowane z dawnej lokalizacji
                self.assertTrue((old / 'tasks.json').is_file())             # oryginał zostaje
                (folder / 'tasks.json').write_text('nowe', encoding='utf-8')
                storage.data_dir()
                self.assertEqual((folder / 'tasks.json').read_text(encoding='utf-8'), 'nowe')   # nie nadpisuje
                self.assertEqual(storage.log_dir(), app / 'logi')

    def test_read_only_program_folder_falls_back_to_legacy_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / 'stare'
            with mock.patch.object(storage, 'app_dir', return_value=Path(tmp) / 'app'), \
                 mock.patch.object(storage, 'legacy_dir', return_value=old), \
                 mock.patch.object(storage, '_writable', return_value=False):
                self.assertEqual(storage.data_dir(), old)


if __name__ == '__main__':
    unittest.main()
