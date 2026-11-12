"""TaskList AK — Windows desktop host. UI stays local, data stored outside the program folder."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import uuid

from app_version import APP_VERSION
from storage import Storage, validate_data, fingerprint, MAX_BYTES
from updates import check_updates, RELEASES_URL
import auto_update


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
                dirty = fingerprint(data) != prefs['xlsx_fp']
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
            if data is None or fingerprint(data) == prefs['xlsx_fp']:
                try:
                    data = self._read_xlsx(path)
                    self._storage.save_data(data)
                    self._storage.set_prefs(xlsx_fp=fingerprint(data))
                    result['warning'] = result.get('warning', '')
                except (OSError, ValueError) as exc:
                    result['warning'] = ('Nie można otworzyć ostatniego pliku Excela (' + name + '): ' + str(exc)
                                         + (' Wczytano ostatnią kopię roboczą.' if data else ''))
                    if data is None:
                        data = {'people': [], 'tasks': []}     # nie zasiewaj przykładów — plik jest skonfigurowany
            else:
                result['warning'] = ('Plik ' + name + ' ma niezapisane zmiany — wczytano kopię roboczą. '
                                     'Zapisz do Excela (Ctrl+S), aby je zachować w pliku.')
        result['people'] = data['people'] if data else None
        result['tasks'] = data['tasks'] if data else None
        result['prefs'] = self._storage.get_prefs()
        result['file'] = self._file_info(data) if data else self._file_info()
        return result

    def save_data(self, data):
        count = self._storage.save_data(data)
        info = self._file_info(data)
        return {'count': count, 'dirty': bool(info and info['dirty'])}

    def set_view(self, view):
        return self._storage.set_view(view)

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
        self._storage.save_data(data)
        self._storage.set_prefs(last_xlsx=str(path), xlsx_fp=fingerprint(data))
        return self._file_info(data)

    def save_xlsx(self, data, as_new=False):
        """Zapisz do zapamiętanego pliku (lub zapytaj o nazwę) i zapamiętaj go."""
        import xlsx_format
        clean = validate_data(data)
        payload = xlsx_format.dumps(clean)
        current = self._storage.get_prefs()['last_xlsx']
        if current and not as_new:
            path = Path(current)
        else:
            path = self._pick_save(Path(current).name if current else 'zadania.xlsx', 'Excel (*.xlsx)', '.xlsx')
            if not path:
                return None
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent, prefix='.zadania-', suffix='.tmp', delete=False) as f:
                tmp = Path(f.name)
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except PermissionError as exc:
            raise PermissionError('Nie można zapisać pliku. Zamknij go w Excelu i sprawdź uprawnienia do folderu.') from exc
        finally:
            if tmp and tmp.exists():
                tmp.unlink()
        self._storage.save_data(clean)
        self._storage.set_prefs(last_xlsx=str(path.resolve()), xlsx_fp=fingerprint(clean))
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
        path = self._pick_open('Wiadomości (*.msg;*.eml)', limit=mail_import.MAX_MAIL_BYTES)
        return mail_import.parse_mail(path.name, path.read_bytes()) if path else None

    def export_json(self, data):
        clean = validate_data(data)
        path = self._pick_save('zadania.json', 'Zadania (*.json)', '.json')
        if not path:
            return None
        path.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding='utf-8')
        return path.name

    def import_json(self):
        path = self._pick_open('Zadania (*.json)')
        return validate_data(json.loads(path.read_bytes().decode('utf-8-sig'))) if path else None

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
        log = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TaskListAK'
        log.mkdir(parents=True, exist_ok=True)
        (log / 'blad.log').write_text(traceback.format_exc(), encoding='utf-8')
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,
                'Nie udało się uruchomić programu. Sprawdź instalację Microsoft Edge WebView2 Runtime.\nSzczegóły: ' + str(log / 'blad.log'),
                'TaskList AK', 16)
        raise
