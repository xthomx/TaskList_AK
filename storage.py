"""Local storage of tasks and preferences. Data lives outside the program folder."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time

MAX_BYTES = 5_000_000
MAX_TASKS = 20000
VIEWS = ('month', 'week', 'day')


def data_dir():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TaskListAK'


def _is_date(s):
    return isinstance(s, str) and len(s) == 10 and s[4] == '-' and s[7] == '-' and (s[:4] + s[5:7] + s[8:]).isdigit()


def _is_time(s):
    return s == '' or (isinstance(s, str) and len(s) == 5 and s[2] == ':' and (s[:2] + s[3:]).isdigit()
                       and int(s[:2]) < 24 and int(s[3:]) < 60)


def validate_tasks(tasks):
    """Return a cleaned list of tasks or raise ValueError."""
    if not isinstance(tasks, list) or len(tasks) > MAX_TASKS:
        raise ValueError('Nieprawidłowa lista zadań.')
    seen, clean = set(), []
    for t in tasks:
        if not isinstance(t, dict) or not isinstance(t.get('id'), str) or not t['id'] or t['id'] in seen:
            raise ValueError('Nieprawidłowe zadanie.')
        seen.add(t['id'])
        title = t.get('title')
        start, end = t.get('start', ''), t.get('end', '')
        if (not isinstance(title, str) or not title.strip() or not _is_date(t.get('date'))
                or not _is_time(start) or not _is_time(end) or t.get('priority') not in (1, 2, 3)
                or not isinstance(t.get('notes', ''), str)):
            raise ValueError('Nieprawidłowe dane zadania: ' + str(title)[:40])
        clean.append({'id': t['id'], 'title': title.strip()[:300], 'date': t['date'],
                      'start': start, 'end': end if start else '', 'priority': t['priority'],
                      'done': bool(t.get('done')), 'notes': t.get('notes', '')[:5000]})
    return clean


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

    def load_tasks(self):
        """None when there is no file yet. A damaged file is set aside, never overwritten."""
        with self.lock:
            if not self.tasks_path.exists():
                return {'tasks': None, 'warning': ''}
            try:
                raw = self.tasks_path.read_bytes()
                if len(raw) > MAX_BYTES:
                    raise ValueError('za duży plik')
                return {'tasks': validate_tasks(json.loads(raw.decode('utf-8-sig'))), 'warning': ''}
            except (OSError, ValueError, UnicodeError):
                backup = self.tasks_path.with_name('tasks.uszkodzony-%d.json' % int(time.time()))
                try:
                    os.replace(self.tasks_path, backup)
                    return {'tasks': None, 'warning': 'Plik z zadaniami był uszkodzony. Zachowano go jako ' + backup.name + '.'}
                except OSError:
                    return {'tasks': None, 'warning': 'Nie można odczytać pliku z zadaniami.', 'readonly': True}

    def save_tasks(self, tasks):
        clean = validate_tasks(tasks)
        text = json.dumps(clean, ensure_ascii=False, indent=1)
        if len(text.encode('utf-8')) > MAX_BYTES:
            raise ValueError('Dane przekraczają 5 MB.')
        with self.lock:
            self._atomic_write(self.tasks_path, text)
        return len(clean)

    def get_prefs(self):
        try:
            data = json.loads(self.prefs_path.read_text(encoding='utf-8'))
            view = data.get('view')
            return {'view': view if view in VIEWS else 'month'}
        except (OSError, ValueError, UnicodeError, AttributeError):
            return {'view': 'month'}

    def set_view(self, view):
        if view not in VIEWS:
            raise ValueError('Nieprawidłowy widok.')
        with self.lock:
            self._atomic_write(self.prefs_path, json.dumps({'view': view}))
        return True
