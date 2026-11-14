"""Exit and replacement failures retain the student's current measurement."""

from base64 import b64encode
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nuclemu.web_session import Application
from tests.test_web_instrument_records import course


class ExitTransactionTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = 0
        self.app = Application({'boxes': course()}, folder.name, lambda: self.now)
        self.app.open({'experiment': 'boxes'})
        self.call('output', output='detector', enabled=True)
        self.call('start_group', component='pair')
        self.now = 3
        self.app.state()
        self.call('snapshot_group', component='pair', device='a', title='exit record', acquisitions={'a': 1, 'b': 1})

    def call(self, action, **fields):
        return self.app.request('/api/action', dict(session=self.app.lab.id, action=action, **fields))

    def test_failed_replacement_keeps_cache_confirmation_and_can_return(self):
        token = self.call('freeze')['confirmation_id']
        lab = self.app.lab
        before = (lab.work.session.snapshots, deepcopy(lab.exchange.document), lab.work.session.time_s)
        self.now = 30
        with self.assertRaises(ValueError):
            self.app.request('/api/replace_package', dict(session=lab.id, confirmation_id=token,
                file=b64encode(b'bad experiment file').decode()))
        self.assertIs(self.app.lab, lab)
        self.assertEqual((lab.work.session.snapshots, lab.exchange.document, lab.work.session.time_s), before)
        self.assertEqual(lab.confirmation_id, token)
        self.assertTrue(lab.frozen)
        self.call('continue', confirmation_id=token)
        self.now = 31
        state = self.app.state()
        self.assertFalse(state['frozen'])
        self.assertEqual(state['instruments']['a']['exposure_s'], 4)
        self.assertEqual(state['instruments']['b']['exposure_s'], 4)

    def test_download_failure_keeps_exit_retry_and_success_does_not_confirm_disk_save(self):
        from unittest.mock import patch
        token = self.call('freeze')['confirmation_id']
        lab = self.app.lab
        document = deepcopy(lab.exchange.document)
        with patch.object(lab.exchange, 'download_package', side_effect=OSError('download failed')):
            with self.assertRaises(OSError):
                self.app.request('/api/download', dict(session=lab.id, scope='experiment'))
        self.assertEqual(lab.exchange.document['items'], document['items'])
        self.assertEqual(lab.confirmation_id, token)
        self.assertTrue(lab.frozen)
        before = deepcopy(lab.state()['unsaved'])
        raw = self.app.request('/api/download', dict(session=lab.id, scope='experiment'))[2]
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'exit.nuclemu'
            path.write_bytes(raw)
            from nuclemu.exchange import load_package
            self.assertEqual(len(load_package(path)['items']), 2)
        self.assertEqual(lab.state()['unsaved'], before)
        self.assertEqual(lab.confirmation_id, token)
        self.assertTrue(lab.frozen)
        self.assertIn('未确认文件保存成功', lab.state()['export_notice'])


if __name__ == '__main__':
    unittest.main()
