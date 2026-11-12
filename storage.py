"""Local storage of tasks, people and preferences. Data lives outside the program folder."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time

MAX_BYTES = 5_000_000
MAX_TASKS = 20000
MAX_PEOPLE = 1000
VIEWS = ('month', 'week', 'day')
STATUSES = ('pending', 'progress', 'done')   # oczekujące (domyślny), w trakcie, zrobione
PROGRESS_STEPS = (0, 25, 50, 75, 100)


def data_dir():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TaskListAK'


def _is_date(s):
    return isinstance(s, str) and len(s) == 10 and s[4] == '-' and s[7] == '-' and (s[:4] + s[5:7] + s[8:]).isdigit()


def _is_time(s):
    return s == '' or (isinstance(s, str) and len(s) == 5 and s[2] == ':' and (s[:2] + s[3:]).isdigit()
                       and int(s[:2]) < 24 and int(s[3:]) < 60)


def validate_data(data):
    """Return cleaned {'people': [...], 'tasks': [...]} or raise ValueError.

    Accepts the legacy format (a bare list of tasks, version 1.0.x) as well.
    """
    if isinstance(data, list):
        data = {'people': [], 'tasks': data}
    if not isinstance(data, dict):
        raise ValueError('Nieprawidłowy format danych.')
    people, tasks = data.get('people', []), data.get('tasks', [])
    if not isinstance(people, list) or len(people) > MAX_PEOPLE or not isinstance(tasks, list) or len(tasks) > MAX_TASKS:
        raise ValueError('Nieprawidłowa lista zadań lub osób.')
    pids, clean_people = set(), []
    for p in people:
        if (not isinstance(p, dict) or not isinstance(p.get('id'), str) or not p['id'] or p['id'] in pids
                or not isinstance(p.get('name'), str) or not p['name'].strip()):
            raise ValueError('Nieprawidłowa osoba.')
        pids.add(p['id'])
        clean_people.append({'id': p['id'], 'name': p['name'].strip()[:100]})
    seen, clean = set(), []
    for t in tasks:
        if not isinstance(t, dict) or not isinstance(t.get('id'), str) or not t['id'] or t['id'] in seen:
            raise ValueError('Nieprawidłowe zadanie.')
        seen.add(t['id'])
        title = t.get('title')
        start, end = t.get('start', ''), t.get('end', '')
        assignees = t.get('assignees', [])
        status = t.get('status') or ('done' if t.get('done') else 'pending')   # 'done' pochodzi z wersji < 1.2
        progress = t.get('progress', 100 if status == 'done' else 0)
        if status == 'done':
            progress = 100
        if (not isinstance(title, str) or not title.strip() or not _is_date(t.get('date'))
                or not _is_time(start) or not _is_time(end) or t.get('priority') not in (1, 2, 3) or status not in STATUSES or progress not in PROGRESS_STEPS
                or not isinstance(t.get('notes', ''), str)
                or not isinstance(assignees, list) or any(a not in pids for a in assignees)):
            raise ValueError('Nieprawidłowe dane zadania: ' + str(title)[:40])
        clean.append({'id': t['id'], 'title': title.strip()[:300], 'date': t['date'],
                      'start': start, 'end': end if start else '', 'priority': t['priority'],
                      'status': status, 'progress': progress, 'notes': t.get('notes', '')[:5000],
                      'assignees': list(dict.fromkeys(assignees))})
    return {'people': clean_people, 'tasks': clean}


class Storage:
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder else data_dir()
        self.tasks_path = self.folder / 'tasks.json'
        self.prefs_path = self.folder / 'preferences.json'
        self.lock = threading.Lock()

    def _atomic_write(self, path, text):
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.folder,
                                             prefix='.tmp-', delete=False) as f:
                tmp = Path(f.name)
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if tmp and tmp.exists():
                tmp.unlink()

    def load_data(self):
        """data is None when there is no file yet. A damaged file is set aside, never overwritten."""
        with self.lock:
            if not self.tasks_path.exists():
                return {'data': None, 'warning': ''}
            try:
                raw = self.tasks_path.read_bytes()
                if len(raw) > MAX_BYTES:
                    raise ValueError('za duży plik')
                return {'data': validate_data(json.loads(raw.decode('utf-8-sig'))), 'warning': ''}
            except (OSError, ValueError, UnicodeError):
                backup = self.tasks_path.with_name('tasks.uszkodzony-%d.json' % int(time.time()))
                try:
                    os.replace(self.tasks_path, backup)
                    return {'data': None, 'warning': 'Plik z zadaniami był uszkodzony. Zachowano go jako ' + backup.name + '.'}
                except OSError:
                    return {'data': None, 'warning': 'Nie można odczytać pliku z zadaniami.', 'readonly': True}

    def save_data(self, data):
        clean = validate_data(data)
        text = json.dumps(clean, ensure_ascii=False, indent=1)
        if len(text.encode('utf-8')) > MAX_BYTES:
            raise ValueError('Dane przekraczają 5 MB.')
        with self.lock:
            self._atomic_write(self.tasks_path, text)
        return len(clean['tasks'])

    def get_prefs(self):
        try:
            data = json.loads(self.prefs_path.read_text(encoding='utf-8'))
            view = data.get('view')
            path, fp = data.get('last_xlsx', ''), data.get('xlsx_fp', '')
            return {'view': view if view in VIEWS else 'month',
                    'last_xlsx': path if isinstance(path, str) and len(path) < 1000 else '',
                    'xlsx_fp': fp if isinstance(fp, str) and len(fp) <= 64 else ''}
        except (OSError, ValueError, UnicodeError, AttributeError):
            return {'view': 'month', 'last_xlsx': '', 'xlsx_fp': ''}

    def set_prefs(self, **changes):
        if set(changes) - {'view', 'last_xlsx', 'xlsx_fp'}:
            raise ValueError('Nieznane ustawienie.')
        if 'view' in changes and changes['view'] not in VIEWS:
            raise ValueError('Nieprawidłowy widok.')
        with self.lock:
            values = self.get_prefs()
            values.update(changes)
            self._atomic_write(self.prefs_path, json.dumps(values, ensure_ascii=False))
        return values

    def set_view(self, view):
        self.set_prefs(view=view)
        return True


def fingerprint(data):
    """Odcisk zawartości niezależny od identyfikatorów — do wykrywania zmian względem pliku Excela."""
    clean = validate_data(data)
    names = {p['id']: p['name'] for p in clean['people']}
    tasks = sorted(json.dumps([t['title'], t['date'], t['start'], t['end'], t['priority'], t['status'],
                               t['progress'], t['notes'], sorted(names[a] for a in t['assignees'])],
                              ensure_ascii=False) for t in clean['tasks'])
    people = sorted(p['name'] for p in clean['people'])
    return hashlib.sha256(json.dumps([people, tasks], ensure_ascii=False).encode('utf-8')).hexdigest()
