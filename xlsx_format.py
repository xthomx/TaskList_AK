"""Excel (.xlsx) export and import of tasks and people."""
import datetime as dt
import io
import re
import uuid

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from storage import validate_data, MAX_TASKS, MAX_PEOPLE

TASK_SHEET, PEOPLE_SHEET = 'Zadania', 'Osoby'
HEADERS = ['Tytuł', 'Data', 'Data do', 'Od', 'Do', 'Priorytet', 'Status', 'Postęp (%)', 'Osoby', 'Notatki', 'Seria']
PRIORITY = {1: 'Niski', 2: 'Średni', 3: 'Wysoki'}
PRIORITY_BACK = {'niski': 1, 'sredni': 2, 'średni': 2, 'wysoki': 3, '1': 1, '2': 2, '3': 3,
                 'low': 1, 'medium': 2, 'high': 3}
STATUS_LABEL = {'pending': 'Oczekujące', 'progress': 'W trakcie', 'done': 'Zrobione'}
DONE_WORDS = {'wykonane', 'zrobione', 'zrobiony', 'tak', 'done', 'x', '1', 'true', 'prawda'}
PROGRESS_WORDS = {'w trakcie', 'trakcie', 'w toku', 'realizowane', 'in progress', 'progress'}


def _status(value):
    s = value.strip().lower()
    return 'done' if s in DONE_WORDS else 'progress' if s in PROGRESS_WORDS else 'pending'


WIDTHS = [40, 12, 12, 8, 8, 11, 13, 11, 30, 50, 14]



def dumps(data):
    data = validate_data(data)
    names = {p['id']: p['name'] for p in data['people']}
    wb = Workbook()
    ws = wb.active
    ws.title = TASK_SHEET
    ws.append(HEADERS)
    tasks = sorted(data['tasks'], key=lambda t: (t['date'], t['start'], t['title'].lower()))
    for t in tasks:
        ws.append([t['title'], dt.date.fromisoformat(t['date']),
                   dt.date.fromisoformat(t['end_date']) if t['end_date'] != t['date'] else None, t['start'], t['end'],
                   PRIORITY[t['priority']], STATUS_LABEL[t['status']], t['progress'],
                   '; '.join(names[a] for a in t['assignees']), t['notes'], t['series'] or None])
        for column in (2, 3):
            ws.cell(row=ws.max_row, column=column).number_format = 'yyyy-mm-dd'
    people = wb.create_sheet(PEOPLE_SHEET)
    people.append(['Osoba'])
    for p in data['people']:
        people.append([p['name']])
    fill = PatternFill('solid', fgColor='DCE6FF')
    for sheet, widths in ((ws, WIDTHS), (people, [30])):
        for i, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(i)].width = width
            sheet.cell(row=1, column=i).font = Font(bold=True)
            sheet.cell(row=1, column=i).fill = fill
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
    for sheet in (ws, people):          # tekst zaczynający się od = nie może stać się formułą
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith('='):
                    cell.data_type = 's'
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _progress(v, status):
    """Postęp 0-100 zaokrąglony do 25; zrobione zawsze 100; brak wartości = z statusu."""
    if status == 'done':
        return 100
    if v is None or (isinstance(v, str) and not v.strip()):
        return 0
    try:
        n = float(str(v).strip().rstrip('%').replace(',', '.')) if isinstance(v, str) else float(v)
    except ValueError:
        raise ValueError('nieprawidłowy postęp: ' + str(v)[:10])
    if 0 < n <= 1 and not isinstance(v, str):      # komórka w formacie procentowym (0,5 = 50%)
        n *= 100
    return min(100, max(0, round(n / 25) * 25))


def _text(v):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _date(v):
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    s = _text(v)
    for pattern, order in ((r'(\d{4})-(\d{1,2})-(\d{1,2})', (0, 1, 2)), (r'(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})', (2, 1, 0))):
        m = re.fullmatch(pattern, s[:10] if pattern.startswith('(\\d{4})') else s)
        if m:
            y, mo, d = (int(m.group(i + 1)) for i in order)
            try:
                return dt.date(y, mo, d).isoformat()
            except ValueError:
                break
    raise ValueError('nieprawidłowa data: ' + s[:20])


def _time(v):
    if v is None or v == '':
        return ''
    if isinstance(v, dt.datetime):
        return '%02d:%02d' % (v.hour, v.minute)
    if isinstance(v, dt.time):
        return '%02d:%02d' % (v.hour, v.minute)
    if isinstance(v, (int, float)) and 0 <= v < 1:          # ułamek doby
        minutes = round(v * 1440)
        return '%02d:%02d' % divmod(minutes % 1440, 60)
    m = re.fullmatch(r'(\d{1,2})[:.](\d{2})(?::\d{2})?', _text(v))
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return '%02d:%s' % (int(m.group(1)), m.group(2))
    raise ValueError('nieprawidłowa godzina: ' + _text(v)[:10])


def loads(raw):
    """Parse a workbook into validated data. Raises ValueError with a readable message."""
    try:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError('To nie jest poprawny plik Excela (.xlsx).') from exc
    sheet = wb[TASK_SHEET] if TASK_SHEET in wb.sheetnames else wb[wb.sheetnames[0]]
    rows = sheet.iter_rows(values_only=True)
    header = next(rows, None)
    if not header:
        raise ValueError('Arkusz jest pusty.')
    index = {_text(h).lower(): i for i, h in enumerate(header) if _text(h)}
    if 'tytuł' not in index and 'tytul' not in index:
        raise ValueError('Brak kolumny „Tytuł” w pierwszym wierszu arkusza „Zadania”.')
    col = lambda *names: next((index[n] for n in names if n in index), None)
    c_title, c_date, c_start, c_end = col('tytuł', 'tytul'), col('data'), col('od'), col('do')
    c_prio, c_status, c_people, c_notes = col('priorytet'), col('status'), col('osoby', 'osoba'), col('notatki', 'notatka')
    c_date2 = col('data do', 'do dnia', 'koniec')
    c_series = col('seria')
    c_prog = col('postęp (%)', 'postęp', 'postep', 'postęp %')
    if c_date is None:
        raise ValueError('Brak kolumny „Data”.')
    get = lambda row, c: row[c] if c is not None and c < len(row) else None

    people, by_name = [], {}

    def person(name):
        key = name.casefold()
        if key not in by_name:
            if len(people) >= MAX_PEOPLE:
                raise ValueError('Zbyt wiele osób.')
            by_name[key] = {'id': uuid.uuid4().hex[:12], 'name': name}
            people.append(by_name[key])
        return by_name[key]['id']

    if PEOPLE_SHEET in wb.sheetnames:
        for row in list(wb[PEOPLE_SHEET].iter_rows(values_only=True))[1:]:
            name = _text(row[0]) if row else ''
            if name:
                person(name)
    tasks = []
    for n, row in enumerate(rows, 2):
        if not row or all(_text(v) == '' for v in row):
            continue
        if len(tasks) >= MAX_TASKS:
            raise ValueError('Zbyt wiele zadań (limit %d).' % MAX_TASKS)
        try:
            title = _text(get(row, c_title))
            if not title:
                raise ValueError('brak tytułu')
            start, end = _time(get(row, c_start)), _time(get(row, c_end))
            prio = PRIORITY_BACK.get(_text(get(row, c_prio)).lower(), 1) if _text(get(row, c_prio)) else 1
            status = _status(_text(get(row, c_status)))
            progress = _progress(get(row, c_prog), status)
            date = _date(get(row, c_date))
            date2 = _date(get(row, c_date2)) if _text(get(row, c_date2)) else date
            if date2 < date:
                raise ValueError('"Data do" jest wcześniejsza niż "Data"')
            owners = _text(get(row, c_people))
            names = [x.strip() for x in owners.split(';' if ';' in owners else ',') if x.strip()]
            tasks.append({'id': uuid.uuid4().hex[:12], 'title': title, 'date': date, 'end_date': date2,
                          'start': start, 'end': end, 'priority': prio,
                          'status': status, 'progress': progress,
                          'series': _text(get(row, c_series))[:64],
                          'notes': _text(get(row, c_notes)), 'assignees': [person(x[:100]) for x in names]})
        except ValueError as exc:
            raise ValueError('Wiersz %d: %s' % (n, exc)) from exc
    wb.close()
    return validate_data({'people': people, 'tasks': tasks})
