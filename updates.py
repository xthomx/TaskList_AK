"""On-demand update checks. No task data or credentials are sent."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from app_version import APP_VERSION

API_URL = 'https://api.github.com/repos/xthomx/TaskList_AK/releases/latest'
RELEASES_URL = 'https://github.com/xthomx/TaskList_AK/releases/latest'
ASSET_NAME = 'TaskListAK-Windows-x64.zip'


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value or '')
    if not match:
        raise ValueError('Nieobsługiwany numer wersji. Oczekiwany format: v1.2.3.')
    return tuple(int(part) for part in match.groups())


def release_result(release, current=APP_VERSION):
    if not isinstance(release, dict):
        raise ValueError('Nieprawidłowa odpowiedź GitHuba.')
    if release.get('draft') or release.get('prerelease'):
        return {'status': 'unavailable', 'current': current}
    latest = release.get('tag_name', '')
    newer = version_tuple(latest) > version_tuple(current)
    ready = any(a.get('name') == ASSET_NAME and a.get('state') == 'uploaded'
                for a in release.get('assets', []) if isinstance(a, dict))
    return {'status': ('available' if ready else 'pending') if newer else 'current',
            'current': current, 'latest': latest}


def check_updates():
    request = Request(API_URL, headers={'Accept': 'application/vnd.github+json',
                                       'User-Agent': 'TaskListAK/' + APP_VERSION})
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError('Odpowiedź GitHuba jest zbyt duża.')
        return release_result(json.loads(raw))
    except HTTPError as exc:
        if exc.code == 404:
            return {'status': 'unavailable', 'current': APP_VERSION}
        if exc.code in (403, 429):
            return {'status': 'error', 'message': 'GitHub ograniczył liczbę zapytań. Spróbuj później.'}
        return {'status': 'error', 'message': 'GitHub jest chwilowo niedostępny. Spróbuj później.'}
    except (URLError, TimeoutError, OSError):
        return {'status': 'error', 'message': 'Brak połączenia z GitHubem. Sprawdź internet i spróbuj ponownie.'}
    except (ValueError, TypeError, AttributeError):
        return {'status': 'error', 'message': 'Nie udało się odczytać informacji o wydaniu.'}
