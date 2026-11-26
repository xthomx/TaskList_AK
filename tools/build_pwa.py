"""Buduje wersję PWA (iPhone / przeglądarka) do folderu site/: index.html, manifest, service worker, ikony.
Użycie: py -3 tools/build_pwa.py [folder_wyjściowy]"""
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app_version import APP_VERSION  # noqa: E402

UI = ROOT / 'ui'
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'site'
ACCENT = (37, 99, 235)


def png(size, pixel):
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw.extend(pixel(x / size, y / size))

    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def icon_pixel(u, v, pad=0.0):
    u, v = (u - 0.5) / (1 - pad) + 0.5, (v - 0.5) / (1 - pad) + 0.5
    # karta kalendarza
    in_card = 0.2 <= u <= 0.8 and 0.24 <= v <= 0.8
    r = 0.07
    if in_card:
        cx, cy = min(max(u, 0.2 + r), 0.8 - r), min(max(v, 0.24 + r), 0.8 - r)
        in_card = (u - cx) ** 2 + (v - cy) ** 2 <= r * r
    if not in_card and not (0.3 <= u <= 0.7 and 0.17 <= v <= 0.3 and (abs(u - 0.33) < 0.03 or abs(u - 0.67) < 0.03)):
        return ACCENT
    if abs(u - 0.33) < 0.03 or abs(u - 0.67) < 0.03:
        if v < 0.32:
            return (255, 255, 255)
    if v < 0.36:
        return (219, 234, 254)
    d = min(seg_dist(u, v, 0.34, 0.58, 0.45, 0.69), seg_dist(u, v, 0.45, 0.69, 0.67, 0.47))
    return ACCENT if d < 0.04 else (255, 255, 255)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    html = (UI / 'index.html').read_text(encoding='utf-8')
    html = html.replace('<link rel="stylesheet" href="style.css">',
                        '<link rel="manifest" href="manifest.webmanifest">\n'
                        '<link rel="apple-touch-icon" href="icon-180.png">\n'
                        '<meta name="theme-color" content="#2563eb">\n'
                        '<meta name="apple-mobile-web-app-capable" content="yes">\n'
                        '<meta name="mobile-web-app-capable" content="yes">\n'
                        '<meta name="apple-mobile-web-app-title" content="TaskList AK">\n'
                        '<meta name="apple-mobile-web-app-status-bar-style" content="default">\n'
                        '<style>' + (UI / 'style.css').read_text(encoding='utf-8') + '</style>')
    html = html.replace('width=device-width, initial-scale=1', 'width=device-width, initial-scale=1, viewport-fit=cover')
    html = html.replace('<!--HELP-->', (UI / 'help.html').read_text(encoding='utf-8'))
    scripts = ((UI / 'app.js').read_text(encoding='utf-8') + '\n</script>\n<script>\n' + (UI / 'cloud.js').read_text(encoding='utf-8')
               + "\n</script>\n<script>if('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(function(){});")
    html = html.replace('<script src="app.js"></script>', '<script>' + scripts + '</script>')
    (OUT / 'index.html').write_text(html, encoding='utf-8')
    manifest = {'name': 'TaskList AK', 'short_name': 'TaskList', 'lang': 'pl', 'start_url': './', 'scope': './',
                'display': 'standalone', 'background_color': '#ffffff', 'theme_color': '#2563eb',
                'icons': [{'src': 'icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                          {'src': 'icon-512.png', 'sizes': '512x512', 'type': 'image/png'},
                          {'src': 'icon-512-maskable.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'}]}
    (OUT / 'manifest.webmanifest').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    sw = ("const CACHE = 'tasklist-ak-%s';\n"
          "const FILES = ['./', 'index.html', 'manifest.webmanifest', 'icon-180.png', 'icon-192.png', 'icon-512.png'];\n"
          "self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(FILES)).then(() => self.skipWaiting())); });\n"
          "self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())); });\n"
          "self.addEventListener('fetch', e => {\n"
          "  const u = new URL(e.request.url);\n"
          "  if(e.request.method !== 'GET' || u.origin !== location.origin) return;\n"
          "  e.respondWith(fetch(e.request).then(r => { const c = r.clone(); caches.open(CACHE).then(x => x.put(e.request, c)); return r; })\n"
          "    .catch(() => caches.match(e.request).then(r => r || caches.match('index.html'))));\n"
          "});\n") % APP_VERSION
    (OUT / 'sw.js').write_text(sw, encoding='utf-8')
    (OUT / 'icon-180.png').write_bytes(png(180, lambda u, v: icon_pixel(u, v)))
    (OUT / 'icon-192.png').write_bytes(png(192, lambda u, v: icon_pixel(u, v)))
    (OUT / 'icon-512.png').write_bytes(png(512, lambda u, v: icon_pixel(u, v)))
    (OUT / 'icon-512-maskable.png').write_bytes(png(512, lambda u, v: icon_pixel(u, v, pad=0.2)))
    (OUT / '.nojekyll').write_text('', encoding='utf-8')
    print('PWA zbudowana w', OUT, 'wersja', APP_VERSION)


if __name__ == '__main__':
    main()
