import datetime as dt
import struct
import unittest

import calendar_import
import mail_import
from tests.test_mail_import import FakeOle, u16, systime_entry


def bool_entry(pid, value):
    return struct.pack('<HHI', 0x000B, pid, 0) + bytes([1 if value else 0]) + b'\x00' * 7


def appointment(start, end, all_day=False, swap=False, location='Sala 3'):
    """Atrapa elementu kalendarza: nazwane właściwości (LID 0x820D/0x820E/0x8215/0x8208) w strumieniach nameid."""
    entries = b''.join(struct.pack('<IHH', lid, *((idx, 6) if swap else (6, idx)))
                       for lid, idx in ((0x820D, 0), (0x820E, 1), (0x8215, 2), (0x8208, 3)))
    props = b'\x00' * 32 + systime_entry(0x8000, start) + systime_entry(0x8001, end) + bool_entry(0x8002, all_day)
    return FakeOle({
        '__properties_version1.0': props,
        '__nameid_version1.0/__substg1.0_00020102': calendar_import.APPT_GUID.bytes_le,
        '__nameid_version1.0/__substg1.0_00030102': entries,
        '__substg1.0_8003001F': u16(location),
        '__substg1.0_0037001F': u16('Spotkanie z klientem'),
        '__substg1.0_0C1A001F': u16('Kowalski Jan'),
        '__substg1.0_1000001F': u16('Omówić ofertę.'),
    })


UTC = dt.timezone.utc


class AppointmentMsgTests(unittest.TestCase):
    def local(self, moment):
        return moment.astimezone()

    def test_timed_appointment_keeps_outlook_day_and_hours(self):
        start, end = dt.datetime(2026, 11, 18, 9, 0, tzinfo=UTC), dt.datetime(2026, 11, 18, 10, 30, tzinfo=UTC)
        for swap in (False, True):                               # oba warianty kolejności pól wpisu nameid
            with self.subTest(swap=swap):
                r = calendar_import.parse_appointment_ole(appointment(start, end, swap=swap))
                self.assertEqual(r['kind'], 'appointment')
                self.assertEqual(r['subject'], 'Spotkanie z klientem')
                self.assertEqual((r['date'], r['start'], r['end']),
                                 (self.local(start).date().isoformat(), self.local(start).strftime('%H:%M'), self.local(end).strftime('%H:%M')))
                self.assertIn('Miejsce: Sala 3', r['notes'])
                self.assertIn('Omówić ofertę.', r['notes'])

    def test_all_day_and_multi_day_become_all_day_tasks(self):
        s = dt.datetime(2026, 11, 18, 0, 0).astimezone().astimezone(UTC)           # lokalna północ
        one = calendar_import.parse_appointment_ole(appointment(s, s + dt.timedelta(days=1), all_day=True))
        self.assertEqual((one['date'], one['end_date'], one['start']), ('2026-11-18', '2026-11-18', ''))
        three = calendar_import.parse_appointment_ole(appointment(s, s + dt.timedelta(days=3), all_day=True))
        self.assertEqual((three['date'], three['end_date']), ('2026-11-18', '2026-11-20'))

    def test_regular_message_is_not_an_appointment(self):
        self.assertIsNone(calendar_import.parse_appointment_ole(FakeOle({'__substg1.0_0037001F': u16('Zwykły mail')})))


class TimingTests(unittest.TestCase):
    def test_rules(self):
        d = dt.datetime
        self.assertEqual(calendar_import.timing(d(2026, 11, 18, 10), d(2026, 11, 18, 11), False),
                         {'date': '2026-11-18', 'end_date': '2026-11-18', 'start': '10:00', 'end': '11:00'})
        self.assertEqual(calendar_import.timing(d(2026, 11, 18, 22), d(2026, 11, 19, 2), False)['end_date'], '2026-11-19')   # przez północ
        self.assertEqual(calendar_import.timing(d(2026, 11, 18, 10), d(2026, 11, 18, 10), False)['end'], '')                 # bez czasu trwania


BS = chr(92)
ICS = ('BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Zebranie zespołu\r\nDTSTART:20261118T100000\r\nDTEND:20261118T113000\r\n'
       'LOCATION:Sala 3' + BS + ', piętro 2\r\nDESCRIPTION:Punkt 1' + BS + 'nPunkt 2 dłuższy tekst \r\n zawinięty\r\nORGANIZER;CN=Kowalski Jan:mailto:j@x.pl\r\n'
       'ATTENDEE;CN=Nowak Anna:mailto:a@x.pl\r\nRRULE:FREQ=WEEKLY\r\nEND:VEVENT\r\n'
       'BEGIN:VEVENT\r\nSUMMARY:Urlop\r\nDTSTART;VALUE=DATE:20261123\r\nDTEND;VALUE=DATE:20261126\r\nEND:VEVENT\r\n'
       'BEGIN:VEVENT\r\nSUMMARY:Z UTC\r\nDTSTART:20261118T090000Z\r\nDURATION:PT45M\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')


class IcsTests(unittest.TestCase):
    def test_events_keep_day_and_hours(self):
        r = mail_import.parse_mail('kalendarz.ics', ICS.encode('utf-8'))
        items = r['items']
        self.assertEqual(len(items), 3)
        first = items[0]
        self.assertEqual((first['subject'], first['date'], first['start'], first['end']), ('Zebranie zespołu', '2026-11-18', '10:00', '11:30'))
        self.assertIn('Sala 3, piętro 2', first['notes'])
        self.assertIn('Punkt 1\nPunkt 2 dłuższy tekst zawinięty', first['notes'])
        self.assertIn('Nowak Anna', first['notes'])
        self.assertTrue(first['recurring'])
        self.assertEqual((items[1]['date'], items[1]['end_date'], items[1]['start']), ('2026-11-23', '2026-11-25', ''))   # DTEND dnia jest wyłączny
        utc = dt.datetime(2026, 11, 18, 9, 0, tzinfo=UTC).astimezone()
        self.assertEqual((items[2]['start'], items[2]['end']), (utc.strftime('%H:%M'), (utc + dt.timedelta(minutes=45)).strftime('%H:%M')))

    def test_errors(self):
        with self.assertRaisesRegex(ValueError, 'terminów'):
            mail_import.parse_mail('x.ics', b'BEGIN:VCALENDAR\r\nEND:VCALENDAR')
        single = mail_import.parse_mail('x.ics', ICS.split('BEGIN:VEVENT')[0].encode() + b'BEGIN:VEVENT' + ICS.split('BEGIN:VEVENT')[1].encode() + b'END:VCALENDAR\r\n')
        self.assertNotIn('items', single)


if __name__ == '__main__':
    unittest.main()
