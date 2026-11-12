"""TaskList AK — Windows desktop host. UI stays local, data stored outside the program folder."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from app_version import APP_VERSION
from storage import Storage, validate_tasks, MAX_BYTES
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
        result = self._storage.load_tasks()
        result['prefs'] = self._storage.get_prefs()
        return result

    def save_tasks(self, tasks):
        return self._storage.save_tasks(tasks)

    def set_view(self, view):
        return self._storage.set_view(view)

    def export_tasks(self, tasks):
        import webview
        clean = validate_tasks(tasks)
        paths = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename='zadania.json',
                                                file_types=('Zadania (*.json)',))
        if not paths:
            return None
        path = Path(paths[0] if isinstance(paths, (list, tuple)) else paths)
        if path.suffix.lower() != '.json':
            path = path.with_suffix('.json')
        path.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding='utf-8')
        return path.name

    def import_tasks(self):
        import webview
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False,
                                                file_types=('Zadania (*.json)',))
        if not paths:
            return None
        path = Path(paths[0] if isinstance(paths, (list, tuple)) else paths)
        raw = path.read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError('Plik przekracza 5 MB.')
        return validate_tasks(json.loads(raw.decode('utf-8-sig')))

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
    webview.start(gui='edgechromium', private_mode=True)


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
