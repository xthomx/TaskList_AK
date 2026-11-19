"""Zadanie na podstawie terminu z kalendarza Outlooka: element .msg (przeciągnięty z kalendarza) lub plik iCalendar (.ics).
Zadanie dostaje dokładnie ten dzień i godziny, które termin ma w Outlooku. Dane nie opuszczają komputera."""
import datetime as dt
import re
import struct
import uuid

from mail_import import MAX_NOTES, _body, _clean, _stream_text

MAX_EVENTS = 200
PT_BOOLEAN, PT_SYSTIME = 0x000B, 0x0040
APPT_GUID = uuid.UUID('00062002-0000-0000-c000-000000000046')       # PSETID_Appointment
PS_MAPI = uuid.UUID('00020328-0000-0000-c000-000000000046')
PS_PUBLIC_STRINGS = uuid.UUID('00020329-0000-0000-c000-000000000046')
LID_LOCATION, LID_START, LID_END, LID_ALLDAY, LID_RECURRING = 0x8208, 0x820D, 0x820E, 0x8215, 0x8223
UTC = dt.timezone.utc


# ---------------------------------------------------------------- wspólne
def _local(moment):
    """Chwila w UTC (lub z strefą) -> czas lokalny komputera, taki jak pokazuje Outlook."""
    try:
        return moment.astimezone()
    except (OverflowError, OSError, ValueError):
        return moment


def timing(start, end, all_day):
    """Dzień i godziny zadania. Termin wielodniowy (także godzinowy) staje się zadaniem wielodniowym całodniowym."""
    if end is None or end < start:
        end = start
    if all_day:
        last = (end - dt.timedelta(seconds=1)).date() if end > start else start.date()
        return {'date': start.date().isoformat(), 'end_date': max(last, start.date()).isoformat(), 'start': '', 'end': ''}
    effective = end - dt.timedelta(minutes=1) if end > start else end
    if effective.date() > start.date():
        return {'date': start.date().isoformat(), 'end_date': effective.date().isoformat(), 'start': '', 'end': ''}
    return {'date': start.date().isoformat(), 'end_date': start.date().isoformat(), 'start': start.strftime('%H:%M'),
            'end': end.strftime('%H:%M') if end > start else ''}


def _when_text(t):
    if t['end_date'] != t['date']:
        return f"{t['date']} – {t['end_date']} (cały dzień)"
    if not t['start']:
        return f"{t['date']} (cały dzień)"
    return f"{t['date']} {t['start']}" + (f"–{t['end']}" if t['end'] else '')


def _result(subject, t, location, organizer, attendees, recurring, body):
    head = [f"Termin w Outlooku: {_when_text(t)}"]
    for label, value in (('Miejsce', location), ('Organizator', organizer), ('Uczestnicy', attendees)):
        if value:
            head.append(f'{label}: {value}')
    if recurring:
        head.append('Termin cykliczny — data to wystąpienie z przeciągniętego elementu; sprawdź, czy się zgadza.')
    text = '\n'.join(head) + (('\n\n' + _clean(body)) if _clean(body) else '')
    if len(text) > MAX_NOTES:
        text = text[:MAX_NOTES - 1].rstrip() + '…'
    return {'kind': 'appointment', 'subject': (subject or '').strip()[:300] or '(bez tematu)', 'notes': text,
            'recurring': bool(recurring), 'location': location, **t}


# ---------------------------------------------------------------- .msg (przeciągnięty termin z kalendarza)
def _fixed_props(ole):
    name = '__properties_version1.0'
    if not ole.exists(name):
        return {}
    data = ole.openstream(name).read()
    out = {}
    for off in range(32, len(data) - 15, 16):                 # nagłówek wiadomości głównej: 32 bajty
        ptype, pid = struct.unpack_from('<HH', data, off)
        out[pid] = (ptype, data[off + 8:off + 16])
    return out


def _named_ids(ole, swap=False):
    """(GUID, LID) -> identyfikator właściwości (0x8000 + indeks). Kolejność pól wpisu bywa opisywana różnie,
    dlatego wywołujący próbuje obu wariantów (swap) i wybiera ten, który daje poprawne daty."""
    base = '__nameid_version1.0/'
    if not (ole.exists(base + '__substg1.0_00020102') and ole.exists(base + '__substg1.0_00030102')):
        return {}
    raw_guids = ole.openstream(base + '__substg1.0_00020102').read()
    entries = ole.openstream(base + '__substg1.0_00030102').read()
    guids = [uuid.UUID(bytes_le=raw_guids[i:i + 16]) for i in range(0, len(raw_guids) - 15, 16)]
    out = {}
    for i in range(0, len(entries) - 7, 8):
        name_id, a, b = struct.unpack_from('<IHH', entries, i)
        guid_kind, prop_index = (b, a) if swap else (a, b)
        if guid_kind & 1:
            continue                                          # nazwa tekstowa, nie liczbowa
        g = guid_kind >> 1
        guid = PS_MAPI if g == 1 else PS_PUBLIC_STRINGS if g == 2 else (guids[g - 3] if 0 <= g - 3 < len(guids) else None)
        if guid is not None:
            out[(guid, name_id)] = 0x8000 + prop_index
    return out


def _filetime(raw8):
    ticks = struct.unpack('<Q', raw8)[0]
    if not ticks:
        return None
    try:
        return _local(dt.datetime(1601, 1, 1, tzinfo=UTC) + dt.timedelta(microseconds=ticks // 10))
    except OverflowError:
        return None


def parse_appointment_ole(ole):
    """Zwraca wynik dla elementu kalendarza albo None, gdy to zwykła wiadomość."""
    fixed = _fixed_props(ole)
    for swap in (False, True):
        ids = _named_ids(ole, swap)
        ps, pe = ids.get((APPT_GUID, LID_START)), ids.get((APPT_GUID, LID_END))
        if ps in fixed and fixed[ps][0] == PT_SYSTIME:
            start = _filetime(fixed[ps][1])
            if start is not None:
                break
    else:
        return None
    end = _filetime(fixed[pe][1]) if pe in fixed and fixed[pe][0] == PT_SYSTIME else None
    flag = lambda lid: (lambda pid: pid in fixed and fixed[pid][0] == PT_BOOLEAN and fixed[pid][1][0] != 0)(ids.get((APPT_GUID, lid)))
    all_day = flag(LID_ALLDAY)
    location = ''
    pl = ids.get((APPT_GUID, LID_LOCATION))
    if pl:
        location = _stream_text(ole, '%04X' % pl)
    organizer = _stream_text(ole, '0C1A')
    attendees = _stream_text(ole, '0E04').replace(';', ',')
    return _result(_stream_text(ole, '0037'), timing(start, end, all_day), location, organizer, attendees,
                   flag(LID_RECURRING), _body(ole))


# ---------------------------------------------------------------- .ics
def _unfold(text):
    return re.sub(r'\r?\n[ \t]', '', text.replace('\r\n', '\n').replace('\r', '\n'))


def _unescape(value):
    return (value.replace('\\n', '\n').replace('\\N', '\n').replace('\\,', ',').replace('\\;', ';').replace('\\\\', '\\')).strip()


def _split(line):
    head, _, value = line.partition(':')
    name, *params = head.split(';')
    return name.upper(), {p.partition('=')[0].upper(): p.partition('=')[2].strip('"') for p in params}, value


def _ics_moment(value, params):
    """Zwraca (chwila, całodniowy). Czas z 'Z' to UTC (przeliczany na lokalny); czas ze strefą IANA też; reszta to czas lokalny."""
    value = value.strip()
    if len(value) == 8 and value.isdigit():
        return dt.datetime(int(value[:4]), int(value[4:6]), int(value[6:8])), True
    match = re.fullmatch(r'(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)?(Z?)', value)
    if not match:
        raise ValueError('Nieobsługiwany format daty w pliku .ics: ' + value[:20])
    y, mo, d, h, mi, s, z = match.groups()
    moment = dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    if z:
        return _local(moment.replace(tzinfo=UTC)).replace(tzinfo=None), False
    tzid = params.get('TZID', '')
    if tzid:
        try:
            from zoneinfo import ZoneInfo
            return _local(moment.replace(tzinfo=ZoneInfo(tzid))).replace(tzinfo=None), False
        except Exception:                                      # nazwa strefy Windows / brak bazy stref: czas traktujemy jako lokalny
            pass
    return moment, False


def _duration(value):
    match = re.fullmatch(r'P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?', value.strip())
    if not match:
        return None
    w, d, h, m, s = (int(x or 0) for x in match.groups())
    return dt.timedelta(weeks=w, days=d, hours=h, minutes=m, seconds=s)


def parse_ics(raw):
    for codec in ('utf-8-sig', 'cp1250'):
        try:
            text = raw.decode(codec)
            break
        except UnicodeDecodeError:
            continue
    if 'BEGIN:VEVENT' not in text.upper():
        raise ValueError('W pliku nie ma terminów kalendarza (.ics).')
    events, current, depth = [], None, 0
    for line in _unfold(text).split('\n'):
        key = line.strip().upper()
        if key == 'BEGIN:VEVENT':
            current = []
        elif key == 'END:VEVENT' and current is not None:
            events.append(current)
            current = None
        elif current is not None and line.strip():
            current.append(line)
    out = []
    for lines in events[:MAX_EVENTS]:
        props = {}
        attendees = []
        for line in lines:
            name, params, value = _split(line)
            if name == 'ATTENDEE':
                attendees.append(params.get('CN') or value.replace('mailto:', ''))
            else:
                props.setdefault(name, (params, value))
        if 'DTSTART' not in props:
            continue
        start, all_day = _ics_moment(props['DTSTART'][1], props['DTSTART'][0])
        end = None
        if 'DTEND' in props:
            end, _ = _ics_moment(props['DTEND'][1], props['DTEND'][0])
        elif 'DURATION' in props and _duration(props['DURATION'][1]) is not None:
            end = start + _duration(props['DURATION'][1])
        organizer = props.get('ORGANIZER', ({}, ''))
        out.append(_result(_unescape(props.get('SUMMARY', ({}, ''))[1]), timing(start, end, all_day),
                           _unescape(props.get('LOCATION', ({}, ''))[1]),
                           organizer[0].get('CN') or organizer[1].replace('mailto:', ''),
                           ', '.join(attendees[:10]) + (' …' if len(attendees) > 10 else ''),
                           'RRULE' in props, _unescape(props.get('DESCRIPTION', ({}, ''))[1])))
    if not out:
        raise ValueError('W pliku nie znaleziono terminów z datą rozpoczęcia.')
    first = dict(out[0])
    if len(out) > 1:
        first['items'] = out
    return first
