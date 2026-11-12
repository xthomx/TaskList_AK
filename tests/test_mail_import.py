import datetime as dt
from email.message import EmailMessage
import struct
import unittest

import mail_import


class FakeOle:
    """Atrapa OleFileIO: słownik nazwa -> bajty (nazwy strumieni jak w pliku .msg)."""
    def __init__(self, streams):
        self.streams = streams

    def exists(self, name):
        return name in self.streams

    def openstream(self, name):
        import io
        key = '/'.join(name) if isinstance(name, (list, tuple)) else name
        return io.BytesIO(self.streams[key])

    def listdir(self, streams=True, storages=False):
        return [k.split('/') for k in self.streams if '/' in k]


def u16(text):
    return text.encode('utf-16-le') + b'\x00\x00'


def systime_entry(pid, when):
    ticks = int((when - dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc)).total_seconds() * 10_000_000)
    return struct.pack('<HHI', 0x0040, pid, 0) + struct.pack('<Q', ticks)


SENT = dt.datetime(2026, 11, 10, 8, 30, tzinfo=dt.timezone.utc)


class MailTests(unittest.TestCase):
    def test_eml_plain_text_with_polish_characters(self):
        m = EmailMessage()
        m['Subject'] = 'Zażółć gęślą jaźń — oferta'
        m['From'] = 'Jan Kowalski <jan@example.com>'
        m['To'] = 'ja@example.com'
        m['Date'] = 'Tue, 10 Nov 2026 09:30:00 +0100'
        m.set_content('Dzień dobry,\n\nproszę o odpowiedź do piątku.\n\n\n\nPozdrawiam')
        m.add_attachment(b'x', maintype='application', subtype='pdf', filename='oferta.pdf')
        result = mail_import.parse_mail('oferta.eml', m.as_bytes())
        self.assertEqual(result['subject'], 'Zażółć gęślą jaźń — oferta')
        self.assertEqual(result['from'], 'Jan Kowalski <jan@example.com>')
        self.assertEqual(result['date'], '2026-11-10')
        self.assertIn('Od: Jan Kowalski <jan@example.com>', result['notes'])
        self.assertIn('Załączniki: oferta.pdf', result['notes'])
        self.assertIn('proszę o odpowiedź do piątku.\n\nPozdrawiam', result['notes'])

    def test_eml_html_only_is_converted_to_text(self):
        m = EmailMessage()
        m['Subject'] = 'HTML'
        m['From'] = 'a@example.com'
        m.set_content('<html><head><style>p{color:red}</style></head><body><p>Pierwszy</p><p>Drugi <b>akapit</b></p></body></html>', subtype='html')
        notes = mail_import.parse_mail('x.eml', m.as_bytes())['notes']
        self.assertIn('Pierwszy', notes)
        self.assertIn('Drugi akapit', notes)
        self.assertNotIn('color', notes)

    def test_msg_properties(self):
        header = b'\x00' * 32
        props = header + systime_entry(0x0039, SENT)
        ole = FakeOle({
            '__substg1.0_0037001F': u16('Zapytanie ofertowe'),
            '__substg1.0_0C1A001F': u16('Nowak Anna'),
            '__substg1.0_0C1F001F': u16('/O=EXCHANGE/CN=RECIPIENTS/CN=NOWAK'),
            '__substg1.0_5D01001F': u16('anna.nowak@firma.pl'),
            '__substg1.0_0E04001F': u16('Kowalski Jan; Wiśniewski Piotr'),
            '__substg1.0_1000001F': u16('Treść wiadomości\r\n\r\n\r\n\r\nstopka'),
            '__properties_version1.0': props,
            '__attach_version1.0_#00000000/__substg1.0_3707001F': u16('umowa.docx'),
        })
        result = mail_import.parse_ole(ole)
        self.assertEqual(result['subject'], 'Zapytanie ofertowe')
        self.assertEqual(result['from'], 'Nowak Anna <anna.nowak@firma.pl>')
        self.assertRegex(result['date'], r'^2026-11-1[01]$')
        self.assertIn('Do: Kowalski Jan, Wiśniewski Piotr', result['notes'])
        self.assertIn('Załączniki: umowa.docx', result['notes'])
        self.assertIn('Treść wiadomości\n\nstopka', result['notes'])

    def test_msg_ansi_streams_and_html_body_fallback(self):
        ole = FakeOle({
            '__substg1.0_0037001E': 'Zażółć'.encode('cp1250'),
            '__substg1.0_10130102': '<p>Treść <b>HTML</b></p>'.encode('utf-8'),
        })
        result = mail_import.parse_ole(ole)
        self.assertEqual(result['subject'], 'Zażółć')
        self.assertIn('Treść HTML', result['notes'])
        self.assertEqual(result['date'], '')

    def test_empty_or_broken_input_gives_readable_errors(self):
        with self.assertRaisesRegex(ValueError, 'odczytać'):
            mail_import.parse_ole(FakeOle({}))
        with self.assertRaisesRegex(ValueError, '.msg'):
            mail_import.parse_mail('x.msg', b'to nie jest plik OLE')
        with self.assertRaisesRegex(ValueError, 'Obsługiwane'):
            mail_import.parse_mail('x.txt', b'abc')
        with self.assertRaisesRegex(ValueError, 'zbyt duża'):
            mail_import.parse_mail('x.eml', b'x' * (mail_import.MAX_MAIL_BYTES + 1))

    def test_notes_respect_storage_limit(self):
        notes = mail_import.build_notes({'from': 'a@b.pl', 'body': 'x' * 10000})
        self.assertLessEqual(len(notes), mail_import.MAX_NOTES)
        self.assertTrue(notes.endswith('…'))


class ApiMailTests(unittest.TestCase):
    def test_api_parse_mail_decodes_base64_and_validates(self):
        import base64
        import tempfile
        from main import Api
        from storage import Storage
        with tempfile.TemporaryDirectory() as folder:
            api = Api(Storage(folder))
            m = EmailMessage()
            m['Subject'] = 'Temat'
            m['From'] = 'a@example.com'
            m.set_content('Treść')
            result = api.parse_mail('temat.eml', base64.b64encode(m.as_bytes()).decode())
            self.assertEqual(result['subject'], 'Temat')
            with self.assertRaises(ValueError):
                api.parse_mail('temat.eml', 'to nie jest base64!!')
            with self.assertRaises(ValueError):
                api.parse_mail('temat.exe', base64.b64encode(b'abc').decode())
