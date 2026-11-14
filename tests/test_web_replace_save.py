"""Saving before replacement must finish the old archive transaction first."""
from base64 import b64encode
from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nuclemu.catalog import discover
from nuclemu.core import Session
from nuclemu.exchange import capture_session, package_bytes
from nuclemu.web_session import Application
from tests.legacy_web_fixture import legacy_course


class ReplaceSaveTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name
        self.now = 0
        self.definitions = discover()
        old = legacy_course('alpha')
        self.definitions[old.id] = old
        self.app = Application(self.definitions, self.folder, lambda: self.now)
        self.app.open(dict(experiment=old.id))
        self.call('start', duration=2)
        self.now = 1
        self.call('save', exit=False)
        self.original_id = self.app.lab.archive_id
        self.original = deepcopy(self.app.store.read(self.original_id))
        self.app.lab = None
        self.app.open(dict(archive=self.original_id))
        self.call('analysis', roi=[12, 34])
        self.token = self.call('freeze')['confirmation_id']
        self.replacement = package_bytes(capture_session(Session(self.definitions['beta'])))

    def call(self, action, **fields):
        return self.app.request('/api/action', dict(session=self.app.lab.id, action=action, **fields))

    def replace(self, *, save, raw=None):
        return self.app.request('/api/replace_package', dict(session=self.app.lab.id,
            confirmation_id=self.token, save=save,
            file=b64encode(self.replacement if raw is None else raw).decode()))

    def test_save_replacement_creates_reopenable_copy_with_current_roi(self):
        old_lab = self.app.lab
        state = self.replace(save=True)
        self.assertEqual(state['experiment'], 'beta')
        copied = self.app.store.read(old_lab.archive_id)
        self.assertNotEqual(old_lab.archive_id, self.original_id)
        self.assertEqual(copied['analysis']['mca']['roi'], [12, 34])
        self.assertEqual(self.app.store.read(self.original_id), self.original)
        reopened = Application(self.definitions, self.folder, lambda: self.now)
        result = reopened.open(dict(archive=old_lab.archive_id))
        self.assertEqual(result['analysis']['roi'], [12, 34])
        self.assertEqual(result['product'], self.original['product'])

    def test_write_failure_keeps_old_session_and_confirmation_for_return(self):
        lab = self.app.lab
        before = deepcopy(lab.document())
        with patch.object(self.app.store, 'write', side_effect=OSError('archive disk failed')):
            with self.assertRaisesRegex(OSError, 'archive disk failed'):
                self.replace(save=True)
        self.assertIs(self.app.lab, lab)
        self.assertEqual(lab.document(), before)
        self.assertEqual(lab.confirmation_id, self.token)
        self.assertTrue(lab.frozen)
        self.assertEqual(self.app.store.read(self.original_id), self.original)
        self.call('continue', confirmation_id=self.token)
        self.assertFalse(lab.frozen)
        self.assertEqual(self.app.state()['analysis']['roi'], [12, 34])

    def test_live_old_protocol_saves_the_last_partial_exposure_before_replacement(self):
        self.app.lab = None
        self.app.open(dict(experiment='legacy_alpha'))
        self.call('start', duration=10)
        self.now += 1.5
        self.call('analysis', roi=[12, 34])
        self.token = self.call('freeze')['confirmation_id']
        lab = self.app.lab
        self.replace(save=True)
        copied = self.app.store.read(lab.archive_id)
        self.assertEqual(copied['analysis']['mca']['roi'], [12, 34])
        self.assertEqual(copied['product']['segments'][-1]['end_s'], 1.5)
        self.assertEqual(self.app.store.read(self.original_id), self.original)

    def test_bad_replacement_is_rejected_before_writing_and_discard_skips_copy(self):
        lab = self.app.lab
        with patch.object(self.app.store, 'write') as writing:
            with self.assertRaises(ValueError):
                self.replace(save=True, raw=b'bad experiment file')
            writing.assert_not_called()
        self.assertIs(self.app.lab, lab)
        self.assertEqual(lab.confirmation_id, self.token)
        self.assertEqual(self.replace(save=False)['experiment'], 'beta')
        archives = [r for r in self.app.store.list() if r['kind'] == 'archive']
        self.assertEqual([r['id'] for r in archives], [self.original_id])
        self.assertEqual(self.app.store.read(self.original_id), self.original)


if __name__ == '__main__':
    unittest.main()
