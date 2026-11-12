from pathlib import Path
import tempfile
import unittest

import xlsx_format
from main import Api
from storage import Storage, fingerprint


def make(title, people=(('p1', 'Kowalski Jan'),)):
    return {'people': [{'id': i, 'name': n} for i, n in people],
            'tasks': [{'id': 't1', 'title': title, 'date': '2026-11-12', 'start': '10:00', 'end': '11:00',
                       'priority': 2, 'status': 'progress', 'progress': 50, 'notes': 'n',
                       'assignees': [people[0][0]] if people else []}]}


class RememberFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = Storage(self.root / 'dane')
        self.api = Api(self.storage)
        self.xlsx = self.root / 'zadania.xlsx'

    def link(self, data):
        self.xlsx.write_bytes(xlsx_format.dumps(data))
        self.storage.save_data(data)
        self.storage.set_prefs(last_xlsx=str(self.xlsx), xlsx_fp=fingerprint(data))

    def titles(self, state):
        return [t['title'] for t in state['tasks']]

    def test_fingerprint_ignores_ids_but_sees_changes(self):
        a, b = make('A'), make('A', people=(('zzz', 'Kowalski Jan'),))
        b['tasks'][0]['id'] = 'inne'
        self.assertEqual(fingerprint(a), fingerprint(b))
        self.assertNotEqual(fingerprint(a), fingerprint(make('B')))

    def test_clean_working_copy_loads_file_at_start(self):
        self.link(make('Stary'))
        self.xlsx.write_bytes(xlsx_format.dumps(make('Zmieniony w Excelu')))   # plik edytowany poza programem
        state = self.api.load_state()
        self.assertEqual(self.titles(state), ['Zmieniony w Excelu'])
        self.assertEqual(state['file']['name'], 'zadania.xlsx')
        self.assertFalse(state['file']['dirty'])
        self.assertEqual(self.titles(self.api.load_state()), ['Zmieniony w Excelu'])

    def test_unsaved_changes_keep_working_copy(self):
        self.link(make('W pliku'))
        self.api.save_data(make('Zmiana w programie'))
        state = self.api.load_state()
        self.assertEqual(self.titles(state), ['Zmiana w programie'])
        self.assertIn('niezapisane', state['warning'])
        self.assertTrue(state['file']['dirty'])

    def test_save_to_remembered_file_clears_dirty_and_persists(self):
        self.link(make('A'))
        self.assertTrue(self.api.save_data(make('B'))['dirty'])
        info = self.api.save_xlsx(make('B'))
        self.assertFalse(info['dirty'])
        self.assertEqual(self.titles(xlsx_format.loads(self.xlsx.read_bytes())), ['B'])
        self.assertFalse(self.api.save_data(make('B'))['dirty'])
        self.assertEqual(self.titles(self.api.load_state()), ['B'])

    def test_missing_file_falls_back_without_sample_data(self):
        self.link(make('Kopia'))
        self.xlsx.unlink()
        state = self.api.load_state()
        self.assertEqual(self.titles(state), ['Kopia'])
        self.assertIn('Nie można otworzyć', state['warning'])
        self.storage.tasks_path.unlink()
        state = self.api.load_state()
        self.assertEqual(state['tasks'], [])          # nie null, więc UI nie wstawi przykładów
        self.assertIn('Nie można otworzyć', state['warning'])

    def test_open_is_remembered_only_after_accept(self):
        self.xlsx.write_bytes(xlsx_format.dumps(make('Z pliku')))
        self.api._pick_open = lambda label: self.xlsx
        opened = self.api.open_xlsx()
        self.assertEqual(self.storage.get_prefs()['last_xlsx'], '')
        info = self.api.accept_xlsx(opened['token'])
        self.assertEqual(info['name'], 'zadania.xlsx')
        self.assertFalse(info['dirty'])
        self.assertEqual(self.storage.get_prefs()['last_xlsx'], str(self.xlsx.resolve()))
        with self.assertRaises(ValueError):
            self.api.accept_xlsx(opened['token'])

    def test_no_linked_file_behaves_as_before(self):
        state = self.api.load_state()
        self.assertIsNone(state['tasks'])
        self.assertIsNone(state['file'])
        self.assertEqual(self.api.save_data(make('A')), {'count': 1, 'dirty': False})
