"""Review scenarios at the Web boundary, including immutable window records."""

import json
from base64 import b64encode
from tempfile import TemporaryDirectory
import unittest

from nuclemu.catalog import describe
from nuclemu.experiments.beta import EXPERIMENT, DETECTOR_OUTPUT
from nuclemu.web_session import WebLab
from nuclemu.web_session import Application
from nuclemu.catalog import discover
from nuclemu.web_store import ArchiveStore


class WebRevisionTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = 0
        self.lab = WebLab(EXPERIMENT, describe(EXPERIMENT), 42, ArchiveStore(folder.name), lambda: self.now)
        self.lab.work.set_output(DETECTOR_OUTPUT, True)

    def test_five_short_windows_and_one_long_window_are_json_safe(self):
        self.lab.work.start(device='counter', window_s=1)
        self.lab.work.start(device='counter_b', window_s=5)
        self.lab.work.advance(5)
        state = self.lab.state()
        json.dumps(state, allow_nan=False)
        self.assertEqual(len(state['counter_windows']['counter']), 5)
        self.assertEqual(len(state['counter_windows']['counter_b']), 1)
        self.assertEqual([row['end_exposure_s'] - row['start_exposure_s']
                          for row in state['counter_windows']['counter']], [1] * 5)

    def test_clear_state_is_recoverable_without_page_local_request(self):
        self.lab.work.start(10, device='counter')
        self.lab.work.advance(3)
        request = self.lab.work.begin_clear(device='counter')
        self.lab._clear_requests.clear()
        state = self.lab.state()
        self.assertEqual(state['clear_confirmation'], dict(device='counter', token=request.token, exposure_s=3))
        self.lab.act(dict(action='finish_clear', device='counter', token=request.token, choice='cancel'))
        self.assertIsNone(self.lab.state()['clear_confirmation'])
        self.assertEqual(self.lab.work.session.instrument('counter').remaining_s, 7)

    def test_invalid_replacement_preserves_original_frozen_session_and_cache(self):
        app = Application(discover(), self.lab.store.directory, lambda: self.now)
        app.lab = self.lab
        self.lab.work.start(device='counter')
        self.lab.work.advance(3)
        self.lab.act(dict(action='snapshot', device='counter'))
        self.lab.act(dict(action='freeze'))
        before = self.lab.state()
        with self.assertRaises((ValueError, OSError)):
            app.request('/api/replace_package', dict(session=self.lab.id, confirmation_id=self.lab.confirmation_id,
                                                    file=b64encode(b'invalid experiment').decode()))
        self.assertIs(app.lab, self.lab)
        self.assertEqual(self.lab.state()['snapshots'], before['snapshots'])
        self.assertTrue(self.lab.frozen)
