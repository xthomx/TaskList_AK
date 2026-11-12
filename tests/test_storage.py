import json
from pathlib import Path
import tempfile
import unittest
from storage import Storage, validate_data


def task(**kw):
    base = {'id': 'a', 'title': 'Zadanie', 'date': '2026-11-12', 'start': '10:00', 'end': '11:00',
            'priority': 2, 'done': False, 'notes': '', 'assignees': []}
    base.update(kw)
    return base


def data(*tasks, people=()):
    return {'people': list(people), 'tasks': list(tasks)}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Storage(Path(self.temp.name) / 'dane')

    def test_roundtrip_with_polish_characters(self):
        self.assertIsNone(self.store.load_data()['data'])
        self.store.save_data(data(task(title='Zażółć gęślą jaźń')))
        self.assertEqual(self.store.load_data()['data']['tasks'][0]['title'], 'Zażółć gęślą jaźń')

    def test_invalid_tasks_refused(self):
        for bad in (task(date='12.11.2026'), task(start='25:00'), task(priority=9), task(title=' '),
                    task(id=''), task(assignees=['nieznany'])):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_data(data(bad))
        with self.assertRaises(ValueError):
            validate_data(data(task(), task()))

    def test_all_day_task_drops_end(self):
        self.assertEqual(validate_data(data(task(start='', end='11:00')))['tasks'][0]['end'], '')

    def test_people_and_assignees(self):
        people = [{'id': 'p1', 'name': ' Anna Kowalska '}, {'id': 'p2', 'name': 'Jan'}]
        clean = validate_data(data(task(assignees=['p1', 'p2', 'p1']), people=people))
        self.assertEqual(clean['people'][0]['name'], 'Anna Kowalska')
        self.assertEqual(clean['tasks'][0]['assignees'], ['p1', 'p2'])
        for bad in ([{'id': 'p1', 'name': ''}], [{'id': 'p1', 'name': 'A'}, {'id': 'p1', 'name': 'B'}]):
            with self.assertRaises(ValueError):
                validate_data(data(people=bad))

    def test_legacy_list_format_from_v1_0(self):
        legacy = [{k: v for k, v in task().items() if k != 'assignees'}]
        clean = validate_data(legacy)
        self.assertEqual(clean['people'], [])
        self.assertEqual(clean['tasks'][0]['assignees'], [])
        self.store.folder.mkdir(parents=True)
        self.store.tasks_path.write_text(json.dumps(legacy), encoding='utf-8')
        self.assertEqual(len(self.store.load_data()['data']['tasks']), 1)

    def test_damaged_file_is_set_aside_not_overwritten(self):
        self.store.folder.mkdir(parents=True)
        self.store.tasks_path.write_text('{nie json', encoding='utf-8')
        result = self.store.load_data()
        self.assertIsNone(result['data'])
        self.assertTrue(result['warning'])
        self.assertFalse(self.store.tasks_path.exists())
        self.assertEqual(len(list(self.store.folder.glob('tasks.uszkodzony-*.json'))), 1)

    def test_failed_save_keeps_previous_data(self):
        self.store.save_data(data(task()))
        with self.assertRaises(ValueError):
            self.store.save_data(data(task(date='zła')))
        self.assertEqual(json.loads(self.store.tasks_path.read_text('utf-8'))['tasks'][0]['id'], 'a')

    def test_view_preference(self):
        self.assertEqual(self.store.get_prefs()['view'], 'month')
        self.store.set_view('week')
        self.assertEqual(self.store.get_prefs()['view'], 'week')
        with self.assertRaises(ValueError):
            self.store.set_view('rok')
