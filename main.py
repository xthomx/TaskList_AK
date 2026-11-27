"""TaskList AK — Windows desktop host. UI stays local, data stored outside the program folder."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from app_version import APP_VERSION
from storage import Storage, validate_data, fingerprint, log_dir, write_atomic, MAX_BYTES
from applog import log as applog
from updates import check_updates, RELEASES_URL
import auto_update


def _cal(t):
    return 'group' if t.get('calendar') == 'group' else 'local'


def _used(tasks):
    return {a for t in tasks for a in t.get('assignees', [])}


def _part(data, cal):
    """Zadania jednego kalendarza z osobami. Plik grupowy zawiera tylko osoby z zadań grupowych (nic z prywatnych);
    część prywatna nie zawiera osób występujących wyłącznie w zadaniach grupowych."""
    tasks = [t for t in data['tasks'] if _cal(t) == cal]
    group_only = _used([t for t in data['tasks'] if _cal(t) == 'group']) - _used([t for t in data['tasks'] if _cal(t) == 'local'])
    if cal == 'group':
        people = [p for p in data['people'] if p['id'] in _used(tasks)]
    else:
        people = [p for p in data['people'] if p['id'] not in group_only]
    return {'people': people, 'tasks': tasks}


def _replace(base, cal, extra):
    """Zastąp zadania kalendarza cal zadaniami z extra (osoby łączone po nazwie), drugi kalendarz zostaje bez zmian."""
    kept = [t for t in base['tasks'] if _cal(t) != cal]
    if cal == 'local':
        people = [p for p in base['people'] if p['id'] in _used(kept)]
    else:
        people = list(_part(base, 'local')['people'])
    by_name = {p['name'].casefold(): p['id'] for p in people}
    ids = {p['id'] for p in people}
    idmap = {}
    for p in extra['people']:
        key = p['name'].casefold()
        if key not in by_name:
            pid = p['id'] if p['id'] not in ids else uuid.uuid4().hex[:12]
            people.append({'id': pid, 'name': p['name']})
            by_name[key] = pid
            ids.add(pid)
        idmap[p['id']] = by_name[key]
    tasks, taken = list(kept), {t['id'] for t in kept}
    for t in extra['tasks']:
        t = dict(t, assignees=[idmap[a] for a in t.get('assignees', []) if a in idmap], calendar=cal)
        if t['id'] in taken:
            t['id'] = uuid.uuid4().hex[:12]
        taken.add(t['id'])
        tasks.append(t)
    return validate_data({'people': people, 'tasks': tasks})


# Scalanie zmian w kalendarzu grupowym: trzy wersje — baza (stan po ostatniej synchronizacji), moja i cudza (aktualny plik).
# Pole zmienione tylko po jednej stronie wygrywa; zmienione po obu stronach różnie: zostaje moje, a konflikt trafia do raportu.
FIELD_GROUPS = (('title',), ('date', 'end_date', 'start', 'end'), ('priority',), ('status', 'progress'),
                ('notes',), ('color',), ('assignees',), ('series',))


def _norm(part):
    """id -> zadanie z osobami zapisanymi nazwiskami (identyfikatory osób bywają różne w różnych programach)."""
    names = {p['id']: p['name'] for p in part['people']}
    out = {}
    for t in part['tasks']:
        d = {k: t[k] for k in ('title', 'date', 'end_date', 'start', 'end', 'priority', 'status', 'progress', 'notes', 'color', 'series')}
        d['assignees'] = sorted(names[a] for a in t['assignees'] if a in names)
        out[t['id']] = d
    return out


def merge_group(base, mine, theirs, all_people=False):
    """base, mine, theirs: części grupowe {people, tasks} (base może być None). Zwraca (część, raport)."""
    b, m, t = (_norm(base) if base else None), _norm(mine), _norm(theirs)
    out, added, changed, conflicts = {}, [], [], []
    removed = 0
    for tid in list(m) + [x for x in t if x not in m]:
        inm, int_, inb = tid in m, tid in t, bool(b) and tid in b
        if inm and int_:
            base_t = b[tid] if inb else None
            merged, bad = dict(m[tid]), False
            for group in FIELD_GROUPS:
                mv, tv = [m[tid][k] for k in group], [t[tid][k] for k in group]
                if mv == tv:
                    continue
                bv = [base_t[k] for k in group] if base_t else None
                if bv is not None and mv == bv:
                    merged.update({k: t[tid][k] for k in group})
                elif bv is None or tv == bv:
                    pass                                     # zostaje moje
                else:
                    bad = True                               # obie strony zmieniły różnie: zostaje moje
            out[tid] = merged
            if bad:
                conflicts.append(merged['title'])
            elif merged != m[tid]:
                changed.append(merged['title'])
        elif inm:                                            # tylko u mnie
            if inb and m[tid] == b[tid]:
                removed += 1                                 # ktoś usunął, a ja nie ruszałem
            else:
                out[tid] = m[tid]
                if inb:
                    conflicts.append(m[tid]['title'])        # ja edytowałem, ktoś usunął: zostaje
        else:                                                # tylko w pliku
            if inb and t[tid] == b[tid]:
                continue                                     # usunąłem u siebie, nikt nie ruszał: usuwam
            out[tid] = t[tid]
            if inb:
                conflicts.append(t[tid]['title'])            # usunąłem, ktoś edytował: zostaje jego
            else:
                added.append(t[tid]['title'])
    full = {t['id']: t for t in mine['tasks']}
    full.update({t['id']: t for t in theirs['tasks'] if t['id'] not in full})
    pid = {p['name']: p['id'] for p in theirs['people']}
    pid.update({p['name']: p['id'] for p in mine['people']})
    used = sorted({n for d in out.values() for n in d['assignees']})
    if all_people:                                       # kalendarz prywatny: lista osób jest wspólna (także osoby bez zadań)
        used = sorted(set(used) | {p['name'] for p in mine['people']} | {p['name'] for p in theirs['people']})
    people = [{'id': pid[n], 'name': n} for n in used]
    tasks = []
    for tid, d in out.items():
        tasks.append(dict(d, id=tid, calendar='group', assignees=[pid[n] for n in d['assignees']]))
    tasks.sort(key=lambda x: (x['date'], x['start'], x['title'].lower(), x['id']))
    return {'people': people, 'tasks': tasks}, {'added': added, 'changed': changed, 'removed': removed, 'conflicts': conflicts}


def _sig(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


class Api:
    def __init__(self, storage=None):
        self._window = None
        self._update = None
        self._lock = threading.Lock()
        self._storage = storage or Storage()
        self._pending = None

    # ---- dane i zapamiętany plik Excela ----
    def _file_info(self, data=None, path=None):
        prefs = self._storage.get_prefs()
        path = path or prefs['last_xlsx']
        if not path:
            return None
        dirty = False
        if data is not None:
            try:
                dirty = fingerprint(_part(validate_data(data), 'local')) != prefs['xlsx_fp']
            except ValueError:
                dirty = True
        return {'name': Path(path).name, 'path': str(path), 'dirty': dirty}

    @staticmethod
    def _read_xlsx(path):
        import xlsx_format
        path = Path(path)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('Plik przekracza 5 MB.')
        return xlsx_format.loads(path.read_bytes())

    def load_state(self):
        """Przy starcie: wczytaj ostatni plik Excela, chyba że kopia robocza ma niezapisane zmiany."""
        result = self._storage.load_data()
        data = result.pop('data')
        prefs = self._storage.get_prefs()
        path = prefs['last_xlsx']
        if path:
            name = Path(path).name
            if data is None or fingerprint(_part(data, 'local')) == prefs['xlsx_fp']:
                try:
                    loaded = self._read_xlsx(path)
                    data = _replace(data, 'local', loaded) if data else loaded
                    self._storage.save_data(data)
                    self._storage.set_prefs(xlsx_fp=fingerprint(_part(data, 'local')), xlsx_sig=_sig(Path(path).read_bytes()))
                    result['warning'] = result.get('warning', '')
                except (OSError, ValueError) as exc:
                    result['warning'] = ('Nie można otworzyć ostatniego pliku Excela (' + name + '): ' + str(exc)
                                         + (' Wczytano ostatnią kopię roboczą.' if data else ''))
                    if data is None:
                        data = {'people': [], 'tasks': []}     # nie zasiewaj przykładów — plik jest skonfigurowany
            else:
                result['warning'] = ('Plik ' + name + ' ma niezapisane zmiany — wczytano kopię roboczą. '
                                     'Zapisz do Excela (Ctrl+S), aby je zachować w pliku.')
        result['group'] = None
        if prefs['group_path']:
            data, result['warning'] = self._load_group(data, result.get('warning', ''))
        result['local_json'] = None
        if prefs['local_path']:
            data, result['warning'] = self._load_cal('local', data, result.get('warning', ''))
        result['people'] = data['people'] if data else None
        result['tasks'] = data['tasks'] if data else None
        result['prefs'] = self._storage.get_prefs()
        result['data_path'] = str(self._storage.tasks_path.resolve())
        result['file'] = self._file_info(data) if data else self._file_info()
        result['group'] = self._group_info(data) if data else self._group_info()
        result['local_json'] = self._local_info(data) if data else self._local_info()
        return result

    # ---- pliki JSON kalendarzy: grupowy (np. dysk sieciowy) i prywatny (np. folder OneDrive, wiele urządzeń jednego użytkownika) ----
    LINKS = {'group': ('group_path', 'group_sig', 'group_fp', 'group_base.json', 'group', 'grupowy'),
             'local': ('local_path', 'local_sig', 'local_fp', 'local_base.json', 'local_json', 'prywatny')}

    def _link_info(self, cal, data=None):
        pkey, _s, fkey = self.LINKS[cal][:3]
        prefs = self._storage.get_prefs()
        path = prefs[pkey]
        if not path:
            return None
        dirty = False
        if data is not None:
            try:
                dirty = fingerprint(_part(validate_data(data), cal)) != prefs[fkey]
            except ValueError:
                dirty = True
        return {'name': Path(path).name, 'path': str(path), 'dirty': dirty}

    def _group_info(self, data=None):
        return self._link_info('group', data)

    def _local_info(self, data=None):
        return self._link_info('local', data)

    @staticmethod
    def _read_doc(path, cal):
        path = Path(path)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('Plik przekracza 5 MB.')
        raw = path.read_bytes()
        try:
            doc = json.loads(raw.decode('utf-8-sig'))
            clean = validate_data({'people': doc['people'], 'tasks': [dict(t, calendar=cal) for t in doc['tasks']]})
        except (ValueError, UnicodeError, KeyError, TypeError) as exc:
            raise ValueError('To nie jest poprawny plik kalendarza ' + Api.LINKS[cal][5][:-1] + 'ego.') from exc
        return clean, _sig(raw)

    @staticmethod
    def _read_group(path):
        return Api._read_doc(path, 'group')

    @staticmethod
    def _read_local(path):
        return Api._read_doc(path, 'local')

    def _read_link(self, cal, path):
        return self._read_group(path) if cal == 'group' else self._read_local(path)

    # baza scalania: zawartość pliku po ostatniej synchronizacji
    def _base_file(self, cal):
        return self._storage.folder / self.LINKS[cal][3]

    @property
    def _base_path(self):
        return self._base_file('group')

    def _read_base(self, cal='group'):
        try:
            doc = json.loads(self._base_file(cal).read_text(encoding='utf-8'))
            return validate_data({'people': doc['people'], 'tasks': [dict(t, calendar=cal) for t in doc['tasks']]})
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _write_base(self, part, cal='group'):
        self._storage._atomic_write(self._base_file(cal), json.dumps(part, ensure_ascii=False))

    def _sync_cal(self, cal, data):
        """Scal moje zadania kalendarza z aktualnym plikiem, zapisz wynik w pliku (gdy się różni) i w kopii roboczej."""
        pkey, skey, fkey, _b, infokey, adj = self.LINKS[cal]
        prefs = self._storage.get_prefs()
        path = Path(prefs[pkey])
        clean = validate_data(data)
        mine = _part(clean, cal)
        for _ in range(4):
            theirs, sig = self._read_link(cal, path)
            merged, report = merge_group(self._read_base(cal), mine, theirs, all_people=(cal == 'local'))
            same_people = cal == 'group' or {p['name'] for p in merged['people']} <= {p['name'] for p in theirs['people']}
            if _norm(merged) == _norm(theirs) and same_people:
                new_sig = sig                                      # plik już zawiera wynik — bez zapisu
            else:
                if _sig(path.read_bytes()) != sig:
                    continue                                       # ktoś zapisał w międzyczasie: scal jeszcze raz
                new_sig = _sig(self._write_text(path, json.dumps(merged, ensure_ascii=False, indent=1)))
            final = _replace(clean, cal, merged)
            self._storage.save_data(final)
            self._write_base(merged, cal)
            self._storage.set_prefs(**{skey: new_sig, fkey: fingerprint(_part(final, cal))})
            return {'people': final['people'], 'tasks': final['tasks'], infokey: self._link_info(cal, final), 'report': report}
        raise ValueError('Plik ' + adj + ' jest zmieniany przez innych — spróbuj ponownie za chwilę.')

    def _sync_group(self, data):
        return self._sync_cal('group', data)

    def _load_cal(self, cal, data, warning):
        """Start: scal kopię roboczą z aktualnym plikiem; gdy plik niedostępny, zostaje kopia."""
        adj = self.LINKS[cal][5]
        name = Path(self._storage.get_prefs()[self.LINKS[cal][0]]).name
        if data is None:
            data = {'people': [], 'tasks': []}
        try:
            out = self._sync_cal(cal, data)
            return {'people': out['people'], 'tasks': out['tasks']}, warning
        except (OSError, ValueError) as exc:
            return data, (warning + ' ' if warning else '') + ('Plik ' + adj + ' niedostępny (' + name + '): ' + str(exc)
                                                               + ' Pokazano ostatnią kopię kalendarza ' + adj[:-1] + 'ego.')

    def _load_group(self, data, warning):
        return self._load_cal('group', data, warning)

    def _cal_create(self, cal, data):
        clean = validate_data(data)
        pkey, skey, fkey = self.LINKS[cal][:3]
        adj = self.LINKS[cal][5]
        path = self._pick_save('zadania-' + ('grupowe' if cal == 'group' else 'prywatne') + '.json', 'Kalendarz ' + adj + ' (*.json)', '.json')
        if not path:
            return None
        part = _part(clean, cal)
        raw = self._write_text(path, json.dumps(part, ensure_ascii=False, indent=1))
        self._write_base(part, cal)
        self._storage.set_prefs(**{pkey: str(path.resolve()), skey: _sig(raw), fkey: fingerprint(_part(clean, cal))})
        return self._link_info(cal, clean)

    def _cal_open(self, cal):
        """Wybierz i sprawdź plik; zapamiętanie po *_accept (po potwierdzeniu w UI)."""
        path = self._pick_open('Kalendarz ' + self.LINKS[cal][5] + ' (*.json)')
        if not path:
            return None
        extra, sig = self._read_link(cal, path)
        token = uuid.uuid4().hex
        pending = getattr(self, '_pending_links', None)
        if pending is None:
            pending = self._pending_links = {}
        pending[cal] = (token, path.resolve(), extra, sig)
        return {'token': token, 'name': path.name, 'count': len(extra['tasks'])}

    def _cal_accept(self, cal, token, data):
        pending = getattr(self, '_pending_links', {}).get(cal)
        if not pending or pending[0] != token:
            raise ValueError('Nieaktualna operacja otwierania.')
        pkey, skey, fkey, _b, infokey = self.LINKS[cal][:5]
        _, path, extra, sig = pending
        self._pending_links.pop(cal, None)
        merged = _replace(validate_data(data), cal, extra)
        self._storage.save_data(merged)
        self._write_base(_part(merged, cal), cal)
        self._storage.set_prefs(**{pkey: str(path), skey: sig, fkey: fingerprint(_part(merged, cal))})
        return {'people': merged['people'], 'tasks': merged['tasks'], infokey: self._link_info(cal, merged)}

    def _cal_check(self, cal):
        """Czy ktoś zmienił plik od naszego ostatniego odczytu/zapisu? Brak dostępu do pliku = tryb offline."""
        pkey, skey = self.LINKS[cal][:2]
        prefs = self._storage.get_prefs()
        if not prefs[pkey]:
            return {'changed': False, 'offline': False}
        try:
            path = Path(prefs[pkey])
            if path.stat().st_size > MAX_BYTES:
                return {'changed': False, 'offline': False}
            raw = path.read_bytes()
        except OSError:
            return {'changed': False, 'offline': True}
        return {'changed': _sig(raw) != prefs[skey], 'offline': False}

    def _cal_disconnect(self, cal):
        pkey, skey, fkey = self.LINKS[cal][:3]
        self._storage.set_prefs(**{pkey: '', skey: '', fkey: ''})
        try:
            self._base_file(cal).unlink()
        except OSError:
            pass
        return True

    def group_create(self, data):
        return self._cal_create('group', data)

    def group_open(self):
        return self._cal_open('group')

    def group_accept(self, token, data):
        return self._cal_accept('group', token, data)

    def group_sync(self, data):
        """Odśwież / zapisz / synchronizuj: scal zmiany obu stron (także gdy ktoś inny zmienił plik)."""
        if not self._storage.get_prefs()['group_path']:
            raise ValueError('Kalendarz grupowy nie jest połączony z plikiem.')
        return self._sync_cal('group', data)

    group_refresh = group_sync
    group_save = group_sync

    def group_check(self):
        return self._cal_check('group')

    def group_disconnect(self):
        return self._cal_disconnect('group')

    def xlsx_disconnect(self):
        """Excel tylko na żądanie (eksport / import): usuń zapamiętany plik, który był zapisywany automatycznie."""
        self._storage.set_prefs(last_xlsx='', xlsx_fp='', xlsx_sig='')
        return True

    def local_create(self, data):
        return self._cal_create('local', data)

    def local_open(self):
        return self._cal_open('local')

    def local_accept(self, token, data):
        return self._cal_accept('local', token, data)

    def local_sync(self, data):
        if not self._storage.get_prefs()['local_path']:
            raise ValueError('Kalendarz prywatny nie jest połączony z plikiem w chmurze.')
        return self._sync_cal('local', data)

    def local_check(self):
        return self._cal_check('local')

    def local_disconnect(self):
        return self._cal_disconnect('local')

    def sync_files(self, data):
        """Zapis automatyczny: wypisz zmiany do połączonych plików (Excel z zadaniami lokalnymi, plik grupowy i plik prywatny JSON —
        ze scaleniem). Błędy nie przerywają pracy: wracają w 'errors' i zapis jest ponawiany."""
        clean = validate_data(data)
        prefs = self._storage.get_prefs()
        out = {'errors': {}, 'group_result': None, 'local_result': None}
        if prefs['last_xlsx']:
            local = _part(clean, 'local')
            try:
                if fingerprint(local) != prefs['xlsx_fp']:
                    path = Path(prefs['last_xlsx'])
                    if path.exists() and prefs['xlsx_sig'] and _sig(path.read_bytes()) != prefs['xlsx_sig']:
                        out['errors']['file'] = ('Plik Excela został zmieniony poza programem — zapis automatyczny wstrzymany. '
                                                 'Użyj Pliki → „Otwórz plik Excela…” (wczytaj jego wersję) albo „Zapisz Excel jako…”.')
                    else:
                        import xlsx_format
                        payload = xlsx_format.dumps(local)
                        self._write_bytes(path, payload)
                        self._storage.set_prefs(xlsx_fp=fingerprint(local), xlsx_sig=_sig(payload))
            except (OSError, ValueError) as exc:
                out['errors']['file'] = 'Zapis do Excela nie powiódł się: ' + str(exc)
        final = clean
        for cal, reskey, label in (('group', 'group_result', 'pliku grupowego'), ('local', 'local_result', 'pliku prywatnego')):
            pkey, _s, fkey = self.LINKS[cal][:3]
            if not prefs[pkey]:
                continue
            try:
                if fingerprint(_part(final, cal)) != prefs[fkey]:
                    out[reskey] = res = self._sync_cal(cal, final)
                    final = {'people': res['people'], 'tasks': res['tasks']}
            except (OSError, ValueError) as exc:
                out['errors'][cal] = 'Zapis do ' + label + ' nie powiódł się: ' + str(exc)
        for what, msg in out['errors'].items():
            applog(what + ': ' + msg)
        out['file'] = self._file_info(final)
        out['group'] = self._group_info(final)
        out['local_json'] = self._local_info(final)
        return out

    @staticmethod
    def _write_text(path, text):
        return Api._write_bytes(path, text.encode('utf-8'))

    @staticmethod
    def _swap(tmp, path):
        os.replace(tmp, path)

    @staticmethod
    def _write_bytes(path, raw):
        try:
            write_atomic(path, raw, swap=Api._swap)
        except PermissionError as exc:
            raise PermissionError('Plik jest zablokowany przez inny program lub użytkownika albo brak uprawnień do folderu '
                                  '(zapis zostanie ponowiony automatycznie).') from exc
        return raw

    def save_data(self, data):
        count = self._storage.save_data(data)
        info = self._file_info(data)
        out = {'count': count, 'dirty': bool(info and info['dirty'])}
        group = self._group_info(data)
        if group:
            out['group_dirty'] = group['dirty']
        local = self._local_info(data)
        if local:
            out['local_dirty'] = local['dirty']
        return out

    def set_view(self, view):
        return self._storage.set_view(view)

    def set_collapsed(self, keys):
        return self._storage.set_collapsed(keys)

    def set_day_mode(self, mode):
        return self._storage.set_day_mode(mode)

    def set_calendar(self, cal, only):
        return self._storage.set_calendar(cal, only)

    def set_show_list(self, visible):
        return self._storage.set_show_list(visible)

    def set_show_done(self, visible):
        return self._storage.set_show_done(visible)

    def set_show_overdue(self, visible):
        return self._storage.set_show_overdue(visible)

    def set_reminders(self, enabled):
        return self._storage.set_reminders(enabled)

    def set_notified(self, keys):
        return self._storage.set_notified(keys)

    @staticmethod
    def _play_alert():
        """Trzy rosnące tony (natywnie, przez Windows — działa niezależnie od przeglądarki w oknie programu i od fokusu).
        W osobnym wątku, bo winsound.Beep blokuje. Gdy się nie uda, dźwięk systemowy „wykrzyknik”."""
        def run():
            try:
                import winsound
                try:
                    for freq, ms in ((880, 180), (1175, 180), (1568, 350)):
                        winsound.Beep(freq, ms)
                except Exception:
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def alert_sound(self):
        """Powtórzenie sygnału, dopóki przypomnienie jest na ekranie."""
        if sys.platform == 'win32':
            self._play_alert()
        return True

    def attention(self, on_top=True):
        """Przypomnienie: wyciągnij okno nad wszystkie inne okna i zostaw je tam, dopóki przypomnienie jest na ekranie
        (on_top=True); po zamknięciu przypomnienia interfejs woła attention(False), co zdejmuje znacznik „zawsze na wierzchu”.
        Tylko wywołania Win32 (bez pól formularza WinForms z innego wątku — ustawianie TopMost / WindowState spoza wątku okna
        potrafiło zawiesić program). Błędy ignorujemy."""
        if sys.platform != 'win32':
            return True
        if on_top:
            self._play_alert()                                  # sygnał dźwiękowy także wtedy, gdy Windows nie odda fokusu
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, 'TaskList AK')
            if not hwnd:
                return True
            flags = 0x0001 | 0x0002 | 0x0010 | 0x4000                                # NOSIZE | NOMOVE | NOACTIVATE | ASYNCWINDOWPOS
            if not on_top:
                user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)                     # HWND_NOTOPMOST — okno zostaje na wierzchu zwykłych okien
                return True
            if user32.IsIconic(hwnd):
                user32.ShowWindowAsync(hwnd, 9)                 # SW_RESTORE: wraca do poprzedniego stanu (także zmaksymalizowanego)

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [('cbSize', wintypes.UINT), ('hwnd', wintypes.HWND), ('dwFlags', wintypes.DWORD),
                            ('uCount', wintypes.UINT), ('dwTimeout', wintypes.DWORD)]
            info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x0000000F, 5, 0)     # FLASHW_ALL | FLASHW_TIMERNOFG
            user32.FlashWindowEx(ctypes.byref(info))
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags)                         # HWND_TOPMOST — nad wszystkimi oknami
            try:                                                                     # spróbuj też przejąć fokus (system bywa temu przeciwny — wtedy zostaje miganie na pasku)
                kernel32 = ctypes.windll.kernel32
                fg = user32.GetForegroundWindow()
                fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
                my_thread = kernel32.GetCurrentThreadId()
                attached = bool(fg_thread and fg_thread != my_thread and user32.AttachThreadInput(my_thread, fg_thread, True))
                try:
                    user32.BringWindowToTop(hwnd)
                    user32.SetForegroundWindow(hwnd)
                finally:
                    if attached:
                        user32.AttachThreadInput(my_thread, fg_thread, False)
            except Exception:
                pass
        except Exception:
            pass
        return True

    def set_theme(self, theme):
        return self._storage.set_theme(theme)

    def set_layout(self, layout):
        return self._storage.set_layout(layout)

    def open_xlsx(self):
        """Wybierz i sprawdź plik; zapamiętanie nastąpi dopiero po accept_xlsx (po potwierdzeniu w UI)."""
        path = self._pick_open('Excel (*.xlsx)')
        if not path:
            return None
        data = self._read_xlsx(path)
        token = uuid.uuid4().hex
        self._pending = (token, path.resolve(), data)
        return {'token': token, 'name': path.name, 'data': data}

    def accept_xlsx(self, token):
        if not self._pending or self._pending[0] != token:
            raise ValueError('Nieaktualna operacja otwierania.')
        _, path, data = self._pending
        self._pending = None
        stored = self._storage.load_data()['data']
        merged = _replace(stored, 'local', data) if stored else data
        self._storage.save_data(merged)
        self._storage.set_prefs(last_xlsx=str(path), xlsx_fp=fingerprint(_part(merged, 'local')), xlsx_sig=_sig(Path(path).read_bytes()))
        return dict(self._file_info(merged), people=merged['people'], tasks=merged['tasks'])

    def save_xlsx(self, data, as_new=False):
        """Zapisz do zapamiętanego pliku (lub zapytaj o nazwę) i zapamiętaj go."""
        import xlsx_format
        clean = validate_data(data)
        payload = xlsx_format.dumps(_part(clean, 'local'))
        current = self._storage.get_prefs()['last_xlsx']
        if current and not as_new:
            path = Path(current)
        else:
            path = self._pick_save(Path(current).name if current else 'zadania.xlsx', 'Excel (*.xlsx)', '.xlsx')
            if not path:
                return None
        self._write_bytes(path, payload)
        self._storage.save_data(clean)
        self._storage.set_prefs(last_xlsx=str(path.resolve()), xlsx_fp=fingerprint(_part(clean, 'local')), xlsx_sig=_sig(payload))
        return self._file_info(clean)

    def _pick_save(self, name, label, ext):
        import webview
        paths = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name, file_types=(label,))
        if not paths:
            return None
        path = Path(paths[0] if isinstance(paths, (list, tuple)) else paths)
        return path if path.suffix.lower() == ext else path.with_suffix(ext)

    def _pick_open(self, label, limit=MAX_BYTES):
        import webview
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False, file_types=(label,))
        if not paths:
            return None
        path = Path(paths[0] if isinstance(paths, (list, tuple)) else paths)
        if path.stat().st_size > limit:
            raise ValueError('Plik przekracza %d MB.' % (limit // (1024 * 1024)))
        return path

    # ---- zadanie z wiadomości e-mail (przeciągnięcie z Outlooka lub wybór pliku .msg/.eml) ----
    def parse_mail(self, name, content_b64):
        import base64
        import binascii
        import mail_import
        if not isinstance(content_b64, str) or len(content_b64) > mail_import.MAX_MAIL_BYTES * 4 // 3 + 16:
            raise ValueError('Wiadomość jest zbyt duża (limit 25 MB).')
        try:
            raw = base64.b64decode(content_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError('Nie udało się odczytać przeciągniętego pliku.') from exc
        return mail_import.parse_mail(str(name), raw)

    def open_mail(self):
        import mail_import
        path = self._pick_open('Wiadomości i terminy (*.msg;*.eml;*.ics)', limit=mail_import.MAX_MAIL_BYTES)
        return mail_import.parse_mail(path.name, path.read_bytes()) if path else None

    @staticmethod
    def _cal_arg(cal):
        if cal not in ('local', 'group'):
            raise ValueError('Nieprawidłowy kalendarz.')
        return cal

    def export_json(self, data, cal='local'):
        """Kopia JSON jednego kalendarza (prywatnego lub grupowego)."""
        part = _part(validate_data(data), self._cal_arg(cal))
        path = self._pick_save('zadania-%s.json' % ('grupowe' if cal == 'group' else 'prywatne'), 'Zadania (*.json)', '.json')
        if not path:
            return None
        path.write_text(json.dumps(part, ensure_ascii=False, indent=1), encoding='utf-8')
        return path.name

    def export_xlsx(self, data, cal='local'):
        """Jednorazowy eksport kalendarza do Excela (nie zmienia zapamiętanego pliku)."""
        import xlsx_format
        part = _part(validate_data(data), self._cal_arg(cal))
        path = self._pick_save('zadania-%s.xlsx' % ('grupowe' if cal == 'group' else 'prywatne'), 'Excel (*.xlsx)', '.xlsx')
        if not path:
            return None
        path.write_bytes(xlsx_format.dumps(part))
        return path.name

    def _import_cal(self, name, extra, data, cal):
        merged = _replace(validate_data(data), self._cal_arg(cal), extra)
        return {'name': name, 'count': len(extra['tasks']), 'people': merged['people'], 'tasks': merged['tasks']}

    def import_json(self, data=None, cal='local'):
        """Wczytaj JSON do wskazanego kalendarza; jego zadania zostaną zastąpione (po potwierdzeniu w UI)."""
        path = self._pick_open('Zadania (*.json)')
        if not path:
            return None
        extra = validate_data(json.loads(path.read_bytes().decode('utf-8-sig')))
        return extra if data is None else self._import_cal(path.name, extra, data, cal)

    def import_xlsx(self, data, cal='local'):
        path = self._pick_open('Excel (*.xlsx)')
        if not path:
            return None
        return self._import_cal(path.name, self._read_xlsx(path), data, cal)

    # ---- aktualizacje ----
    def get_version(self):
        return APP_VERSION

    def check_updates(self):
        return check_updates()

    def prepare_update(self):
        with self._lock:
            if self._update is None:
                self._update = auto_update.prepare()
            return {'version': self._update['version']}

    def install_update(self):
        with self._lock:
            if not self._update:
                raise RuntimeError('Najpierw pobierz aktualizację.')
            update = self._update
            subprocess.Popen([update['runner'], '--pid', str(os.getpid()),
                              '--staged', update['staged'], '--target', update['target']],
                             cwd=update['folder'])
            self._update = None
        self._window.destroy()
        return True

    def open_updates_page(self):
        import webbrowser
        if not webbrowser.open(RELEASES_URL):
            raise RuntimeError('Nie udało się otworzyć przeglądarki. Wejdź na github.com/xthomx/TaskList_AK/releases.')
        return True


def build_html():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'ui'
    html = (root / 'index.html').read_text(encoding='utf-8')
    html = html.replace('<link rel="stylesheet" href="style.css">',
                        '<style>' + (root / 'style.css').read_text(encoding='utf-8') + '</style>')
    help_file = root / 'help.html'
    if help_file.is_file():
        html = html.replace('<!--HELP-->', help_file.read_text(encoding='utf-8'))
    html = html.replace('<script src="app.js"></script>',
                        '<script>window.__DESKTOP__=true;</script><script>' + (root / 'app.js').read_text(encoding='utf-8') + '</script>')
    return html


def main():
    import webview
    api = Api()
    window = webview.create_window('TaskList AK', html=build_html(), js_api=api,
                                   width=1400, height=900, min_size=(900, 600), maximized=True,
                                   text_select=True)
    api._window = window
    icon = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'ui' / 'icon.ico'
    webview.start(gui='edgechromium', private_mode=True, icon=str(icon) if icon.is_file() else None)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        log = log_dir()
        log.mkdir(parents=True, exist_ok=True)
        (log / 'blad.log').write_text(traceback.format_exc(), encoding='utf-8')
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,
                'Nie udało się uruchomić programu. Sprawdź instalację Microsoft Edge WebView2 Runtime.\nSzczegóły: ' + str(log / 'blad.log'),
                'TaskList AK', 16)
        raise
