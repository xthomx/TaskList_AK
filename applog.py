"""Prosty dziennik zdarzeń programu: logi\\program.log obok programu (z rotacją)."""
import sys
import time

from storage import log_dir

MAX_BYTES = 512 * 1024


def log(message):
    if 'unittest' in sys.modules:
        return
    try:
        folder = log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'program.log'
        if path.exists() and path.stat().st_size > MAX_BYTES:
            path.replace(folder / 'program.1.log')
        with path.open('a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + str(message).replace('\n', ' ') + '\n')
    except OSError:
        pass
