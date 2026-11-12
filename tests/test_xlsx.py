import datetime as dt
import io
import unittest

from openpyxl import Workbook, load_workbook
import xlsx_format
from storage import validate_data

PEOPLE = [{'id': 'p1', 'name': 'Anna Kowalska'}, {'id': 'p2', 'name': 'Łukasz Żółć'}]


def task(i, **kw):
    base = {'id': 't%d' % i, 'title': 'Zadanie %d' % i, 'date': '2026-11-1%d' % i, 'start': '09:30',
            'end': '10:45', 'priority': 3, 'done': False, 'notes': 'Notatka ąęć', 'assignees': ['p1', 'p2']}
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
        source = validate_data({'people': PEOPLE, 'tasks': [task(2, done=True), task(1, start='', end='', assignees=[])]})
        result = xlsx_format.loads(xlsx_format.dumps(source))
        self.assertEqual([p['name'] for p in result['people']], ['Anna Kowalska', 'Łukasz Żółć'])
        by_title = {t['title']: t for t in result['tasks']}
        names = {p['id']: p['name'] for p in result['people']}
        t2 = by_title['Zadanie 2']
        self.assertEqual((t2['date'], t2['start'], t2['end'], t2['priority'], t2['done'], t2['notes']),
                         ('2026-11-12', '09:30', '10:45', 3, True, 'Notatka ąęć'))
        self.assertEqual([names[a] for a in t2['assignees']], ['Anna Kowalska', 'Łukasz Żółć'])
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
            ('Telefon', '05.12.2026', '9:15', None, None, None, None, 'notatka'),
            (None, None, None, None, None, None, None, None),
        ])
        result = xlsx_format.loads(raw)
        self.assertEqual(len(result['tasks']), 2)
        first, second = result['tasks']
        self.assertEqual((first['date'], first['start'], first['end'], first['priority'], first['done']),
                         ('2026-12-01', '08:00', '12:00', 3, True))
        self.assertEqual(len(first['assignees']), 2)
        self.assertEqual({p['name'] for p in result['people']}, {'Ola', 'Piotr'})
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
