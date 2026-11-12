import json
from pathlib import Path
import tempfile
import unittest
from storage import Storage, validate_tasks


def task(**kw):
    base = {'id': 'a', 'title': 'Zadanie', 'date': '2026-11-12', 'start': '10:00', 'end': '11:00',
            'priority': 2, 'done': False, 'notes': ''}
    base.update(kw)
    return base


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Storage(Path(self.temp.name) / 'dane')

    def test_roundtrip_with_polish_characters(self):
        self.assertIsNone(self.store.load_tasks()['tasks'])
        self.store.save_tasks([task(title='Zażółć gęślą jaźń')])
        self.assertEqual(self.store.load_tasks()['tasks'][0]['title'], 'Zażółć gęślą jaźń')

    def test_invalid_tasks_refused(self):
        for bad in (task(date='12.11.2026'), task(start='25:00'), task(priority=9), task(title=' '),
                    task(id='')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_tasks([bad])
        with self.assertRaises(ValueError):
            validate_tasks([task(), task()])

    def test_all_day_task_drops_end(self):
        self.assertEqual(validate_tasks([task(start='', end='11:00')])[0]['end'], '')

    def test_damaged_file_is_set_aside_not_overwritten(self):
        self.store.folder.mkdir(parents=True)
        self.store.tasks_path.write_text('{nie json', encoding='utf-8')
        result = self.store.load_tasks()
        self.assertIsNone(result['tasks'])
        self.assertTrue(result['warning'])
        self.assertFalse(self.store.tasks_path.exists())
        self.assertEqual(len(list(self.store.folder.glob('tasks.uszkodzony-*.json'))), 1)

    def test_failed_save_keeps_previous_data(self):
        self.store.save_tasks([task()])
        with self.assertRaises(ValueError):
            self.store.save_tasks([task(date='zła')])
        self.assertEqual(json.loads(self.store.tasks_path.read_text('utf-8'))[0]['id'], 'a')

    def test_view_preference(self):
        self.assertEqual(self.store.get_prefs()['view'], 'month')
        self.store.set_view('week')
        self.assertEqual(self.store.get_prefs()['view'], 'week')
        with self.assertRaises(ValueError):
            self.store.set_view('rok')
