"""Local storage of tasks, people and preferences. Working data and logs live next to the program (folders dane\\ and logi\\)."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time

MAX_BYTES = 5_000_000
MAX_TASKS = 20000
MAX_PEOPLE = 1000
VIEWS = ('month', 'week', 'day')
LAYOUTS = ('board', 'grid')                  # tydzień/dzień: kafelki (domyślnie) lub siatka godzinowa
THEMES = ('light', 'dark')                    # brak wyboru = motyw systemowy
DAY_MODES = ('sections', 'hours')            # podsumowanie dnia: sekcje albo siatka godzin
SECTIONS = ('filters', 'config')              # sekcje panelu, które można zwijać
CALENDARS = ('local', 'group')               # kalendarz zadania: lokalny (Mój) albo grupowy (Wspólny)
STATUSES = ('pending', 'progress', 'done')   # oczekujące (domyślny), w trakcie, zrobione
PROGRESS_STEPS = (0, 25, 50, 75, 100)


def app_dir():
    """Katalog, w którym uruchamia się program (obok TaskListAK.exe; w trybie deweloperskim folder projektu)."""
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def legacy_dir():
    """Dawna lokalizacja danych (do wersji 1.15): %LOCALAPPDATA%\\TaskListAK."""
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TaskListAK'


def _writable(path):
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path):
            pass
        return True
    except OSError:
        return False


def data_dir():
    """Dane robocze: folder dane\\ obok programu. Gdy folder programu jest tylko do odczytu (np. Program Files) — dawna lokalizacja.
    Dane z dawnej lokalizacji są kopiowane przy pierwszym uruchomieniu (oryginały zostają jako kopia)."""
    folder = app_dir() / 'dane'
    if not _writable(folder):
        return legacy_dir()
    old = legacy_dir()
    for name in ('tasks.json', 'preferences.json', 'group_base.json'):
        try:
            if (old / name).is_file() and not (folder / name).exists():
                shutil.copy2(old / name, folder / name)
        except OSError:
            pass
    return folder


def log_dir():
    folder = app_dir() / 'logi'
    return folder if _writable(folder) else legacy_dir()


def _is_date(s):
    """Prawdziwa data kalendarzowa w formacie RRRR-MM-DD."""
    if not (isinstance(s, str) and len(s) == 10 and s[4] == '-' and s[7] == '-' and (s[:4] + s[5:7] + s[8:]).isdigit()):
        return False
    try:
        datetime.date(int(s[:4]), int(s[5:7]), int(s[8:]))
    except ValueError:
        return False
    return True


def _is_color(s):
    return len(s) == 7 and s[0] == '#' and all(c in '0123456789abcdef' for c in s[1:])


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
        end_date = t.get('end_date') or t.get('date')            # zadanie wielodniowe: end_date > date
        series = t.get('series', '')                              # zadania cykliczne: wspólny identyfikator serii
        color = t.get('color', '')                                # własny kolor zadania (#rrggbb); pusty = wg priorytetu
        if isinstance(color, str) and color:
            color = color.lower()
        calendar = t.get('calendar') or 'local'
        status = t.get('status') or ('done' if t.get('done') else 'pending')   # 'done' pochodzi z wersji < 1.2
        progress = t.get('progress', 100 if status == 'done' else 0)
        if status == 'done':
            progress = 100
        if (not isinstance(title, str) or not title.strip() or not _is_date(t.get('date'))
                or not _is_time(start) or not _is_time(end) or t.get('priority') not in (1, 2, 3) or status not in STATUSES or progress not in PROGRESS_STEPS
                or not isinstance(t.get('notes', ''), str)
                or not isinstance(assignees, list) or any(a not in pids for a in assignees)
                or not _is_date(end_date) or end_date < t['date']
                or not isinstance(series, str) or len(series) > 64 or calendar not in CALENDARS
                or not isinstance(color, str) or not (color == '' or _is_color(color))):
            raise ValueError('Nieprawidłowe dane zadania: ' + str(title)[:40])
        clean.append({'id': t['id'], 'title': title.strip()[:300], 'date': t['date'],
                      'end_date': end_date, 'series': series, 'color': color, 'calendar': calendar,
                      'start': start if end_date == t['date'] else '', 'end': end if (start and end_date == t['date']) else '',
                      'priority': t['priority'],
                      'status': status, 'progress': progress, 'notes': t.get('notes', '')[:5000],
                      'assignees': list(dict.fromkeys(assignees))})
    return {'people': clean_people, 'tasks': clean}


def write_atomic(path, raw, swap=None):
    """Zapis pliku: plik tymczasowy + podmiana (atomowo). Podmiana bywa niemożliwa: ktoś czyta plik albo system plików jej nie
    obsługuje (np. folder współdzielony maszyny wirtualnej, niektóre dyski sieciowe). Po kilku ponowieniach zapisujemy wtedy
    w miejscu. Gdy i to się nie uda, wyjątek (PermissionError / OSError) trafia do wywołującego."""
    path = Path(path)
    swap = swap or os.replace
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        try:
            with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent, prefix='.tmp-', suffix='.tmp', delete=False) as f:
                tmp = Path(f.name)
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            for delay in (0.1, 0.3, 0.6, 1.0, None):
                try:
                    swap(tmp, path)
                    return
                except OSError:
                    if delay is None:
                        raise
                    time.sleep(delay)
        except OSError:
            pass
        with open(path, 'wb') as f:                          # zapis w miejscu (czytanie przez innych tego nie blokuje)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
    finally:
        if tmp and tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


class Storage:
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder else data_dir()
        self.tasks_path = self.folder / 'tasks.json'
        self.prefs_path = self.folder / 'preferences.json'
        self.lock = threading.Lock()

    def _atomic_write(self, path, text):
        self.folder.mkdir(parents=True, exist_ok=True)
        write_atomic(path, text.encode('utf-8'))

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
            xs = data.get('xlsx_sig', '')
            gp, gs, gf = data.get('group_path', ''), data.get('group_sig', ''), data.get('group_fp', '')
            lp, ls, lf = data.get('local_path', ''), data.get('local_sig', ''), data.get('local_fp', '')
            layout, theme = data.get('layout'), data.get('theme')
            notified = data.get('notified', [])
            notified = [k for k in notified if isinstance(k, str) and len(k) < 120][:300] if isinstance(notified, list) else []
            return {'view': view if view in VIEWS else 'month', 'layout': layout if layout in LAYOUTS else 'board', 'theme': theme if theme in THEMES else '',
                    'reminders': data.get('reminders') is not False, 'notified': notified,
                    'show_list': data.get('show_list') is not False,
                    'show_done': data.get('show_done') is not False,
                    'show_overdue': data.get('show_overdue') is not False,
                    'cal': data.get('cal') if data.get('cal') in CALENDARS else 'local', 'cal_only': data.get('cal_only') is True,
                    'day_mode': data.get('day_mode') if data.get('day_mode') in DAY_MODES else 'hours',
                    'collapsed': [k for k in data.get('collapsed', []) if k in SECTIONS] if isinstance(data.get('collapsed', []), list) else [],
                    'last_xlsx': path if isinstance(path, str) and len(path) < 1000 else '',
                    'xlsx_fp': fp if isinstance(fp, str) and len(fp) <= 64 else '',
                    'xlsx_sig': xs if isinstance(xs, str) and len(xs) <= 64 else '',
                    'group_path': gp if isinstance(gp, str) and len(gp) < 1000 else '',
                    'group_sig': gs if isinstance(gs, str) and len(gs) <= 64 else '',
                    'group_fp': gf if isinstance(gf, str) and len(gf) <= 64 else '',
                    'local_path': lp if isinstance(lp, str) and len(lp) < 1000 else '',
                    'local_sig': ls if isinstance(ls, str) and len(ls) <= 64 else '',
                    'local_fp': lf if isinstance(lf, str) and len(lf) <= 64 else ''}
        except (OSError, ValueError, UnicodeError, AttributeError):
            return {'view': 'month', 'layout': 'board', 'theme': '', 'reminders': True, 'notified': [], 'show_list': True, 'show_done': True, 'show_overdue': True, 'cal': 'local', 'cal_only': False, 'day_mode': 'hours', 'collapsed': [], 'last_xlsx': '', 'xlsx_fp': '', 'xlsx_sig': '', 'group_path': '', 'group_sig': '', 'group_fp': '', 'local_path': '', 'local_sig': '', 'local_fp': ''}

    def set_prefs(self, **changes):
        if set(changes) - {'view', 'layout', 'theme', 'reminders', 'notified', 'show_list', 'show_done', 'show_overdue', 'cal', 'cal_only', 'day_mode', 'collapsed', 'last_xlsx', 'xlsx_fp', 'xlsx_sig', 'group_path', 'group_sig', 'group_fp', 'local_path', 'local_sig', 'local_fp'}:
            raise ValueError('Nieznane ustawienie.')
        if 'collapsed' in changes:
            c = changes['collapsed']
            if not isinstance(c, list) or any(k not in SECTIONS for k in c):
                raise ValueError('Nieprawidłowa lista zwiniętych sekcji.')
            changes['collapsed'] = list(dict.fromkeys(c))
        if 'cal' in changes and changes['cal'] not in CALENDARS:
            raise ValueError('Nieprawidłowy kalendarz.')
        if 'cal_only' in changes and not isinstance(changes['cal_only'], bool):
            raise ValueError('Nieprawidłowe ustawienie kalendarza.')
        if 'day_mode' in changes and changes['day_mode'] not in DAY_MODES:
            raise ValueError('Nieprawidłowy tryb dnia.')
        if 'show_list' in changes and not isinstance(changes['show_list'], bool):
            raise ValueError('Nieprawidłowe ustawienie listy zadań.')
        if 'show_overdue' in changes and not isinstance(changes['show_overdue'], bool):
            raise ValueError('Nieprawidłowe ustawienie zaległych zadań.')
        if 'show_done' in changes and not isinstance(changes['show_done'], bool):
            raise ValueError('Nieprawidłowe ustawienie zakończonych zadań.')
        if 'reminders' in changes and not isinstance(changes['reminders'], bool):
            raise ValueError('Nieprawidłowe ustawienie przypomnień.')
        if 'notified' in changes:
            n = changes['notified']
            if not isinstance(n, list) or len(n) > 300 or any(not isinstance(k, str) or len(k) >= 120 for k in n):
                raise ValueError('Nieprawidłowa lista powiadomień.')
        if 'theme' in changes and changes['theme'] not in THEMES:
            raise ValueError('Nieprawidłowy motyw.')
        if 'layout' in changes and changes['layout'] not in LAYOUTS:
            raise ValueError('Nieprawidłowy układ.')
        if 'view' in changes and changes['view'] not in VIEWS:
            raise ValueError('Nieprawidłowy widok.')
        with self.lock:
            values = self.get_prefs()
            values.update(changes)
            self._atomic_write(self.prefs_path, json.dumps(values, ensure_ascii=False))
        return values

    def set_collapsed(self, keys):
        self.set_prefs(collapsed=keys)
        return True

    def set_day_mode(self, mode):
        self.set_prefs(day_mode=mode)
        return True

    def set_calendar(self, cal, only):
        self.set_prefs(cal=cal, cal_only=bool(only))
        return True

    def set_show_list(self, visible):
        self.set_prefs(show_list=bool(visible))
        return True

    def set_show_done(self, visible):
        self.set_prefs(show_done=bool(visible))

    def set_show_overdue(self, visible):
        self.set_prefs(show_overdue=bool(visible))
        return True

    def set_reminders(self, enabled):
        self.set_prefs(reminders=bool(enabled))
        return True

    def set_notified(self, keys):
        self.set_prefs(notified=keys)
        return True

    def set_theme(self, theme):
        self.set_prefs(theme=theme)
        return True

    def set_layout(self, layout):
        self.set_prefs(layout=layout)
        return True

    def set_view(self, view):
        self.set_prefs(view=view)
        return True


def fingerprint(data):
    """Odcisk zawartości niezależny od identyfikatorów — do wykrywania zmian względem pliku Excela."""
    clean = validate_data(data)
    names = {p['id']: p['name'] for p in clean['people']}
    tasks = sorted(json.dumps([t['title'], t['date'], t['end_date'], t['start'], t['end'], t['priority'], t['status'],
                               t['progress'], t['notes'], t['color'], t['calendar'], sorted(names[a] for a in t['assignees'])],
                              ensure_ascii=False) for t in clean['tasks'])
    people = sorted(p['name'] for p in clean['people'])
    return hashlib.sha256(json.dumps([people, tasks], ensure_ascii=False).encode('utf-8')).hexdigest()
