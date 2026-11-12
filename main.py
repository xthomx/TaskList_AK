"""TaskList AK — Windows desktop host. UI stays local, data stored outside the program folder."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from app_version import APP_VERSION
from storage import Storage, validate_data, MAX_BYTES
from updates import check_updates, RELEASES_URL
import auto_update


class Api:
    def __init__(self, storage=None):
        self._window = None
        self._update = None
        self._lock = threading.Lock()
        self._storage = storage or Storage()

    # ---- dane ----
    def load_state(self):
        result = self._storage.load_data()
        data = result.pop('data')
        result['people'] = data['people'] if data else None
        result['tasks'] = data['tasks'] if data else None
        result['prefs'] = self._storage.get_prefs()
        return result

    def save_data(self, data):
        return self._storage.save_data(data)

    def set_view(self, view):
        return self._storage.set_view(view)

    def _pick_save(self, name, label, ext):
        import webview
        paths = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name, file_types=(label,))
        if not paths:
            return None
        path = Path(paths[0] if isinstance(paths, (list, tuple)) else paths)
        return path if path.suffix.lower() == ext else path.with_suffix(ext)

    def _pick_open(self, label):
        import webview
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False, file_types=(label,))
        if not paths:
            return None
        path = Path(paths[0] if isinstance(paths, (list, tuple)) else paths)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('Plik przekracza 5 MB.')
        return path

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

    def export_xlsx(self, data):
        import xlsx_format
        payload = xlsx_format.dumps(data)
        path = self._pick_save('zadania.xlsx', 'Excel (*.xlsx)', '.xlsx')
        if not path:
            return None
        try:
            path.write_bytes(payload)
        except PermissionError as exc:
            raise PermissionError('Nie można zapisać pliku. Zamknij go w Excelu i sprawdź uprawnienia do folderu.') from exc
        return path.name

    def import_xlsx(self):
        import xlsx_format
        path = self._pick_open('Excel (*.xlsx)')
        return xlsx_format.loads(path.read_bytes()) if path else None

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
