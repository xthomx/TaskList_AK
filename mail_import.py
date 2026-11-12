"""Zadanie na podstawie wiadomości e-mail: Outlook (.msg) i standardowe .eml. Dane nie opuszczają komputera."""
import datetime as dt
import email
from email import policy
from html.parser import HTMLParser
import io
import re
import struct

MAX_MAIL_BYTES = 25 * 1024 * 1024
MAX_NOTES = 4000
PT_SYSTIME = 0x0040
DATE_TAGS = (0x0039, 0x0E06)          # czas wysłania, czas doręczenia


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.skip += 1
        elif tag in ('br', 'p', 'div', 'tr', 'li', 'h1', 'h2', 'h3'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head') and self.skip:
            self.skip -= 1
        elif tag in ('p', 'div', 'tr', 'li'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(html):
    parser = _Text()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return re.sub(r'<[^>]+>', ' ', html)
    return ''.join(parser.parts)


def _clean(text):
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n').replace('\xa0', ' ')
    text = re.sub(r'[ \t]+\n', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _address(name, addr):
    name, addr = (name or '').strip(), (addr or '').strip()
    return f'{name} <{addr}>' if name and addr and name != addr else (name or addr)


def build_notes(mail):
    """Notatka zadania: nagłówek wiadomości + początek treści (limit zgodny z walidacją zapisu)."""
    head = [f'{label}: {mail[key]}' for label, key in
            (('Od', 'from'), ('Do', 'to'), ('Data', 'sent'), ('Załączniki', 'attachments')) if mail.get(key)]
    body = _clean(mail.get('body'))
    notes = '\n'.join(head) + ('\n\n' + body if body else '')
    return notes if len(notes) <= MAX_NOTES else notes[:MAX_NOTES - 1].rstrip() + '…'


def _result(subject, sender, to, sent, attachments, body):
    mail = {'subject': (subject or '').strip() or '(bez tematu)', 'from': sender, 'to': to,
            'sent': sent.strftime('%Y-%m-%d %H:%M') if sent else '', 'attachments': ', '.join(attachments),
            'body': body}
    return {'subject': mail['subject'][:300], 'from': sender, 'date': sent.strftime('%Y-%m-%d') if sent else '',
            'notes': build_notes(mail)}


# ---------------------------------------------------------------- .eml
def parse_eml(raw):
    msg = email.message_from_bytes(raw, policy=policy.default)
    if not (msg['subject'] or msg['from'] or msg['date']):
        raise ValueError('To nie wygląda na wiadomość e-mail (.eml).')
    part = msg.get_body(preferencelist=('plain', 'html'))
    body = ''
    if part is not None:
        try:
            body = part.get_content()
        except (LookupError, UnicodeError):
            body = ''
        if part.get_content_type() == 'text/html':
            body = html_to_text(body)
    sent = None
    try:
        sent = email.utils.parsedate_to_datetime(str(msg['date'])).astimezone() if msg['date'] else None
    except (TypeError, ValueError):
        pass
    attachments = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
    return _result(str(msg['subject'] or ''), str(msg['from'] or ''), str(msg['to'] or ''), sent, attachments, body)


# ---------------------------------------------------------------- .msg
def _stream_text(ole, tag):
    for suffix, codec in (('001F', 'utf-16-le'), ('001E', 'cp1250')):
        name = '__substg1.0_%s%s' % (tag, suffix)
        if ole.exists(name):
            return ole.openstream(name).read().decode(codec, 'replace').rstrip('\x00').strip()
    return ''


def _systime(ole, wanted=DATE_TAGS):
    name = '__properties_version1.0'
    if not ole.exists(name):
        return None
    data = ole.openstream(name).read()
    found = {}
    for off in range(32, len(data) - 15, 16):         # nagłówek wiadomości głównej ma 32 bajty
        ptype, pid = struct.unpack_from('<HH', data, off)
        if ptype == PT_SYSTIME and pid in wanted:
            ticks = struct.unpack_from('<Q', data, off + 8)[0]
            if ticks:
                found[pid] = dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(microseconds=ticks // 10)
    for pid in wanted:
        if pid in found:
            try:
                return found[pid].astimezone()
            except (OverflowError, OSError, ValueError):
                return found[pid]
    return None


def _body(ole):
    text = _stream_text(ole, '1000')
    if text:
        return text
    name = '__substg1.0_10130102'                      # treść HTML (bajty)
    if ole.exists(name):
        raw = ole.openstream(name).read()
        for codec in ('utf-8', 'cp1250'):
            try:
                return html_to_text(raw.decode(codec))
            except UnicodeDecodeError:
                continue
    return ''


def _attachments(ole):
    names = []
    for path in ole.listdir(streams=True, storages=False):
        if len(path) == 2 and path[0].startswith('__attach_version1.0_') and path[1] in ('__substg1.0_3707001F', '__substg1.0_3704001F'):
            raw = ole.openstream(path).read()
            text = raw.decode('utf-16-le' if path[1].endswith('001F') else 'cp1250', 'replace').rstrip('\x00').strip()
            if text and text not in names:
                names.append(text)
    return names


def parse_ole(ole):
    smtp, other = _stream_text(ole, '5D01'), _stream_text(ole, '0C1F')
    addr = smtp if '@' in smtp else (other if '@' in other else '')    # adres wewnętrzny Exchange (/O=...) pomijamy
    subject = _stream_text(ole, '0037')
    sender = _address(_stream_text(ole, '0C1A'), addr)
    if not (subject or sender or _stream_text(ole, '1000')):
        raise ValueError('Nie udało się odczytać wiadomości z pliku .msg.')
    return _result(subject, sender, _stream_text(ole, '0E04').replace(';', ','), _systime(ole),
                   _attachments(ole), _body(ole))


def parse_msg(raw):
    import olefile
    try:
        ole = olefile.OleFileIO(io.BytesIO(raw))
    except Exception as exc:
        raise ValueError('To nie jest poprawny plik wiadomości Outlooka (.msg).') from exc
    try:
        return parse_ole(ole)
    finally:
        ole.close()


def parse_mail(name, raw):
    """Wybiera parser po rozszerzeniu; rzuca ValueError z czytelnym komunikatem."""
    if len(raw) > MAX_MAIL_BYTES:
        raise ValueError('Wiadomość jest zbyt duża (limit 25 MB).')
    lower = (name or '').lower()
    if lower.endswith('.msg'):
        return parse_msg(raw)
    if lower.endswith('.eml'):
        return parse_eml(raw)
    raise ValueError('Obsługiwane są pliki .msg (Outlook) i .eml.')
