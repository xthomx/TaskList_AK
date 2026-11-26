import json
from pathlib import Path
import tempfile
import unittest

from main import Api
from storage import Storage


def T(i, title, cal='local', who=()):
    return {'id': i, 'title': title, 'date': '2026-11-12', 'end_date': '2026-11-12', 'start': '', 'end': '',
            'priority': 1, 'status': 'pending', 'progress': 0, 'notes': '', 'assignees': list(who), 'calendar': cal}


def D(*tasks, people=(('p1', 'Kowalski Jan'), ('p2', 'Nowak Anna'))):
    return {'people': [{'id': i, 'name': n} for i, n in people], 'tasks': list(tasks)}


class LocalJsonTests(unittest.TestCase):
    """Plik lokalny JSON (np. w OneDrive): jeden użytkownik, wiele urządzeń."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.api = Api(Storage(self.root / 'dane'))
        self.file = self.root / 'OneDrive' / 'prywatny.json'
        self.file.parent.mkdir()
        self.api._pick_save = lambda *a: self.file

    def test_create_writes_only_local_tasks_but_all_local_people(self):
        data = D(T('a', 'Mój', 'local', ['p1']), T('b', 'Zespół', 'group', ['p2']))
        info = self.api.local_create(data)
        self.assertEqual(info['name'], 'prywatny.json')
        doc = json.loads(self.file.read_text('utf-8'))
        self.assertEqual([t['title'] for t in doc['tasks']], ['Mój'])
        self.assertIn('Kowalski Jan', [p['name'] for p in doc['people']])

    def test_changes_from_other_device_are_merged_and_group_tasks_untouched(self):
        data = D(T('a', 'Mój', 'local'), T('g', 'Zespół', 'group'))
        self.api.local_create(data)
        doc = json.loads(self.file.read_text('utf-8'))
        doc['tasks'].append(T('n', 'Z telefonu', 'local'))
        self.file.write_text(json.dumps(doc), encoding='utf-8')
        self.assertTrue(self.api.local_check()['changed'])
        out = self.api.local_sync(data)
        self.assertEqual(sorted(t['title'] for t in out['tasks'] if t['calendar'] == 'local'), ['Mój', 'Z telefonu'])
        self.assertEqual([t['title'] for t in out['tasks'] if t['calendar'] == 'group'], ['Zespół'])
        self.assertFalse(self.api.local_check()['changed'])

    def test_sync_files_pushes_local_edit_and_keeps_roster(self):
        data = D(T('a', 'Mój', 'local'))
        self.api.local_create(data)
        edited = D(T('a', 'Zmieniony', 'local'))
        out = self.api.sync_files(edited)
        self.assertIsNotNone(out['local_result'])
        doc = json.loads(self.file.read_text('utf-8'))
        self.assertEqual([t['title'] for t in doc['tasks']], ['Zmieniony'])
        self.assertEqual(sorted(p['name'] for p in doc['people']), ['Kowalski Jan', 'Nowak Anna'])

    def test_disconnect_clears_link(self):
        self.api.local_create(D(T('a', 'Mój', 'local')))
        self.assertTrue(self.api.local_disconnect())
        self.assertEqual(self.api._storage.get_prefs()['local_path'], '')
        self.assertEqual(self.api.local_check(), {'changed': False, 'offline': False})


if __name__ == '__main__':
    unittest.main()
