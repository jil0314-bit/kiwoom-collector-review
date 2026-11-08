"""Offline installer/config tests; only dummy credentials in temporary folders."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import app
import kiwoom
import local_config as c


class InstallTests(unittest.TestCase):
    def test_existing_office_profile_is_preserved(self):
        with patch.object(c,'settings',return_value={}):
            self.assertEqual(c.profile_file('Portfolio.dat',Path('office.dat')),Path('office.dat'))

    def test_unconfigured_notebook_does_not_read_office_profile(self):
        with patch.object(c,'settings',return_value={'notebook_install':True}),patch.object(c,'config_root',return_value=Path('local')):
            self.assertEqual(c.profile_file('Portfolio.dat',Path('office.dat')),Path('local/unconfigured/Portfolio.dat'))

    def test_explicit_profile(self):
        with patch.object(c,'settings',return_value={'hero4_profile':'chosen'}):
            self.assertEqual(c.profile_file('Portfolio.dat',Path('office.dat')),Path('chosen/Portfolio.dat'))

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_encrypted_credential_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(c,'config_root',return_value=Path(tmp)):
            self.assertIsNone(c.read_credentials())
            c.save_credentials('dummy-app-key','dummy-app-secret')
            body=(Path(tmp)/'credentials.dpapi').read_bytes()
            self.assertNotIn(b'dummy-app-key',body);self.assertNotIn(b'dummy-app-secret',body)
            self.assertEqual(c.read_credentials()[:2],('dummy-app-key','dummy-app-secret'))
            (Path(tmp)/'credentials.dpapi').write_bytes(b'invalid-data')
            with self.assertRaises(ValueError):c.read_credentials()

    def test_empty_or_multiline_credentials_rejected(self):
        for key,secret in [('', 'dummy'),('dummy',''),('dummy\n','dummy')]:
            with self.assertRaises(ValueError):c.save_credentials(key,secret)

    def test_notebook_explicit_credentials_precede_other_environment(self):
        with patch.object(c,'settings',return_value={'notebook_install':True}),patch.object(c,'read_credentials',return_value=('dummy-new','dummy-secret','protected')),patch.dict(os.environ,{'KIWOOM_APP_KEY':'dummy-old','KIWOOM_SECRET_KEY':'dummy-old-secret'}):
            self.assertEqual(kiwoom.credentials(),('dummy-new','dummy-secret','protected'))

    def test_notebook_memo_write_requires_explicit_enable(self):
        with patch.object(c,'settings',return_value={'notebook_install':True,'memo_write_enabled':False}),patch.object(app.threading,'Thread') as thread:
            app.memo_tick();thread.assert_not_called()


if __name__=='__main__':unittest.main()
