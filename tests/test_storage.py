import json
from pathlib import Path
import tempfile
import unittest
from storage import Storage, validate_data


def task(**kw):
    base = {'id': 'a', 'title': 'Zadanie', 'date': '2026-11-12', 'start': '10:00', 'end': '11:00',
            'priority': 2, 'status': 'pending', 'progress': 0, 'notes': '', 'assignees': []}
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
        people = [{'id': 'p1', 'name': ' Kowalska Anna '}, {'id': 'p2', 'name': 'Jan'}]
        clean = validate_data(data(task(assignees=['p1', 'p2', 'p1']), people=people))
        self.assertEqual(clean['people'][0]['name'], 'Kowalska Anna')
        self.assertEqual(clean['tasks'][0]['assignees'], ['p1', 'p2'])
        for bad in ([{'id': 'p1', 'name': ''}], [{'id': 'p1', 'name': 'A'}, {'id': 'p1', 'name': 'B'}]):
            with self.assertRaises(ValueError):
                validate_data(data(people=bad))

    def test_legacy_list_format_from_v1_0(self):
        legacy = [{k: v for k, v in task().items() if k not in ('assignees', 'status')}]
        clean = validate_data(legacy)
        self.assertEqual(clean['people'], [])
        self.assertEqual(clean['tasks'][0]['assignees'], [])
        self.assertEqual(clean['tasks'][0]['status'], 'pending')
        self.assertEqual(validate_data([dict(legacy[0], done=True)])['tasks'][0]['status'], 'done')
        with self.assertRaises(ValueError):
            validate_data(data(task(status='x')))
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

    def test_progress_steps_and_done_means_100(self):
        for bad in (task(progress=30), task(progress=-25), task(progress='50')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_data(data(bad))
        self.assertEqual(validate_data(data(task(status='progress', progress=75)))['tasks'][0]['progress'], 75)
        self.assertEqual(validate_data(data(task(status='done', progress=25)))['tasks'][0]['progress'], 100)
        legacy = {k: v for k, v in task().items() if k not in ('status', 'progress')}
        self.assertEqual(validate_data([dict(legacy, done=True)])['tasks'][0]['progress'], 100)
        self.assertEqual(validate_data([legacy])['tasks'][0]['progress'], 0)

    def test_multi_day_tasks(self):
        one = validate_data(data(task()))['tasks'][0]
        self.assertEqual(one['end_date'], one['date'])
        self.assertEqual(one['start'], '10:00')
        multi = validate_data(data(task(end_date='2026-11-14')))['tasks'][0]
        self.assertEqual((multi['date'], multi['end_date']), ('2026-11-12', '2026-11-14'))
        self.assertEqual((multi['start'], multi['end']), ('', ''))          # wielodniowe = całodniowe
        for bad in ('2026-11-11', 'jutro', '2026-13-40'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_data(data(task(end_date=bad)))
        from storage import fingerprint
        self.assertNotEqual(fingerprint(data(task())), fingerprint(data(task(end_date='2026-11-14'))))

    def test_layout_preference(self):
        self.assertEqual(self.store.get_prefs()['layout'], 'board')
        self.store.set_layout('grid')
        self.assertEqual(self.store.get_prefs()['layout'], 'grid')
        self.assertEqual(self.store.get_prefs()['view'], 'month')
        with self.assertRaises(ValueError):
            self.store.set_layout('lista')

    def test_task_color_and_theme_preference(self):
        self.assertEqual(validate_data(data(task()))['tasks'][0]['color'], '')
        self.assertEqual(validate_data(data(task(color='#3B6CF6')))['tasks'][0]['color'], '#3b6cf6')
        for bad in ('red', '#12345', '#gggggg', 123):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_data(data(task(color=bad)))
        from storage import fingerprint
        self.assertNotEqual(fingerprint(data(task())), fingerprint(data(task(color='#3b6cf6'))))
        self.assertEqual(self.store.get_prefs()['theme'], '')
        self.store.set_theme('dark')
        self.assertEqual(self.store.get_prefs()['theme'], 'dark')
        with self.assertRaises(ValueError):
            self.store.set_theme('fioletowy')

    def test_reminder_preferences(self):
        prefs = self.store.get_prefs()
        self.assertTrue(prefs['reminders'])
        self.assertEqual(prefs['notified'], [])
        self.store.set_reminders(False)
        self.store.set_notified(['a|2026-11-13|10:00'])
        prefs = self.store.get_prefs()
        self.assertFalse(prefs['reminders'])
        self.assertEqual(prefs['notified'], ['a|2026-11-13|10:00'])
        with self.assertRaises(ValueError):
            self.store.set_notified('nie lista')
        with self.assertRaises(ValueError):
            self.store.set_notified(['x' * 200])
        self.assertEqual(self.store.get_prefs()['view'], 'month')

    def test_show_list_preference(self):
        self.assertTrue(self.store.get_prefs()['show_list'])
        self.store.set_show_list(False)
        self.assertFalse(self.store.get_prefs()['show_list'])
        self.store.set_show_list(True)
        self.assertTrue(self.store.get_prefs()['show_list'])
        with self.assertRaises(ValueError):
            self.store.set_prefs(show_list='tak')
