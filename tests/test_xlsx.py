import datetime as dt
import io
import unittest

from openpyxl import Workbook, load_workbook
import xlsx_format
from storage import validate_data

PEOPLE = [{'id': 'p1', 'name': 'Kowalska Anna'}, {'id': 'p2', 'name': 'Żółć Łukasz'}]


def task(i, **kw):
    base = {'id': 't%d' % i, 'title': 'Zadanie %d' % i, 'date': '2026-11-1%d' % i, 'start': '09:30',
            'end': '10:45', 'priority': 3, 'status': 'pending', 'progress': 0, 'notes': 'Notatka ąęć', 'assignees': ['p1', 'p2']}
    base.update(kw)
    return base


def workbook(rows, header=('Tytuł', 'Data', 'Od', 'Do', 'Priorytet', 'Status', 'Osoby', 'Notatki')):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Zadania'
    ws.append(list(header))
    for row in rows:
        ws.append(list(row))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


class XlsxTests(unittest.TestCase):
    def test_roundtrip_keeps_everything_except_ids(self):
        source = validate_data({'people': PEOPLE, 'tasks': [task(2, status='done', progress=100), task(3, status='progress', progress=50), task(1, start='', end='', assignees=[])]})
        result = xlsx_format.loads(xlsx_format.dumps(source))
        self.assertEqual([p['name'] for p in result['people']], ['Kowalska Anna', 'Żółć Łukasz'])
        by_title = {t['title']: t for t in result['tasks']}
        names = {p['id']: p['name'] for p in result['people']}
        t2 = by_title['Zadanie 2']
        self.assertEqual((t2['date'], t2['start'], t2['end'], t2['priority'], t2['status'], t2['notes']),
                         ('2026-11-12', '09:30', '10:45', 3, 'done', 'Notatka ąęć'))
        self.assertEqual([names[a] for a in t2['assignees']], ['Kowalska Anna', 'Żółć Łukasz'])
        t1 = by_title['Zadanie 1']
        self.assertEqual((t1['start'], t1['end'], t1['assignees']), ('', '', []))

    def test_export_has_real_dates_and_is_sorted(self):
        source = {'people': PEOPLE, 'tasks': [task(3), task(1)]}
        ws = load_workbook(io.BytesIO(xlsx_format.dumps(source)))['Zadania']
        self.assertEqual([c.value for c in ws[1]][:2], ['Tytuł', 'Data'])
        self.assertEqual(ws['B2'].value, dt.datetime(2026, 11, 11))
        self.assertEqual(ws['A3'].value, 'Zadanie 3')

    def test_formula_like_text_is_stored_as_text(self):
        source = {'people': [], 'tasks': [task(1, title='=1+1', assignees=[])]}
        ws = load_workbook(io.BytesIO(xlsx_format.dumps(source)))['Zadania']
        self.assertEqual(ws['A2'].data_type, 's')
        self.assertEqual(ws['A2'].value, '=1+1')

    def test_import_handwritten_sheet(self):
        raw = workbook([
            ('Zrobić raport', dt.datetime(2026, 12, 1), dt.time(8, 0), 0.5, 'wysoki', 'Wykonane', 'Ola, Piotr', None),
            ('Telefon', '05.12.2026', '9:15', None, None, 'W trakcie', None, 'notatka'),
            (None, None, None, None, None, None, None, None),
        ])
        result = xlsx_format.loads(raw)
        self.assertEqual(len(result['tasks']), 2)
        first, second = result['tasks']
        self.assertEqual((first['date'], first['start'], first['end'], first['priority'], first['status']),
                         ('2026-12-01', '08:00', '12:00', 3, 'done'))
        self.assertEqual(len(first['assignees']), 2)
        self.assertEqual({p['name'] for p in result['people']}, {'Ola', 'Piotr'})
        self.assertEqual(second['status'], 'progress')
        self.assertEqual((first['progress'], second['progress']), (100, 0))
        self.assertEqual((second['date'], second['start'], second['end'], second['priority']), ('2026-12-05', '09:15', '', 1))

    def test_errors_are_readable(self):
        with self.assertRaisesRegex(ValueError, 'Excela'):
            xlsx_format.loads(b'to nie jest xlsx')
        with self.assertRaisesRegex(ValueError, 'Tytuł'):
            xlsx_format.loads(workbook([], header=('A', 'B')))
        with self.assertRaisesRegex(ValueError, 'Wiersz 2'):
            xlsx_format.loads(workbook([('X', 'jutro', None, None, None, None, None, None)]))
        with self.assertRaisesRegex(ValueError, 'Wiersz 2.*godzina'):
            xlsx_format.loads(workbook([('X', '2026-12-01', '25:99', None, None, None, None, None)]))

    def test_progress_import_rounding(self):
        rows = [('A', '2026-12-01', None, None, None, 'W trakcie', '60%', None, None),
                ('B', '2026-12-01', None, None, None, 'Oczekujące', 0.5, None, None),
                ('C', '2026-12-01', None, None, None, 'Zrobione', 10, None, None),
                ('D', '2026-12-01', None, None, None, None, None, None, None)]
        header = ('Tytuł', 'Data', 'Od', 'Do', 'Priorytet', 'Status', 'Postęp (%)', 'Osoby', 'Notatki')
        result = xlsx_format.loads(workbook(rows, header=header))
        self.assertEqual([t['progress'] for t in result['tasks']], [50, 50, 100, 0])

    def test_multi_day_roundtrip_and_import(self):
        source = validate_data({'people': [], 'tasks': [task(1, end_date='2026-11-15', assignees=[]), task(2, assignees=[])]})
        result = xlsx_format.loads(xlsx_format.dumps(source))
        by = {t['title']: t for t in result['tasks']}
        self.assertEqual((by['Zadanie 1']['date'], by['Zadanie 1']['end_date']), ('2026-11-11', '2026-11-15'))
        self.assertEqual(by['Zadanie 2']['end_date'], by['Zadanie 2']['date'])
        header = ('Tytuł', 'Data', 'Data do')
        ok = xlsx_format.loads(workbook([('Urlop', '2026-12-20', '23.12.2026')], header=header))
        self.assertEqual(ok['tasks'][0]['end_date'], '2026-12-23')
        with self.assertRaisesRegex(ValueError, 'Wiersz 2'):
            xlsx_format.loads(workbook([('Urlop', '2026-12-20', '2026-12-10')], header=header))

    def test_series_survives_roundtrip(self):
        source = validate_data({'people': [], 'tasks': [task(1, series='abc123', assignees=[]), task(2, assignees=[])]})
        by = {t['title']: t for t in xlsx_format.loads(xlsx_format.dumps(source))['tasks']}
        self.assertEqual(by['Zadanie 1']['series'], 'abc123')
        self.assertEqual(by['Zadanie 2']['series'], '')

    def test_color_roundtrip_and_import(self):
        source = validate_data({'people': [], 'tasks': [task(1, color='#e0529c', assignees=[]), task(2, assignees=[])]})
        by = {t['title']: t for t in xlsx_format.loads(xlsx_format.dumps(source))['tasks']}
        self.assertEqual(by['Zadanie 1']['color'], '#e0529c')
        self.assertEqual(by['Zadanie 2']['color'], '')
        ok = xlsx_format.loads(workbook([('A', '2026-12-01', 'E0529C')], header=('Tytuł', 'Data', 'Kolor')))
        self.assertEqual(ok['tasks'][0]['color'], '#e0529c')
        with self.assertRaisesRegex(ValueError, 'Wiersz 2'):
            xlsx_format.loads(workbook([('A', '2026-12-01', 'czerwony')], header=('Tytuł', 'Data', 'Kolor')))
