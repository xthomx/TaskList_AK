import json
from pathlib import Path
import tempfile
import unittest

import xlsx_format
from main import Api, _part, _replace
from storage import Storage


def T(i, title, cal='local', who=()):
    return {'id': i, 'title': title, 'date': '2026-11-12', 'end_date': '2026-11-12', 'start': '', 'end': '',
            'priority': 1, 'status': 'pending', 'progress': 0, 'notes': '', 'assignees': list(who), 'calendar': cal}


def D(*tasks, people=(('p1', 'Kowalski Jan'), ('p2', 'Nowak Anna'))):
    return {'people': [{'id': i, 'name': n} for i, n in people], 'tasks': list(tasks)}


class GroupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = Storage(self.root / 'dane')
        self.api = Api(self.storage)
        self.gfile = self.root / 'siec' / 'grupowy.json'
        self.gfile.parent.mkdir()

    def titles(self, data, cal):
        return sorted(t['title'] for t in data['tasks'] if t['calendar'] == cal)

    def test_group_file_never_contains_local_tasks_or_unrelated_people(self):
        data = D(T('a', 'Prywatne', 'local', ['p1']), T('b', 'Wspólne', 'group', ['p2']))
        self.api._pick_save = lambda *a: self.gfile
        info = self.api.group_create(data)
        self.assertEqual(info['name'], 'grupowy.json')
        doc = json.loads(self.gfile.read_text('utf-8'))
        self.assertEqual([t['title'] for t in doc['tasks']], ['Wspólne'])
        self.assertEqual([p['name'] for p in doc['people']], ['Nowak Anna'])

    def test_connect_replaces_only_group_tasks_and_merges_people_by_name(self):
        self.gfile.write_text(json.dumps({'people': [{'id': 'x', 'name': 'nowak anna'}, {'id': 'y', 'name': 'Zielona Ewa'}],
                                          'tasks': [T('b', 'Od zespołu', 'group', ['x', 'y'])]}), encoding='utf-8')
        self.api._pick_open = lambda label: self.gfile
        opened = self.api.group_open()
        self.assertEqual(self.storage.get_prefs()['group_path'], '')
        local = D(T('a', 'Prywatne', 'local', ['p1']), T('b', 'Stare grupowe', 'group'))
        out = self.api.group_accept(opened['token'], local)
        self.assertEqual(self.titles(out, 'local'), ['Prywatne'])
        self.assertEqual(self.titles(out, 'group'), ['Od zespołu'])
        self.assertEqual(sorted(p['name'] for p in out['people']), ['Kowalski Jan', 'Nowak Anna', 'Zielona Ewa'])
        task = next(t for t in out['tasks'] if t['title'] == 'Od zespołu')
        self.assertIn('p2', task['assignees'])                      # „nowak anna” = istniejąca Nowak Anna
        self.assertFalse(out['group']['dirty'])
        self.assertEqual(len({t['id'] for t in out['tasks']}), 2)   # kolidujący id został zmieniony

    def connect(self, *tasks):
        data = D(*tasks)
        self.api._pick_save = lambda *a: self.gfile
        self.api.group_create(data)
        return data

    def edit_file(self, fn):
        doc = json.loads(self.gfile.read_text('utf-8'))
        fn(doc)
        self.gfile.write_text(json.dumps(doc), encoding='utf-8')

    def file_titles(self):
        return sorted(t['title'] for t in json.loads(self.gfile.read_text('utf-8'))['tasks'])

    def test_save_merges_changes_of_both_sides(self):
        data = self.connect(T('b', 'Wspólne', 'group'), T('d', 'Do usunięcia', 'group'))
        self.edit_file(lambda doc: doc['tasks'].append(T('c', 'Dopisane przez kolegę', 'group')))
        mine = D(T('b', 'Wspólne', 'group'), T('d', 'Do usunięcia', 'group'), T('e', 'Moje nowe', 'group'))
        out = self.api.group_save(mine)
        self.assertEqual(self.titles(out, 'group'), ['Do usunięcia', 'Dopisane przez kolegę', 'Moje nowe', 'Wspólne'])
        self.assertEqual(out['report']['added'], ['Dopisane przez kolegę'])
        self.assertEqual(self.file_titles(), ['Do usunięcia', 'Dopisane przez kolegę', 'Moje nowe', 'Wspólne'])
        self.assertFalse(self.api.group_check()['changed'])

    def test_field_level_merge_and_deletions(self):
        self.connect(T('b', 'Wspólne', 'group'), T('d', 'Usuwane przeze mnie', 'group'), T('f', 'Usuwane przez kolegę', 'group'))

        def theirs(doc):
            for t in doc['tasks']:
                if t['id'] == 'b':
                    t['status'] = 'progress'; t['progress'] = 50       # kolega zmienia status
            doc['tasks'] = [t for t in doc['tasks'] if t['id'] != 'f']  # i usuwa zadanie f
        self.edit_file(theirs)
        mine_b = T('b', 'Wspólne', 'group'); mine_b['start'] = '09:00'; mine_b['end'] = '10:00'   # ja zmieniam godziny
        out = self.api.group_save(D(mine_b, T('f', 'Usuwane przez kolegę', 'group')))           # ja usuwam d, nie ruszam f
        by = {t['id']: t for t in out['tasks']}
        self.assertEqual((by['b']['status'], by['b']['progress'], by['b']['start']), ('progress', 50, '09:00'))
        self.assertNotIn('d', by)
        self.assertNotIn('f', by)
        self.assertEqual(out['report']['removed'], 1)
        self.assertEqual(self.file_titles(), ['Wspólne'])

    def test_conflict_keeps_my_version_and_is_reported(self):
        self.connect(T('b', 'Wspólne', 'group'))
        self.edit_file(lambda doc: doc['tasks'][0].update(title='Tytuł kolegi'))
        out = self.api.group_save(D(T('b', 'Mój tytuł', 'group')))
        self.assertEqual(out['tasks'][0]['title'], 'Mój tytuł')
        self.assertEqual(out['report']['conflicts'], ['Mój tytuł'])
        self.assertEqual(self.file_titles(), ['Mój tytuł'])

    def test_start_merges_when_clean_or_dirty_and_keeps_copy_when_unreachable(self):
        data = D(T('a', 'Prywatne'), T('b', 'Wspólne', 'group'))
        self.storage.save_data(data)
        self.api._pick_save = lambda *a: self.gfile
        self.api.group_create(data)
        self.edit_file(lambda doc: doc['tasks'].append(T('c', 'Nowe od kolegi', 'group')))
        state = self.api.load_state()
        self.assertEqual(sorted(t['title'] for t in state['tasks'] if t['calendar'] == 'group'), ['Nowe od kolegi', 'Wspólne'])
        self.assertEqual(state['group']['name'], 'grupowy.json')
        self.edit_file(lambda doc: doc['tasks'].append(T('x', 'Kolejne od kolegi', 'group')))
        mine = D(T('a', 'Prywatne'), T('b', 'Wspólne', 'group'), T('c', 'Nowe od kolegi', 'group'), T('m', 'Moje niezapisane', 'group'))
        self.api.save_data(mine)                                    # niezapisane zmiany grupowe
        state = self.api.load_state()
        self.assertEqual(sorted(t['title'] for t in state['tasks'] if t['calendar'] == 'group'),
                         ['Kolejne od kolegi', 'Moje niezapisane', 'Nowe od kolegi', 'Wspólne'])
        self.assertIn('Moje niezapisane', self.file_titles())
        self.gfile.unlink()
        state = self.api.load_state()
        self.assertIn('Moje niezapisane', [t['title'] for t in state['tasks']])
        self.assertIn('niedostępny', state['warning'])

    def test_local_excel_holds_only_local_tasks_and_group_tasks_survive_reload(self):
        data = D(T('a', 'Prywatne', 'local', ['p1']), T('b', 'Wspólne', 'group', ['p2']))
        self.storage.save_data(data)
        xlsx = self.root / 'moje.xlsx'
        self.api._pick_save = lambda *a: xlsx
        info = self.api.save_xlsx(data, as_new=True)
        self.assertFalse(info['dirty'])
        loaded = xlsx_format.loads(xlsx.read_bytes())
        self.assertEqual([t['title'] for t in loaded['tasks']], ['Prywatne'])
        self.assertEqual([p['name'] for p in loaded['people']], ['Kowalski Jan'])
        state = self.api.load_state()                               # czysta kopia: Excel wczytany, grupowe zostają
        self.assertEqual(self.titles(state, 'group'), ['Wspólne'])
        self.assertEqual(self.titles(state, 'local'), ['Prywatne'])
        self.assertFalse(state['file']['dirty'])

    def test_export_and_import_per_calendar(self):
        data = D(T('a', 'Prywatne', 'local', ['p1']), T('b', 'Wspólne', 'group', ['p2']))
        out = self.root / 'g.json'
        self.api._pick_save = lambda *a: out
        self.api.export_json(data, 'group')
        self.assertEqual([t['title'] for t in json.loads(out.read_text('utf-8'))['tasks']], ['Wspólne'])
        xl = self.root / 'g.xlsx'
        self.api._pick_save = lambda *a: xl
        self.api.export_xlsx(data, 'group')
        self.assertEqual([t['title'] for t in xlsx_format.loads(xl.read_bytes())['tasks']], ['Wspólne'])
        self.api._pick_open = lambda label: out
        res = self.api.import_json(D(T('a', 'Prywatne', 'local'), T('z', 'Stare', 'group')), 'group')
        self.assertEqual(self.titles(res, 'group'), ['Wspólne'])
        self.assertEqual(self.titles(res, 'local'), ['Prywatne'])
        with self.assertRaises(ValueError):
            self.api.export_json(data, 'inny')

    def test_group_check_detects_changes_by_others_and_offline(self):
        data = D(T('b', 'Wspólne', 'group'))
        self.assertEqual(self.api.group_check(), {'changed': False, 'offline': False})   # brak pliku grupowego
        self.api._pick_save = lambda *a: self.gfile
        self.api.group_create(data)
        self.assertFalse(self.api.group_check()['changed'])
        doc = json.loads(self.gfile.read_text('utf-8'))
        doc['tasks'].append(T('c', 'Od kolegi', 'group'))
        self.gfile.write_text(json.dumps(doc), encoding='utf-8')
        self.assertTrue(self.api.group_check()['changed'])
        self.api.group_refresh(data)
        self.assertFalse(self.api.group_check()['changed'])
        self.gfile.unlink()
        self.assertEqual(self.api.group_check(), {'changed': False, 'offline': True})

    def test_part_and_replace_helpers(self):
        data = D(T('a', 'L', 'local', ['p1']), T('b', 'G', 'group', ['p2']))
        self.assertEqual([p['id'] for p in _part(data, 'group')['people']], ['p2'])
        self.assertEqual([p['id'] for p in _part(data, 'local')['people']], ['p1'])
        merged = _replace(data, 'local', {'people': [], 'tasks': []})
        self.assertEqual(self.titles(merged, 'local'), [])
        self.assertEqual([p['id'] for p in merged['people']], ['p2'])


if __name__ == '__main__':
    unittest.main()
