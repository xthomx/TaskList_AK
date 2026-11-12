import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from updates import check_updates, release_result, version_tuple, ASSET_NAME
from app_version import APP_VERSION

class UpdateTests(unittest.TestCase):
    def release(self, version='v1.1.0', assets=True):
        return {'tag_name': version, 'assets': [{'name': ASSET_NAME, 'state': 'uploaded'}] if assets else []}

    def test_numeric_versions(self):
        self.assertGreater(version_tuple('v1.10.0'), version_tuple('1.9.0'))
        for tag in ('latest', 'v1.0.0-rc1', '1.0', ''):
            with self.assertRaises(ValueError): version_tuple(tag)

    def test_new_equal_older_and_missing_package(self):
        self.assertEqual(release_result(self.release(), '1.0.0')['status'], 'available')
        for tag in ('v1.0.0', 'v0.9.0'):
            self.assertEqual(release_result(self.release(tag), '1.0.0')['status'], 'current')
        self.assertEqual(release_result(self.release(assets=False), '1.0.0')['status'], 'pending')
        self.assertEqual(release_result(dict(self.release(), prerelease=True))['status'], 'unavailable')

    def test_network_errors(self):
        for error, status in [(HTTPError('',404,'',{},None),'unavailable'),
                              (HTTPError('',403,'',{},None),'error'),
                              (URLError('offline'),'error'), (TimeoutError(),'error')]:
            with patch('updates.urlopen', side_effect=error):
                self.assertEqual(check_updates()['status'],status)

    def test_response_and_timeout(self):
        with patch('updates.urlopen', return_value=io.BytesIO(json.dumps(self.release('v'+str(version_tuple(APP_VERSION)[0]+1)+'.0.0')).encode())) as request:
            self.assertEqual(check_updates()['status'],'available')
            self.assertEqual(request.call_args.kwargs['timeout'],10)
        with patch('updates.urlopen', return_value=io.BytesIO(b'invalid')):
            self.assertEqual(check_updates()['status'],'error')
