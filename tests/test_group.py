import json
from pathlib import Path
import tempfile
import unittest

import xlsx_format
from main import Api, GroupChanged, _part, _replace
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

    def test_save_refuses_when_someone_else_changed_file_unless_forced(self):
        data = D(T('b', 'Wspólne', 'group'))
        self.api._pick_save = lambda *a: self.gfile
        self.api.group_create(data)
        doc = json.loads(self.gfile.read_text('utf-8'))
        doc['tasks'].append(T('c', 'Dopisane przez kolegę', 'group'))
        self.gfile.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaises(GroupChanged):
            self.api.group_save(data)
        refreshed = self.api.group_refresh(data)
        self.assertEqual(self.titles(refreshed, 'group'), ['Dopisane przez kolegę', 'Wspólne'])
        self.api.group_save(refreshed)                              # po odświeżeniu zapis przechodzi
        self.gfile.write_text(json.dumps(doc), encoding='utf-8')
        self.api.group_save(refreshed, force=True)
        self.assertEqual(len(json.loads(self.gfile.read_text('utf-8'))['tasks']), 2)

    def test_start_loads_file_when_clean_and_keeps_copy_when_dirty_or_unreachable(self):
        data = D(T('a', 'Prywatne'), T('b', 'Wspólne', 'group'))
        self.storage.save_data(data)
        self.api._pick_save = lambda *a: self.gfile
        self.api.group_create(data)
        doc = json.loads(self.gfile.read_text('utf-8'))
        doc['tasks'].append(T('c', 'Nowe od kolegi', 'group'))
        self.gfile.write_text(json.dumps(doc), encoding='utf-8')
        state = self.api.load_state()
        self.assertEqual(sorted(t['title'] for t in state['tasks'] if t['calendar'] == 'group'), ['Nowe od kolegi', 'Wspólne'])
        self.assertEqual(state['group']['name'], 'grupowy.json')
        self.api.save_data(D(T('a', 'Prywatne'), T('b', 'Moja zmiana', 'group')))      # niezapisane zmiany grupowe
        state = self.api.load_state()
        self.assertIn('Moja zmiana', [t['title'] for t in state['tasks']])
        self.assertIn('niezapisane', state['warning'])
        self.gfile.unlink()
        self.assertIn('Moja zmiana', [t['title'] for t in self.api.load_state()['tasks']])

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

    def test_part_and_replace_helpers(self):
        data = D(T('a', 'L', 'local', ['p1']), T('b', 'G', 'group', ['p2']))
        self.assertEqual([p['id'] for p in _part(data, 'group')['people']], ['p2'])
        self.assertEqual([p['id'] for p in _part(data, 'local')['people']], ['p1'])
        merged = _replace(data, 'local', {'people': [], 'tasks': []})
        self.assertEqual(self.titles(merged, 'local'), [])
        self.assertEqual([p['id'] for p in merged['people']], ['p2'])


if __name__ == '__main__':
    unittest.main()
